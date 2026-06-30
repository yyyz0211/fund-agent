import pytest
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker
from backend.db import repository as repo


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
