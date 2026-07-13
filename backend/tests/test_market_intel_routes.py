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


def test_evidence_endpoint_returns_grouped_rows(client):
    """evidence API 返回按类别分组的证据。"""
    with patch("backend.services.market_evidence_service.search_evidence",
               return_value=[
                   {
                       "id": 1,
                       "trade_date": "2026-07-07",
                       "category": "policy",
                       "title": "创新药政策",
                       "summary": "审评提速。",
                       "source": "NMPA",
                       "source_url": "https://example.gov/a",
                       "published_at": "2026-07-07",
                       "reliability": "official",
                   },
                   {
                       "id": 2,
                       "trade_date": "2026-07-07",
                       "category": "macro",
                       "title": "FRED 利率",
                       "summary": "DFF = 4.25",
                       "source": "FRED",
                       "source_url": "https://fred.stlouisfed.org/series/DFF",
                       "published_at": "2026-07-06",
                       "reliability": "official",
                   },
               ]):
        response = client.get("/api/market/evidence?date=2026-07-07&limit=20")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert data["items"][0]["title"] == "创新药政策"
    assert data["items"][1]["source"] == "FRED"
    assert data["groups"]["policy"][0]["title"] == "创新药政策"
    assert data["groups"]["macro"][0]["source"] == "FRED"


def test_evidence_refresh_status_endpoint_returns_last_result(client):
    with patch(
        "backend.services.market_evidence_service.get_last_refresh_status",
        return_value={
            "status": "failed",
            "brief_type": "post_market",
            "result": {
                "inserted": 0,
                "fetched": 0,
                "errors": [{"adapter": "财联社", "error": "ConnectError"}],
                "categories": {},
            },
        },
    ):
        response = client.get("/api/market/evidence/refresh/status?brief_type=post_market")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["result"]["errors"][0]["adapter"] == "财联社"


def test_cls_telegraph_endpoint_returns_items(client):
    with patch(
        "backend.services.cls_telegraph_sync_service.list_cls_telegraph_items",
        return_value=[
            {
                "cls_id": "2421002",
                "title": "财联社电报：基金市场回暖",
                "brief": "基金市场回暖",
                "content": "基金市场回暖",
                "category": "fund",
                "subjects": ["盘面直播"],
                "symbols": ["沪深300"],
                "source_url": "https://www.cls.cn/detail/2421002",
                "ctime": 1783564494,
                "published_at": "2026-07-09 10:34:54",
                "fetched_at": "2026-07-09T10:35:00",
                "raw_json": {"id": 2421002},
            }
        ],
    ) as mocked:
        response = client.get("/api/cls/telegraph?limit=5&category=fund&keyword=基金&since_id=2420000")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["cls_id"] == "2421002"
    mocked.assert_called_once()
    assert mocked.call_args.kwargs["limit"] == 5
    assert mocked.call_args.kwargs["category"] == "fund"
    assert mocked.call_args.kwargs["keyword"] == "基金"
    assert mocked.call_args.kwargs["since_id"] == "2420000"


def test_cls_telegraph_sync_status_endpoint_returns_state(client):
    with patch(
        "backend.services.cls_telegraph_sync_service.get_cls_telegraph_sync_status",
        return_value={
            "status": "ok",
            "last_success_at": "2026-07-09T10:35:00+08:00",
            "latest_cls_id": "2421002",
            "lag_seconds": 30,
            "last_error": None,
        },
    ):
        response = client.get("/api/cls/telegraph/sync/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["latest_cls_id"] == "2421002"
    assert data["lag_seconds"] == 30
