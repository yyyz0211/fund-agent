"""knowledge_reindex_jobs service 的单元测试。

覆盖核心场景：
- create_job 落 pending 行；
- mark_running / mark_completed / mark_failed 写状态；
- run_job_in_background 异步跑 pipeline 并写完成状态；
- get_job 返回 snapshot；
- list_jobs 返回最近的 N 条。
"""
from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import create_engine, text

from backend.db.init_db import init_db
from backend.db.session import Base, get_session
import backend.db.models  # noqa: F401  (注册模型)


@pytest.fixture
def _in_memory_db(monkeypatch):
    """每个测试用独立的内存 SQLite + 替换进程级 engine / SessionLocal / get_session。

    注意：使用 ``StaticPool`` 让内存 SQLite 在多线程下共享同一连接，
    否则后台线程里的 Session 会落到一个全新的空库（"no such table"）。
    """
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    init_db(engine)

    from backend.db import session as session_module
    from sqlalchemy.orm import sessionmaker

    new_session_local = sessionmaker(bind=engine, expire_on_commit=False)

    def _new_get_session():
        return new_session_local()

    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", new_session_local)
    monkeypatch.setattr(session_module, "get_session", _new_get_session)

    yield engine


def test_create_job_writes_pending_row(_in_memory_db):
    from backend.services import knowledge_reindex_jobs

    job = knowledge_reindex_jobs.create_job(trigger="manual")

    assert job.id is not None
    assert job.trigger == "manual"
    assert job.status == "pending"


def test_mark_running_and_completed(_in_memory_db):
    from backend.services import knowledge_reindex_jobs

    job = knowledge_reindex_jobs.create_job(trigger="manual")
    jid = int(job.id)

    knowledge_reindex_jobs.mark_running(jid)
    snapshot = knowledge_reindex_jobs.get_job(jid)
    assert snapshot is not None
    assert snapshot["status"] == "running"
    assert snapshot["started_at"] is not None

    knowledge_reindex_jobs.mark_completed(
        jid, result={"status": "completed", "indexed": 5}, latency_ms=1234,
    )
    snapshot = knowledge_reindex_jobs.get_job(jid)
    assert snapshot["status"] == "completed"
    assert snapshot["finished_at"] is not None
    assert snapshot["latency_ms"] == 1234
    assert snapshot["result"] == {"status": "completed", "indexed": 5}


def test_mark_failed(_in_memory_db):
    from backend.services import knowledge_reindex_jobs

    job = knowledge_reindex_jobs.create_job(trigger="manual")
    jid = int(job.id)

    knowledge_reindex_jobs.mark_failed(jid, error="boom", latency_ms=42)
    snapshot = knowledge_reindex_jobs.get_job(jid)
    assert snapshot["status"] == "failed"
    assert snapshot["error_message"] == "boom"
    assert snapshot["latency_ms"] == 42


def test_get_job_returns_none_for_missing(_in_memory_db):
    from backend.services import knowledge_reindex_jobs

    assert knowledge_reindex_jobs.get_job(9999) is None


def test_list_jobs_returns_recent_first(_in_memory_db):
    from backend.services import knowledge_reindex_jobs

    for i in range(3):
        knowledge_reindex_jobs.create_job(trigger="scheduled")

    jobs = knowledge_reindex_jobs.list_jobs(limit=10)
    assert len(jobs) == 3
    # id 倒序
    assert jobs[0]["job_id"] > jobs[1]["job_id"] > jobs[2]["job_id"]


def test_run_job_in_background_completes(monkeypatch, _in_memory_db):
    """后台线程跑 pipeline, 完成后状态应变成 completed。"""
    from backend.services import knowledge_reindex_jobs
    from backend.services import knowledge_search_service

    monkeypatch.setattr(
        knowledge_search_service,
        "run_knowledge_pipeline_once",
        lambda **kwargs: {"status": "completed", "indexed": 1},
    )

    job = knowledge_reindex_jobs.create_job(trigger="manual")
    jid = int(job.id)
    thread = knowledge_reindex_jobs.run_job_in_background(
        jid, pipeline_kwargs={"trigger": "manual"},
    )
    thread.join(timeout=5.0)
    assert not thread.is_alive()

    snapshot = knowledge_reindex_jobs.get_job(jid)
    assert snapshot["status"] == "completed"
    assert snapshot["result"] == {"status": "completed", "indexed": 1}


def test_run_job_in_background_marks_failed_on_exception(monkeypatch, _in_memory_db):
    from backend.services import knowledge_reindex_jobs
    from backend.services import knowledge_search_service

    def boom(**kwargs):
        raise RuntimeError("pipeline kaboom")

    monkeypatch.setattr(knowledge_search_service, "run_knowledge_pipeline_once", boom)

    job = knowledge_reindex_jobs.create_job(trigger="manual")
    jid = int(job.id)
    thread = knowledge_reindex_jobs.run_job_in_background(
        jid, pipeline_kwargs={"trigger": "manual"},
    )
    thread.join(timeout=5.0)
    assert not thread.is_alive()

    snapshot = knowledge_reindex_jobs.get_job(jid)
    assert snapshot["status"] == "failed"
    assert "pipeline kaboom" in snapshot["error_message"]


def test_recover_interrupted_jobs_marks_stale_pending(_in_memory_db):
    """超过 stale 阈值的 pending job 应被标记为 interrupted。"""
    from datetime import datetime, timedelta
    from backend.db import models as m
    from backend.services import knowledge_reindex_jobs

    # 落一条"旧" pending job (created_at 设为 2 小时前)
    old = m.KnowledgeReindexJob(trigger="scheduled", status="pending")
    with _in_memory_db.connect() as conn:
        conn.execute(
            m.KnowledgeReindexJob.__table__.insert().values(
                trigger="scheduled",
                status="pending",
                created_at=datetime.utcnow() - timedelta(hours=2),
            )
        )
        conn.commit()

    # 只恢复超过 1 小时的
    recovered = knowledge_reindex_jobs.recover_interrupted_jobs(older_than_seconds=3600)
    assert recovered == 1

    # 验证状态
    with _in_memory_db.connect() as conn:
        row = conn.execute(
            m.KnowledgeReindexJob.__table__.select()
        ).fetchone()
        assert row.status == "interrupted"
        assert row.finished_at is not None
        assert "Recovered after" in row.error_message


def test_recover_interrupted_jobs_ignores_recent_pending(_in_memory_db):
    """未超过 stale 阈值的 pending job 不应被标记为 interrupted。"""
    from backend.db import models as m
    from backend.services import knowledge_reindex_jobs

    # 落一条"新" pending job (刚创建)
    with _in_memory_db.connect() as conn:
        conn.execute(
            m.KnowledgeReindexJob.__table__.insert().values(
                trigger="scheduled",
                status="pending",
            )
        )
        conn.commit()

    recovered = knowledge_reindex_jobs.recover_interrupted_jobs(older_than_seconds=3600)
    assert recovered == 0

    # 验证仍是 pending
    with _in_memory_db.connect() as conn:
        row = conn.execute(
            m.KnowledgeReindexJob.__table__.select()
        ).fetchone()
        assert row.status == "pending"


def test_recover_interrupted_jobs_ignores_completed(_in_memory_db):
    """已完成的 job 不应被标记为 interrupted。"""
    from backend.db import models as m
    from backend.db.session import get_session
    from backend.services import knowledge_reindex_jobs

    with get_session() as s:
        job = m.KnowledgeReindexJob(trigger="scheduled", status="completed")
        s.add(job)
        s.commit()
        job_id = job.id

    recovered = knowledge_reindex_jobs.recover_interrupted_jobs(older_than_seconds=3600)
    assert recovered == 0

    with get_session() as s:
        job = s.get(m.KnowledgeReindexJob, job_id)
        assert job.status == "completed"


def test_recover_interrupted_jobs_multiple_stale(_in_memory_db):
    """多个 stale pending/running 应全部被恢复。"""
    from datetime import datetime, timedelta
    from backend.db import models as m
    from backend.services import knowledge_reindex_jobs

    now = datetime.utcnow()
    with _in_memory_db.connect() as conn:
        conn.execute(m.KnowledgeReindexJob.__table__.insert().values(
            trigger="scheduled", status="pending",
            created_at=now - timedelta(hours=2),
        ))
        conn.execute(m.KnowledgeReindexJob.__table__.insert().values(
            trigger="scheduled", status="running",
            created_at=now - timedelta(hours=3),
        ))
        conn.execute(m.KnowledgeReindexJob.__table__.insert().values(
            trigger="scheduled", status="pending",
            created_at=now - timedelta(minutes=30),
        ))
        conn.commit()

    recovered = knowledge_reindex_jobs.recover_interrupted_jobs(older_than_seconds=3600)
    assert recovered == 2  # 2 小时和 3 小时的那两条

    with _in_memory_db.connect() as conn:
        rows = conn.execute(
            m.KnowledgeReindexJob.__table__.select()
            .order_by(m.KnowledgeReindexJob.id)
        ).fetchall()
        statuses = [r.status for r in rows]
        assert statuses.count("interrupted") == 2
        assert statuses.count("pending") == 1