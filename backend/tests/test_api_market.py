from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.app import app
from backend.db import session as db_session
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from backend.db.models import MarketData
from backend.services import market_service as ms

client = TestClient(app)


def test_market_empty_returns_error(monkeypatch):
    engine = engine_for_test()
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def _get_session():
        return Session()

    monkeypatch.setattr(db_session, "get_session", _get_session)
    monkeypatch.setattr(ms, "get_session", _get_session)

    r = client.get("/api/market/latest")
    assert r.status_code == 404
    assert "detail" in r.json()


def engine_for_test():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_market_returns_latest_day(monkeypatch):
    engine = engine_for_test()
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    s.add(MarketData(symbol="000300", name="沪深300", category="index",
                    close=3800.0, change_pct=0.5,
                    market_date="2026-06-30", source="akshare"))
    s.commit()

    def _get_session():
        return Session()

    monkeypatch.setattr(db_session, "get_session", _get_session)
    monkeypatch.setattr(ms, "get_session", _get_session)
    s.close()

    r = client.get("/api/market/latest")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["symbol"] == "000300"
    assert body["source"] == "akshare"
