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
