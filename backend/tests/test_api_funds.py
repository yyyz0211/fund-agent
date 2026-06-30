import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.db import session as db_session
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy import event, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.services import fund_service as fs

    # fund_service 是 `from backend.db.session import get_session` —— 它
    # 拿到 module attr 的本地绑定。需要在这里 patch service module 自己的
    # `get_session` 名。
from backend.services import data_collector as dc

client = TestClient(app)


@pytest.fixture()
def populated_session(monkeypatch):
    # :memory: SQLite 默认每个 connection 一个内存库；StaticPool 让所有
    # session 共享同一连接，确保 fixture 写入的数据对后续 service 调用可见。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def _get_session():
        return Session()

    # 所有 service 函数 _with_session(None) 默认走 db_session.get_session()
    monkeypatch.setattr(db_session, "get_session", _get_session)
    # 服务层也使用了 fund_service.get_session 这个 module-level 名字
    monkeypatch.setattr(fs, "get_session", _get_session)
    # 测试里手动 refresh 时也用同一个 Session（确保数据写进 :memory:）
    s = Session()

    monkeypatch.setattr(dc, "fetch_fund_info", lambda code: {
        "fund_code": code, "fund_name": "FundA", "fund_type": "混合型",
        "manager": "X", "company": "Y", "source": "akshare", "as_of": "2026-06-30"})
    navs = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.001, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 11)]
    monkeypatch.setattr(dc, "fetch_fund_nav_history", lambda code: navs)

    try:
        yield s
    finally:
        s.close()


def test_get_fund(populated_session):
    fs.refresh_fund("110011", session=populated_session)
    r = client.get("/api/funds/110011")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "110011"
    assert body["fund_name"] == "FundA"
    assert body["source"] == "akshare"


def test_get_fund_404(populated_session):
    r = client.get("/api/funds/999999")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_get_nav(populated_session):
    fs.refresh_fund("110011", session=populated_session)
    r = client.get("/api/funds/110011/nav")
    assert r.status_code == 200
    assert "accumulated_nav" in r.json()


def test_get_nav_history_range(populated_session):
    fs.refresh_fund("110011", session=populated_session)
    r = client.get("/api/funds/110011/nav-history",
                   params={"start": "2026-06-03", "end": "2026-06-05"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert [n["nav_date"] for n in body["navs"]] == \
        ["2026-06-03", "2026-06-04", "2026-06-05"]


def test_get_metrics(populated_session):
    fs.refresh_fund("110011", session=populated_session)
    r = client.get("/api/funds/110011/metrics", params={"period": "1w"})
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "110011"
    assert body["period"] == "1w"
    assert "max_drawdown" in body


def test_get_metrics_illegal_period(populated_session):
    r = client.get("/api/funds/110011/metrics", params={"period": "2y"})
    assert r.status_code == 400


def test_get_metrics_404(populated_session):
    r = client.get("/api/funds/999999/metrics", params={"period": "1w"})
    assert r.status_code == 404
    assert "detail" in r.json()
