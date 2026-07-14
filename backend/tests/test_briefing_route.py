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


@pytest.fixture
def client_with_session():
    """FastAPI TestClient + in-memory DB session。

    策略:
    - 让 `get_settings()` 指向 in-memory,这样 app.on_event("startup") 触发的
      init_db 也会建到同一张内存库里(虽然其实每个 connection 独立,但 SQLAlchemy
      SQLite memory 用 StaticPool 才能多 connection 共享)
    - 使用 StaticPool 让 :memory: 在多连接下共享同一张库
    - override `get_session` 让 route 用同样的测试 session 工厂
    """
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.api.deps import get_db_session
    from backend.db.session import Base, engine, SessionLocal
    from backend.api.app import app

    # 1) 引入模型,确保 Base.metadata 注册完整
    from backend.db.models import Briefing, Fund, Watchlist  # noqa: F401

    # 2) 关掉 startup hook 中的 scheduler 启动;init_db 也用 monkeypatch 跳过
    import backend.scheduler as scheduler_module
    orig_start = scheduler_module.start_scheduler
    scheduler_module.start_scheduler = lambda *args, **kwargs: None

    # 3) 替换全局 engine 为 in-memory + StaticPool,这样 init_db / route / 测试插入
    #    都共享同一张 :memory: 库
    test_engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)

    # monkeypatch 全局 engine 和 SessionLocal
    import backend.db.session as session_module
    orig_engine = session_module.engine
    orig_session_local = session_module.SessionLocal
    session_module.engine = test_engine
    session_module.SessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)
    # 同步 app 内的 startup hook(它 import 时取了旧引用)
    from backend.db import init_db as init_db_module
    orig_init = init_db_module.init_db
    init_db_module.init_db = lambda: None  # 防止它在 in-memory engine 上重复跑

    TestingSession = sessionmaker(bind=test_engine)

    def _override():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db_session] = _override

    with TestClient(app) as client:
        yield client, TestingSession

    app.dependency_overrides.clear()
    session_module.engine = orig_engine
    session_module.SessionLocal = orig_session_local
    init_db_module.init_db = orig_init
    scheduler_module.start_scheduler = orig_start


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

        from backend.services.briefing import briefing_service
        with patch.object(briefing_service, "start_run_async", mock_run):
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

        from backend.services.briefing import briefing_service
        with patch.object(briefing_service, "start_run_async", mock_run):
            resp = client.post(
                "/api/briefing/run",
                headers={"X-Local-Trigger": "1"},
                json={"brief_type": "pre_market"},
            )

        assert resp.status_code == 202
        assert captured == {"trigger": "manual", "brief_type": "pre_market"}
        assert resp.json()["brief_type"] == "pre_market"
