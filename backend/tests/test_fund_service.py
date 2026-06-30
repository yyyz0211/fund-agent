import pytest
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker
from backend.services import fund_service as fs
from backend.services import data_collector as dc
from backend.db import repository as repo


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


def test_get_metrics_invalid_period_returns_error(session, monkeypatch):
    navs = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 4)]
    repo.upsert_navs(session, "110011", navs)

    out = fs.get_metrics("110011", period="bad", session=session)

    assert out["error"] == "unsupported period: bad"
    assert out["source"] == "akshare"


def test_refresh_propagates_collector_error(session, monkeypatch):
    monkeypatch.setattr(dc, "fetch_fund_info", lambda c: {
        "fund_code": c, "source": "akshare", "as_of": "2026-06-30"})
    monkeypatch.setattr(dc, "fetch_fund_nav_history",
                        lambda c: {"error": "boom", "source": "akshare"})
    out = fs.refresh_fund("110011", session=session)
    assert "error" in out


def test_get_basic_info_no_data(session):
    assert "error" in fs.get_basic_info("110011", session=session)


def test_get_basic_info_returns_row(session):
    repo.upsert_fund(session, {"fund_code": "110011", "fund_name": "FundA",
                               "fund_type": "混合型", "manager": "X", "company": "Y"})
    out = fs.get_basic_info("110011", session=session)
    assert out["fund_name"] == "FundA"
    assert out["source"] == "akshare"
    assert "as_of" in out


def test_get_nav_history_no_data(session):
    assert "error" in fs.get_nav_history("110011", session=session)


def test_get_nav_history_full_and_range(session):
    rows = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 11)]
    repo.upsert_navs(session, "110011", rows)

    full = fs.get_nav_history("110011", session=session)
    assert full["count"] == 10
    assert full["navs"][0]["nav_date"] == "2026-06-01"
    assert "accumulated_nav" in full["navs"][0]
    assert full["source"] == "akshare"

    ranged = fs.get_nav_history("110011", start_date="2026-06-03",
                                end_date="2026-06-05", session=session)
    assert [r["nav_date"] for r in ranged["navs"]] == \
        ["2026-06-03", "2026-06-04", "2026-06-05"]
    assert ranged["count"] == 3
