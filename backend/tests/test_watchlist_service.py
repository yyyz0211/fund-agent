import pytest
from backend.services.watchlist import watchlist_service as ws


pytestmark = pytest.mark.db


@pytest.fixture()
def session(db_session):
    return db_session


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
