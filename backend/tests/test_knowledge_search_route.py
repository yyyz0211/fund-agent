from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.app import app
from backend.api.deps import get_db_session
from backend.db.init_db import init_db


@pytest.fixture(autouse=True)
def isolated_db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'knowledge-route.db'}",
        connect_args={"check_same_thread": False},
    )
    init_db(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def dependency():
        with sessions() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    had_db_override = get_db_session in app.dependency_overrides
    previous_db_override = app.dependency_overrides.get(get_db_session)
    app.dependency_overrides[get_db_session] = dependency
    try:
        yield sessions
    finally:
        if had_db_override:
            app.dependency_overrides[get_db_session] = previous_db_override
        else:
            app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()


def test_knowledge_search_accepts_fund_code_filter():
    client = TestClient(app)

    response = client.get("/api/knowledge/search", params={
        "query": "人工智能",
        "fund_code": "000000",
    })

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_knowledge_search_rejects_invalid_date():
    response = TestClient(app).get(
        "/api/knowledge/search",
        params={"date_from": "not-a-date"},
    )

    assert response.status_code == 422


def test_knowledge_search_rejects_inverted_date_range():
    response = TestClient(app).get(
        "/api/knowledge/search",
        params={"date_from": "2026-07-10", "date_to": "2026-07-01"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "date_from must not be later than date_to"


def test_knowledge_queue_status_route_shape(monkeypatch):
    from backend.api.routes import knowledge as route

    monkeypatch.setattr(route.knowledge_search_service, "get_queue_status", lambda **kwargs: {
        "counts": {"by_classification": {}, "by_index": {}},
        "items": [],
    })
    client = TestClient(app)

    response = client.get("/api/knowledge/queue-status")

    assert response.status_code == 200
    assert response.json()["counts"] == {"by_classification": {}, "by_index": {}}


def test_knowledge_reindex_requires_local_trigger(monkeypatch):
    from backend.api.routes import knowledge as route

    called = {"value": False}

    def fake_reindex(**kwargs):
        called["value"] = True
        return {"status": "ok"}

    monkeypatch.setattr(route.knowledge_search_service, "run_knowledge_pipeline_once", fake_reindex)
    client = TestClient(app)

    response = client.post("/api/knowledge/reindex")

    assert response.status_code == 403
    assert response.json()["detail"] == "missing X-Local-Trigger header"
    assert called["value"] is False


def test_ordinary_reindex_never_rebuilds_vector_schema(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.api.deps import get_db_session
    from backend.api.routes import knowledge as route
    from backend.db.init_db import init_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ordinary-reindex.db'}",
        connect_args={"check_same_thread": False},
    )
    init_db(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def dependency():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db_session] = dependency
    monkeypatch.setattr(
        route,
        "rebuild_pgvector_schema",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary reindex must not rebuild vector schema")
        ),
    )
    monkeypatch.setattr(
        route.knowledge_reindex_jobs,
        "run_job_in_background",
        lambda *_args, **_kwargs: None,
    )
    try:
        response = TestClient(app).post(
            "/api/knowledge/reindex",
            headers={"X-Local-Trigger": "1"},
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()

    assert response.status_code == 202


def test_vector_schema_rebuild_requires_local_trigger(monkeypatch):
    from backend.api.routes import knowledge as route

    called = {"value": False}

    def fake_rebuild(*args, **kwargs):
        called["value"] = True
        return 0

    monkeypatch.setattr(route, "rebuild_pgvector_schema", fake_rebuild)

    response = TestClient(app).post(
        "/api/knowledge/vector-schema/rebuild",
        params={"confirm": "true"},
    )

    assert response.status_code == 403
    assert called["value"] is False


def test_vector_schema_rebuild_requires_confirmation(monkeypatch):
    from backend.api.routes import knowledge as route

    def fake_rebuild(_engine, _dimensions, *, confirmed):
        assert confirmed is False
        raise ValueError("vector schema rebuild requires confirm=true")

    monkeypatch.setattr(route, "rebuild_pgvector_schema", fake_rebuild)

    response = TestClient(app).post(
        "/api/knowledge/vector-schema/rebuild",
        headers={"X-Local-Trigger": "1"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "vector schema rebuild requires confirm=true"


def test_vector_schema_rebuild_returns_requeued_document_count(monkeypatch):
    from backend.api.routes import knowledge as route

    monkeypatch.setattr(
        route,
        "rebuild_pgvector_schema",
        lambda _engine, _dimensions, *, confirmed: 7 if confirmed else 0,
    )

    response = TestClient(app).post(
        "/api/knowledge/vector-schema/rebuild",
        params={"confirm": "true"},
        headers={"X-Local-Trigger": "true"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "rebuilt", "requeued_documents": 7}


def test_knowledge_reindex_with_local_trigger(monkeypatch, isolated_db_session):
    """POST /api/knowledge/reindex 立刻返回 202 + job_id, 后台跑 pipeline。

    旧版本会同步阻塞到 pipeline 完成；新版本走异步任务。
    """
    from backend.api.routes import knowledge as route
    from backend.services import knowledge_reindex_jobs as jobs_module

    calls: list[dict] = []

    def _fake_run_in_background(job_id, *, pipeline_kwargs):
        calls.append({"job_id": job_id, "kwargs": dict(pipeline_kwargs)})
        # 返回一个真实 Thread, 但 target 不做副作用
        import threading

        return threading.Thread(target=lambda: None, daemon=True)

    monkeypatch.setattr(jobs_module, "run_job_in_background", _fake_run_in_background)

    response = TestClient(app).post(
        "/api/knowledge/reindex",
        headers={"X-Local-Trigger": "1"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "started"
    assert isinstance(body["job_id"], int) and body["job_id"] > 0
    assert body["trigger"] == "manual"
    assert body["poll_url"] == f"/api/knowledge/reindex/{body['job_id']}"
    assert len(calls) == 1
    assert calls[0]["job_id"] == body["job_id"]
    assert calls[0]["kwargs"]["trigger"] == "manual"


def test_knowledge_reindex_job_status_404_when_missing():
    client = TestClient(app)
    response = client.get("/api/knowledge/reindex/9999999")
    assert response.status_code == 404


def test_knowledge_reindex_commits_job_before_background_start(monkeypatch, tmp_path):
    """后台线程启动时，pending job 必须已对新数据库连接可见。"""
    from backend.api.routes import knowledge as route
    from backend.db.models import KnowledgeReindexJob

    engine = create_engine(
        f"sqlite:///{tmp_path / 'reindex.db'}",
        connect_args={"check_same_thread": False},
    )
    init_db(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def dependency():
        with sessions() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    seen: list[bool] = []

    def fake_background(job_id, *, pipeline_kwargs):
        with sessions() as check:
            seen.append(check.get(KnowledgeReindexJob, job_id) is not None)

    previous_db_override = app.dependency_overrides[get_db_session]
    app.dependency_overrides[get_db_session] = dependency
    monkeypatch.setattr(
        route.knowledge_reindex_jobs,
        "run_job_in_background",
        fake_background,
    )
    try:
        response = TestClient(app).post(
            "/api/knowledge/reindex",
            headers={"X-Local-Trigger": "1"},
        )
    finally:
        app.dependency_overrides[get_db_session] = previous_db_override
        engine.dispose()

    assert response.status_code == 202
    assert seen == [True]
