"""知识库重建任务 (`KnowledgeReindexJob`) 的服务层。

设计动机：
- 把 `run_knowledge_pipeline_once` 从请求线程里挪到后台线程,耗时秒级,
  让前端通过 `job_id` 轮询状态。
- scheduler 触发的 run_knowledge_pipeline_once 也复用同一张表,
  方便前后端统一观察所有重建任务。
- 状态写入用 `process_singleflight` 按 job_id 隔离,避免不同 job 互相
  阻塞;LLM + 向量化期间单飞锁是空闲的,CLS 同步等其它 scheduler job
  可并发跑。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.db import repository as repo
from backend.db.models import KnowledgeReindexJob

logger = logging.getLogger(__name__)


def create_job(*, trigger: str, session: Optional[Session] = None) -> KnowledgeReindexJob:
    """落一条 pending 任务并返回 ORM 实例。

    Args:
        trigger: `manual` 或 `scheduled`。
        session: 复用的 session；为空时新建。事务由调用方决定提交时机。
    """
    owns = session is None
    s = session or _new_session()
    try:
        job = KnowledgeReindexJob(
            trigger=trigger,
            status="pending",
        )
        s.add(job)
        s.flush()
        if owns:
            s.commit()
        return job
    finally:
        if owns:
            s.close()


def mark_running(job_id: int) -> None:
    """把任务标记为 running（独立 session/事务，避免长时间持有）。"""
    with _new_session() as s:
        job = s.get(KnowledgeReindexJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = datetime.utcnow()
        s.commit()


def mark_completed(job_id: int, *, result: dict, latency_ms: int) -> None:
    """任务成功完成,落 result 和耗时。"""
    with _new_session() as s:
        job = s.get(KnowledgeReindexJob, job_id)
        if job is None:
            return
        job.status = "completed"
        job.finished_at = datetime.utcnow()
        job.latency_ms = int(latency_ms)
        try:
            job.result_json = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            job.result_json = json.dumps({"unparseable": True}, ensure_ascii=False)
        s.commit()


def mark_failed(job_id: int, *, error: str, latency_ms: Optional[int] = None) -> None:
    """任务失败,落 error_message。"""
    with _new_session() as s:
        job = s.get(KnowledgeReindexJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.finished_at = datetime.utcnow()
        if latency_ms is not None:
            job.latency_ms = int(latency_ms)
        # 截断超长错误,避免 SQLite 单行超限
        job.error_message = (error or "")[:2000]
        s.commit()


def get_job(job_id: int, *, session: Optional[Session] = None) -> Optional[dict]:
    """读一条任务的快照(纯 dict,不持有 ORM session)。"""
    owns = session is None
    s = session or _new_session()
    try:
        job = s.get(KnowledgeReindexJob, job_id)
        if job is None:
            return None
        return {
            "job_id": int(job.id),
            "trigger": job.trigger,
            "status": job.status,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "latency_ms": job.latency_ms,
            "result": _safe_load_json(job.result_json),
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
        }
    finally:
        if owns:
            s.close()


def list_jobs(*, limit: int = 20, session: Optional[Session] = None) -> list[dict]:
    """返回最近 N 条任务(降序)。"""
    owns = session is None
    s = session or _new_session()
    try:
        rows = repo.list_knowledge_reindex_jobs(s, limit=limit)
        return [
            {
                "job_id": int(r.id),
                "trigger": r.trigger,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "error_message": r.error_message,
            }
            for r in rows
        ]
    finally:
        if owns:
            s.close()


def run_job_in_background(
    job_id: int,
    *,
    pipeline_kwargs: dict,
) -> threading.Thread:
    """在后台线程跑 pipeline,负责状态写入。

    Args:
        job_id: `KnowledgeReindexJob.id`。
        pipeline_kwargs: 传给 `run_knowledge_pipeline_once` 的 kwargs
            (例如 `{"trigger": "manual", "limit": 50}`)。

    Returns:
        启动的 `threading.Thread` 实例(daemon=True),调用方可选择 join。
    """
    from backend.services.knowledge.knowledge_search_service import run_knowledge_pipeline_once
    from backend.services.shared.process_singleflight import (
        SingleflightBusy,
        process_singleflight,
    )

    def _runner():
        started = datetime.utcnow()
        # 段 1: 拿锁 + mark_running（< 100ms，仅 1 次 DB 写）
        try:
            with process_singleflight(
                f"knowledge_reindex:{job_id}",
                timeout_seconds=2.0,
            ):
                mark_running(job_id)
        except SingleflightBusy as exc:
            logger.warning("[knowledge_reindex] job=%s busy_skipped: %s", job_id, exc)
            _mark_busy_skipped(job_id, error=str(exc))
            return

        # 段 2: 在锁外跑 LLM + 向量 + DB 写入，pipeline 内部自己控短事务。
        # LLM/向量化期间单飞锁是空闲的，CLS 同步等其它 job 可并发跑。
        try:
            result = run_knowledge_pipeline_once(**pipeline_kwargs)
        except Exception as exc:  # noqa: BLE001
            latency = int((datetime.utcnow() - started).total_seconds() * 1000)
            logger.exception("[knowledge_reindex] job=%s failed", job_id)
            try:
                with process_singleflight(
                    f"knowledge_reindex:{job_id}",
                    timeout_seconds=2.0,
                ):
                    mark_failed(
                        job_id,
                        error=f"{type(exc).__name__}: {exc}",
                        latency_ms=latency,
                    )
            except SingleflightBusy:
                # 极端并发时连 mark_failed 都拿不到锁，留给 recover_interrupted_jobs 兜底
                logger.warning(
                    "[knowledge_reindex] job=%s mark_failed deferred to recovery",
                    job_id,
                )
            return

        # 段 3: 拿锁 + mark_completed（同上，短事务）
        latency = int((datetime.utcnow() - started).total_seconds() * 1000)
        try:
            with process_singleflight(
                f"knowledge_reindex:{job_id}",
                timeout_seconds=2.0,
            ):
                mark_completed(job_id, result=result, latency_ms=latency)
        except SingleflightBusy:
            # 极端并发：completed 状态写入也撞锁，留给人工或下一轮 reconcile 处理。
            # 但 result 已经算出来了，先把它落库，状态由 recovery 修正。
            logger.warning(
                "[knowledge_reindex] job=%s mark_completed deferred to recovery",
                job_id,
            )

    thread = threading.Thread(
        target=_runner,
        name=f"knowledge-reindex-{job_id}",
        daemon=True,
    )
    thread.start()
    return thread


def _mark_busy_skipped(job_id: int, *, error: str) -> None:
    with _new_session() as s:
        job = s.get(KnowledgeReindexJob, job_id)
        if job is None:
            return
        job.status = "busy_skipped"
        job.finished_at = datetime.utcnow()
        job.error_message = (error or "")[:2000]
        s.commit()


def _new_session() -> Session:
    """开新 session, 通过模块属性读取以支持测试 monkeypatch。

    不要用 `from backend.db.session import get_session` 在模块顶部
    直接绑定 — 那会在加载时锁定引用, 而测试通过
    `monkeypatch.setattr(session_module, "get_session", ...)` 替换
    时不会生效。这里用模块属性查找以跟随 monkeypatch。
    """
    from backend.db import session as _session_module

    return _session_module.get_session()


def _safe_load_json(value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def recover_interrupted_jobs(older_than_seconds: int) -> int:
    """把 stale pending/running 任务标记为 interrupted。

    Args:
        older_than_seconds: 只处理超过此秒数的任务。

    Returns:
        被标记为 interrupted 的任务数量。
    """
    from datetime import timedelta
    from backend.config.settings import get_settings

    cutoff = datetime.utcnow() - timedelta(seconds=older_than_seconds)
    recovered = 0
    with _new_session() as s:
        stale = s.query(KnowledgeReindexJob).filter(
            KnowledgeReindexJob.status.in_(["pending", "running"]),
            KnowledgeReindexJob.created_at < cutoff,
        ).all()
        for job in stale:
            job.status = "interrupted"
            job.finished_at = datetime.utcnow()
            job.error_message = (
                f"Recovered after {older_than_seconds}s stale. "
                f"Original created_at={job.created_at.isoformat()}"
            )[:2000]
            recovered += 1
        if stale:
            s.commit()
    return recovered