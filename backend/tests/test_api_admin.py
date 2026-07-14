"""`/api/admin/*` 定时刷新接口的离线测试。"""
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.services.market import scheduled_refresh as sr

client = TestClient(app)


def test_refresh_status_empty_default():
    sr.reset_for_tests()
    r = client.get("/api/admin/refresh-status")
    assert r.status_code == 200
    body = r.json()
    assert body["last_run_at"] is None
    assert body["total"] == 0
    assert body["failures"] == []


def test_refresh_status_returns_snapshot(monkeypatch):
    sr.reset_for_tests()
    monkeypatch.setattr(
        sr, "get_last_run",
        lambda: {
            "last_run_at": "2026-07-06T20:00:03",
            "trigger": "scheduled",
            "total": 8,
            "succeeded": 7,
            "failed": 1,
            "already_up_to_date": 5,
            "failures": [{"fund_code": "000001", "error": "akshare timeout"}],
        },
    )
    r = client.get("/api/admin/refresh-status")
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == 7
    assert body["failures"][0]["fund_code"] == "000001"


def test_post_refresh_all_returns_started(monkeypatch):
    from backend.api.routes import admin as admin_routes

    monkeypatch.setattr(
        admin_routes.sr, "start_refresh_all_async",
        lambda trigger="manual": {"status": "started", "total": 3},
    )
    r = client.post("/api/admin/refresh-all")
    assert r.status_code == 202
    assert r.json() == {"status": "started", "total": 3}
