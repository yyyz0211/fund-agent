import pytest
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker
from backend.db import repository as repo
from backend.db.models import FundNav


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    s = Local()
    yield s
    s.close()


def test_watchlist_crud(session):
    row = repo.add_to_watchlist(session, "110011", note="hold")
    assert row["fund_code"] == "110011"
    assert repo.add_to_watchlist(session, "110011")["fund_code"] == "110011"  # idempotent
    assert len(repo.get_watchlist(session)) == 1
    repo.update_watchlist_note(session, "110011", "watch")
    assert repo.get_watchlist(session)[0]["note"] == "watch"
    assert repo.remove_from_watchlist(session, "110011") is True
    assert repo.remove_from_watchlist(session, "110011") is False
    assert repo.get_watchlist(session) == []


def test_upsert_navs_dedup_and_read(session):
    rows = [
        {"nav_date": "2026-06-01", "unit_nav": 1.0, "accumulated_nav": 2.0,
         "daily_return": 0.0, "source": "akshare", "source_updated_at": "2026-06-30"},
        {"nav_date": "2026-06-02", "unit_nav": 1.1, "accumulated_nav": 2.1,
         "daily_return": 0.05, "source": "akshare", "source_updated_at": "2026-06-30"},
    ]
    assert repo.upsert_navs(session, "110011", rows) == 2
    assert repo.upsert_navs(session, "110011", rows) == 0  # dedup
    assert repo.get_accumulated_navs(session, "110011") == [2.0, 2.1]


def test_upsert_fund(session):
    repo.upsert_fund(session, {"fund_code": "110011", "fund_name": "FundA"})
    repo.upsert_fund(session, {"fund_code": "110011", "fund_name": "FundA v2"})
    from backend.db.models import Fund
    assert session.get(Fund, "110011").fund_name == "FundA v2"


def test_upsert_and_get_fund_profile(session):
    repo.upsert_fund_profile(session, "110011", {
        "scale": 12.5,
        "scale_date": "2026-06-30",
        "peer_category": "混合型",
        "rank_total": 100,
        "rank_position": 12,
        "peer_candidates_json": '[{"fund_code":"000001"}]',
        "top10_holding_pct": 42.3,
        "top_industry_pct": 30.1,
        "manager_summary": "经理A 任职稳定",
        "source": "akshare",
        "as_of": "2026-07-02",
        "raw_errors": "[]",
    })
    repo.upsert_fund_profile(session, "110011", {
        "scale": 13.5,
        "rank_position": 8,
        "raw_errors": '["scale stale"]',
    })

    profile = repo.get_fund_profile(session, "110011")

    assert profile["fund_code"] == "110011"
    assert profile["scale"] == pytest.approx(13.5)
    assert profile["scale_date"] == "2026-06-30"
    assert profile["peer_category"] == "混合型"
    assert profile["rank_total"] == 100
    assert profile["rank_position"] == 8
    assert profile["peer_candidates_json"] == '[{"fund_code":"000001"}]'
    assert profile["top10_holding_pct"] == pytest.approx(42.3)
    assert profile["top_industry_pct"] == pytest.approx(30.1)
    assert profile["manager_summary"] == "经理A 任职稳定"
    assert profile["source"] == "akshare"
    assert profile["as_of"] == "2026-07-02"
    assert profile["raw_errors"] == '["scale stale"]'


def test_remove_from_watchlist_cleans_fund_profile(session):
    repo.add_to_watchlist(session, "110011")
    repo.upsert_fund_profile(session, "110011", {"scale": 12.5})

    assert repo.remove_from_watchlist(session, "110011") is True

    assert repo.get_fund_profile(session, "110011") is None


def test_count_transactions_for_funds_returns_counts_and_zero_defaults(session):
    repo.add_to_watchlist(session, "110011")
    repo.add_to_watchlist(session, "000001")
    repo.add_transaction(session, "110011", {
        "tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0,
    })
    repo.add_transaction(session, "110011", {
        "tx_date": "2026-02-01", "amount": 500.0, "nav": 1.5,
    })
    repo.add_transaction(session, "000001", {
        "tx_date": "2026-02-01", "amount": 300.0, "nav": 1.0,
    })

    counts = repo.count_transactions_for_funds(session, ["110011", "000001", "999999"])

    assert counts == {"110011": 2, "000001": 1, "999999": 0}


def test_get_latest_navs_for_funds_returns_latest_nav_per_fund(session):
    session.add_all([
        FundNav(fund_code="110011", nav_date="2026-06-01", accumulated_nav=1.1,
                source="akshare", source_updated_at="2026-06-01"),
        FundNav(fund_code="110011", nav_date="2026-06-30", accumulated_nav=1.3,
                source="akshare", source_updated_at="2026-06-30"),
        FundNav(fund_code="000001", nav_date="2026-06-15", accumulated_nav=2.0,
                source="akshare", source_updated_at="2026-06-15"),
    ])
    session.commit()

    latest = repo.get_latest_navs_for_funds(session, ["110011", "000001", "999999"])

    assert latest["110011"]["nav_date"] == "2026-06-30"
    assert latest["110011"]["accumulated_nav"] == pytest.approx(1.3)
    assert latest["000001"]["nav_date"] == "2026-06-15"
    assert "999999" not in latest
