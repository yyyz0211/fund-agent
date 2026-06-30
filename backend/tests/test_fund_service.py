import pytest
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker
from backend.services import fund_service as fs
from backend.services import data_collector as dc


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


def test_get_latest_nav_no_data(session):
    out = fs.get_latest_nav("110011", session=session)
    assert "error" in out


def test_refresh_then_latest_and_metrics(session, monkeypatch):
    monkeypatch.setattr(dc, "fetch_fund_info", lambda c: {
        "fund_code": c, "fund_name": "FundA", "fund_type": "混合型",
        "manager": "X", "company": "Y", "source": "akshare", "as_of": "2026-06-30"})
    navs = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 11)]
    monkeypatch.setattr(dc, "fetch_fund_nav_history", lambda c: navs)

    r = fs.refresh_fund("110011", session=session)
    assert r["navs_inserted"] == 10

    latest = fs.get_latest_nav("110011", session=session)
    assert latest["accumulated_nav"] == pytest.approx(1.10)
    assert latest["source"] == "akshare"

    m = fs.get_metrics("110011", period="1w", session=session)
    assert m["max_drawdown"] is not None
    assert m["source"] == "akshare"


def test_refresh_propagates_collector_error(session, monkeypatch):
    monkeypatch.setattr(dc, "fetch_fund_info", lambda c: {
        "fund_code": c, "source": "akshare", "as_of": "2026-06-30"})
    monkeypatch.setattr(dc, "fetch_fund_nav_history",
                        lambda c: {"error": "boom", "source": "akshare"})
    out = fs.refresh_fund("110011", session=session)
    assert "error" in out
