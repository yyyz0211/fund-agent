"""briefing 路由测试。

覆盖:
- GET /api/briefing/latest 返回最近一篇 + 空状态
- GET /api/briefing/list 排序 + limit
- POST /api/briefing/run local-only 鉴权
"""
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.api.routes import briefing as briefing_route

pytestmark = pytest.mark.db_multiconnection


@pytest.fixture
def client_with_session(db_multiconnection_engine):
    """FastAPI TestClient + PostgreSQL worker schema session factory。"""
    from sqlalchemy.orm import sessionmaker

    from backend.api.deps import get_db_session
    from backend.api.app import app

    TestingSession = sessionmaker(bind=db_multiconnection_engine, expire_on_commit=False)

    def _override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db_session] = _override

    client = TestClient(app)
    try:
        yield client, TestingSession
    finally:
        client.close()
        app.dependency_overrides.pop(get_db_session, None)


def _insert_briefing(
    session_factory,
    *,
    briefing_date: str,
    title: str,
    markdown: str,
    brief_type: str = "post_market",
):
    s = session_factory()
    try:
        from backend.db.models import Briefing
        b = Briefing(
            briefing_date=briefing_date, brief_type=brief_type,
            title=title, markdown=markdown,
            sections_json='{"market_snapshot":[],"watchlist_changes":[]}',
            source="akshare + deepseek", as_of=briefing_date,
        )
        s.add(b)
        s.commit()
        s.refresh(b)
        return b.id
    finally:
        s.close()


class TestRouteLatest:
    def test_route_latest_returns_briefing(self, client_with_session):
        client, session_factory = client_with_session
        _insert_briefing(
            session_factory,
            briefing_date="2026-07-06",
            title="2026-07-06 简报",
            markdown="## 今日\n\n沪深300+0.5%",
        )

        resp = client.get("/api/briefing/latest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["briefing"] is not None
        assert body["briefing"]["title"] == "2026-07-06 简报"
        assert "沪深300+0.5%" in body["briefing"]["markdown"]
        assert body["briefing"]["as_of"] == "2026-07-06"

    def test_route_latest_empty(self, client_with_session):
        client, _ = client_with_session
        resp = client.get("/api/briefing/latest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["briefing"] is None


class TestRouteList:
    def test_route_list_respects_limit(self, client_with_session):
        client, session_factory = client_with_session
        for i in range(1, 6):
            _insert_briefing(
                session_factory,
                briefing_date=f"2026-07-0{i}",
                title=f"简报 {i}",
                markdown=f"content {i}",
            )

        resp = client.get("/api/briefing/list?limit=3")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 3
        assert len(body["briefings"]) == 3
        # 按日期降序
        dates = [b["briefing_date"] for b in body["briefings"]]
        assert dates == sorted(dates, reverse=True)


class TestRouteRun:
    def test_route_run_local_only(self, client_with_session):
        client, _ = client_with_session

        # 不带 header → 403
        resp = client.post("/api/briefing/run")
        assert resp.status_code == 403

        # 带 header → 触发
        def mock_run(**_kwargs):
            return {"status": "started", "trigger": "manual"}

        with patch.object(briefing_route.briefing_jobs, "start_run_async", mock_run):
            resp = client.post("/api/briefing/run", headers={"X-Local-Trigger": "1"})
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "started"

    def test_route_run_accepts_brief_type_body(self, client_with_session):
        client, _ = client_with_session
        captured = {}

        def mock_run(**kwargs):
            captured.update(kwargs)
            return {"status": "started", "trigger": "manual", "brief_type": kwargs["brief_type"]}

        with patch.object(briefing_route.briefing_jobs, "start_run_async", mock_run):
            resp = client.post(
                "/api/briefing/run",
                headers={"X-Local-Trigger": "1"},
                json={"brief_type": "pre_market"},
            )

        assert resp.status_code == 202
        assert captured["trigger"] == "manual"
        assert captured["brief_type"] == "pre_market"
        assert captured["model"] is not None
        assert resp.json()["brief_type"] == "pre_market"
