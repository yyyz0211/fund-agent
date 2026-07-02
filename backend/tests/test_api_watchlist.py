import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.app import app
from backend.db import session as db_session
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from backend.db.models import Fund, FundNav, MarketData, Watchlist
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
    repo.add_to_watchlist_full(session, "110011", {
        "note": "hold",
        "is_holding": True,
        "holding_share": 1000.0,
        "cost_nav": 1.0,
    })
    repo.add_to_watchlist(session, "000001", note="watch")
    session.add_all([
        Fund(fund_code="110011", fund_name="易方达优质精选",
             fund_type="QDII", manager="张坤", company="易方达基金"),
        Fund(fund_code="000001", fund_name="华夏成长",
             fund_type="混合型", manager=None, company=None),
        FundNav(fund_code="110011", nav_date="2026-06-30", unit_nav=1.2,
                accumulated_nav=1.2, daily_return=0.02, source="akshare",
                source_updated_at="2026-06-30"),
        FundNav(fund_code="000001", nav_date="2026-06-30", unit_nav=1.0,
                accumulated_nav=1.0, daily_return=-0.01, source="akshare",
                source_updated_at="2026-06-30"),
    ])
    session.commit()

    r = client.get("/api/watchlist")

    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    codes = {row["fund_code"] for row in body}
    assert codes == {"110011", "000001"}
    by_code = {row["fund_code"]: row for row in body}
    assert by_code["110011"]["fund_name"] == "易方达优质精选"
    assert by_code["110011"]["latest_nav"] == pytest.approx(1.2)
    assert by_code["110011"]["daily_return"] == pytest.approx(0.02)
    assert by_code["110011"]["daily_pnl_pct"] == pytest.approx(0.02)
    assert by_code["110011"]["daily_pnl_abs"] == pytest.approx(23.5294)
    assert by_code["000001"]["fund_name"] == "华夏成长"
    assert by_code["000001"]["daily_return"] == pytest.approx(-0.01)
    assert by_code["000001"]["daily_pnl_abs"] is None


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


def test_delete_cascades_fund_and_nav(session):
    """从自选里删一只基金时,同 `fund_code` 的 Fund 基础信息行 +
    FundNav 净值快照都应一起删 —— 否则缓存数据就变成"幽灵数据"。

    把这只基金入自选 + 预先塞 Fund/FundNav 模拟"已经缓存过"的状态,
    然后 DELETE,验证三表联动:

      Watchlist: 1 -> 0 (主路径)
      Fund:      1 -> 0 (级联)
      FundNav:   3 -> 0 (级联)
      MarketData: 1 -> 1 (无关,不动)
    """
    session.add(Watchlist(fund_code="110011"))
    session.add(Fund(fund_code="110011", fund_name="易方达优质精选",
                     fund_type="QDII", manager="张坤", company="易方达基金"))
    session.add_all([
        FundNav(fund_code="110011", nav_date="2026-06-01", unit_nav=5.0,
                accumulated_nav=5.0, daily_return=0.0, source="akshare"),
        FundNav(fund_code="110011", nav_date="2026-06-02", unit_nav=5.1,
                accumulated_nav=5.1, daily_return=0.02, source="akshare"),
        FundNav(fund_code="110011", nav_date="2026-06-03", unit_nav=5.2,
                accumulated_nav=5.2, daily_return=0.0196, source="akshare"),
    ])
    # market_data 用同 fund_code 不会出现(它的 pk 是 symbol+market_date)
    # ——但放一行验证无关表不被误伤
    session.add(MarketData(symbol="000300", market_date="2026-06-30",
                           name="沪深300", close=4000.0, change_pct=0.5))
    session.commit()

    r = client.delete("/api/watchlist/110011")
    assert r.status_code == 200, r.text
    assert r.json() == {"fund_code": "110011", "removed": True}

    from sqlalchemy import select, func
    assert session.scalar(
        select(func.count()).select_from(Watchlist).where(Watchlist.fund_code == "110011")
    ) == 0, "Watchlist 应被删光"
    assert session.get(Fund, "110011") is None, "Fund 基础信息应被级联删"
    assert session.scalar(
        select(func.count()).select_from(FundNav).where(FundNav.fund_code == "110011")
    ) == 0, "FundNav 历史净值应被级联删"
    # 无关表不能动 —— 防止"删自选时把市场数据搞飞"的灾难
    assert session.scalar(select(MarketData).where(MarketData.symbol == "000300")) is not None


def test_delete_cascade_is_idempotent(session):
    """已在 Fund/FundNav 没有缓存的基金,DELETE 走纯原路径不该报错。

    之前实现删 Watchlist 一行就够 —— 这里保证加级联后,空缓存的场景
    跟原来等价(returned True, Watchlist 行被删, 不抛异常)。
    """
    repo.add_to_watchlist(session, "000001")
    r = client.delete("/api/watchlist/000001")
    assert r.status_code == 200
    assert r.json() == {"fund_code": "000001", "removed": True}
