"""market intel API routes 集成测试。"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.api.app import app
    return TestClient(app)


def test_snapshot_endpoint_returns_structure(client):
    """snapshot API 返回包含预期 keys 的 dict。"""
    with patch("backend.services.market_intel_service.get_market_snapshot",
               return_value={
                   "trade_date": "2026-07-07",
                   "snapshot_type": "post_market",
                   "indices": [], "breadth": {}, "industry_sectors": [],
                   "concept_sectors": [], "industry_flows": [], "concept_flows": [],
                   "themes": [], "breadth_indicators": {}, "overseas": [],
                   "announcements": [], "source": "akshare", "as_of": "2026-07-07",
               }):
        response = client.get("/api/market/snapshot?date=2026-07-07&type=post_market")
    assert response.status_code == 200
    data = response.json()
    assert "trade_date" in data
    assert "snapshot_type" in data
    assert "industry_sectors" in data


def test_sectors_endpoint_returns_rows(client):
    """sectors API 返回 rows 列表。"""
    with patch("backend.services.data_collector.fetch_sector_snapshot",
               return_value=[{"name": "游戏", "change_pct": 2.39}]):
        response = client.get("/api/market/sectors?kind=industry&sort=change_pct&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "rows" in data
    assert isinstance(data["rows"], list)


def test_refresh_requires_header(client):
    """refresh API 无 X-Local-Trigger 时返回 403。"""
    response = client.post("/api/market/refresh")
    assert response.status_code == 403


def test_refresh_with_header_returns_started(client):
    """refresh API 有 X-Local-Trigger 时返回 started。"""
    with patch("backend.services.market_intel_service.refresh_market_intel_async",
               return_value={"status": "started", "trigger": "manual", "job_id": "abc123"}):
        response = client.post("/api/market/refresh",
                               headers={"X-Local-Trigger": "1"})
    assert response.status_code == 200
    assert response.json()["status"] == "started"
