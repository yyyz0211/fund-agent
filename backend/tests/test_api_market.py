import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.db.models import MarketData
from backend.services.market import market_service as ms

client = TestClient(app)
pytestmark = pytest.mark.db


def test_market_empty_returns_error(db_session):
    r = client.get("/api/market/latest")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_market_returns_latest_day(db_session):
    db_session.add(MarketData(symbol="000300", name="沪深300", category="index",
                    close=3800.0, change_pct=0.5,
                    market_date="2026-06-30", source="akshare"))
    db_session.commit()

    r = client.get("/api/market/latest")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["symbol"] == "000300"
    assert body["source"] == "akshare"
