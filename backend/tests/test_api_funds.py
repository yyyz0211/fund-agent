"""`/api/funds/*` 路由离线测试 —— `POST /refresh` 等增量端点。"""
import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.services import fund_service as fs

client = TestClient(app)


def test_refresh_success(monkeypatch):
    """refresh 成功:service 返回正常 dict,端点 200。"""
    monkeypatch.setattr(
        fs, "refresh_fund",
        lambda code, session=None: {
            "fund_code": code, "navs_inserted": 5,
            "already_up_to_date": False,
            "source": "akshare", "as_of": "2026-07-01",
        },
    )
    r = client.post("/api/funds/110011/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "110011"
    assert body["navs_inserted"] == 5
    assert body["already_up_to_date"] is False


def test_refresh_already_up_to_date(monkeypatch):
    """already_up_to_date=True 也返回 200(不是错误)。"""
    monkeypatch.setattr(
        fs, "refresh_fund",
        lambda code, session=None: {
            "fund_code": code, "navs_inserted": 0,
            "already_up_to_date": True,
            "source": "akshare", "as_of": "2026-07-01",
        },
    )
    r = client.post("/api/funds/110011/refresh")
    assert r.status_code == 200
    assert r.json()["already_up_to_date"] is True


def test_refresh_failure_returns_502(monkeypatch):
    """service 返回带 error 的 dict → 502(上游抓取失败)。"""
    monkeypatch.setattr(
        fs, "refresh_fund",
        lambda code, session=None: {"error": "akshare timeout", "source": "akshare"},
    )
    r = client.post("/api/funds/999999/refresh")
    assert r.status_code == 502
    assert "akshare timeout" in r.json()["detail"]