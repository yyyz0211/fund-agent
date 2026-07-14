import pytest
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker
from backend.services.watchlist import watchlist_service as ws


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


def test_list_empty(session):
    assert ws.list_watchlist(session=session) == []


def test_add_and_list(session):
    row = ws.add("110011", note="hold", session=session)
    assert row["fund_code"] == "110011"
    assert len(ws.list_watchlist(session=session)) == 1


def test_remove(session):
    ws.add("110011", session=session)
    assert ws.remove("110011", session=session) == {"fund_code": "110011", "removed": True}
    assert ws.remove("110011", session=session) == {"fund_code": "110011", "removed": False}


def test_update_note_present_and_absent(session):
    ws.add("110011", session=session)
    out = ws.update_note("110011", "watch", session=session)
    assert out["note"] == "watch"
    missing = ws.update_note("999999", "x", session=session)
    assert "error" in missing
