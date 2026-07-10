from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.app import app


def test_knowledge_search_rejects_fund_code_before_fund_matching():
    client = TestClient(app)

    response = client.get("/api/knowledge/search", params={
        "query": "人工智能",
        "fund_code": "000000",
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "fund_code filter requires knowledge fund matching"


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


def test_knowledge_reindex_with_local_trigger(monkeypatch):
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

    client = TestClient(app)

    response = client.post("/api/knowledge/reindex", headers={"X-Local-Trigger": "1"})

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
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.api.deps import get_db_session
    from backend.api.routes import knowledge as route
    from backend.db.init_db import init_db
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
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert seen == [True]
