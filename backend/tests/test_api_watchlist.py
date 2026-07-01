import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.app import app
from backend.db import session as db_session
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from backend.db import repository as repo
from backend.services import watchlist_service as ws

client = TestClient(app)


@pytest.fixture()
def session(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()

    def _get_session():
        return Session()

    # watchlist_service 已经在 import 时把 get_session 名字绑定到 module-level
    monkeypatch.setattr(db_session, "get_session", _get_session)
    monkeypatch.setattr(ws, "get_session", _get_session)

    yield s
    s.close()


def test_watchlist_empty(session):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json() == []


def test_watchlist_with_rows(session):
    repo.add_to_watchlist(session, "110011", note="hold")
    repo.add_to_watchlist(session, "000001", note="watch")
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    codes = {row["fund_code"] for row in body}
    assert codes == {"110011", "000001"}


def test_post_adds_row_with_full_attrs(session):
    payload = {
        "fund_code": "110011",
        "note": "long term",
        "is_holding": True,
        "is_focus": False,
        "holding_amount": 12000.5,
        "holding_share": 1000.0,
        "cost_nav": 1.234,
        "buy_date": "2026-01-15",
    }
    r = client.post("/api/watchlist", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "110011"
    assert body["is_holding"] is True
    assert body["holding_amount"] == 12000.5
    assert body["buy_date"] == "2026-01-15"
    assert body["note"] == "long term"


def test_post_is_idempotent_and_does_not_overwrite(session):
    repo.add_to_watchlist(session, "110011", note="original")
    r = client.post("/api/watchlist", json={"fund_code": "110011", "note": "new"})
    assert r.status_code == 200
    assert r.json()["note"] == "original"  # 幂等,不覆盖


def test_patch_updates_only_supplied_fields(session):
    repo.add_to_watchlist(session, "110011", note="note-1")
    repo.add_to_watchlist(session, "110011")  # idempotent noop
    r = client.patch(
        "/api/watchlist/110011",
        json={"holding_amount": 5000.0, "cost_nav": 1.05, "is_holding": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["holding_amount"] == 5000.0
    assert body["cost_nav"] == 1.05
    assert body["is_holding"] is True
    assert body["note"] == "note-1"  # 未传字段保持原值


def test_patch_404_when_absent(session):
    r = client.patch("/api/watchlist/999999", json={"note": "x"})
    assert r.status_code == 404


def test_patch_rejects_bad_date(session):
    repo.add_to_watchlist(session, "110011")
    r = client.patch("/api/watchlist/110011", json={"buy_date": "2026/01/15"})
    assert r.status_code == 422


def test_delete_removes_row(session):
    repo.add_to_watchlist(session, "110011")
    r = client.delete("/api/watchlist/110011")
    assert r.status_code == 200
    assert r.json() == {"fund_code": "110011", "removed": True}
    listing = client.get("/api/watchlist").json()
    assert listing == []


def test_delete_404_when_absent(session):
    r = client.delete("/api/watchlist/999999")
    assert r.status_code == 404
