import pytest
import backend.db.models  # noqa: F401
from backend.services.market import market_service as ms
from backend.db.models import MarketData

pytestmark = pytest.mark.db


@pytest.fixture()
def session(db_session):
    return db_session


def test_get_indices_no_data(session):
    assert "error" in ms.get_indices(session=session)


def test_get_indices_returns_latest_date_only(session):
    session.add(MarketData(symbol="000300", name="沪深300", category="index",
                           close=3800.0, change_pct=0.5, market_date="2026-06-29",
                           source="akshare"))
    session.add(MarketData(symbol="000300", name="沪深300", category="index",
                           close=3820.0, change_pct=0.6, market_date="2026-06-30",
                           source="akshare"))
    session.add(MarketData(symbol="000001", name="上证指数", category="index",
                           close=3100.0, change_pct=0.3, market_date="2026-06-30",
                           source="akshare"))
    session.commit()

    out = ms.get_indices(session=session)
    dates = {i["market_date"] for i in out["indices"]}
    assert dates == {"2026-06-30"}  # latest date only
    assert len(out["indices"]) == 2
    assert out["source"] == "akshare"
    assert "as_of" in out
