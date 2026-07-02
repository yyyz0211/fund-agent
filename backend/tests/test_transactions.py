"""`transaction_service.recalc_holding` + watchlist transaction API 离线测试。

不联网。in-memory SQLite,验证:
- 加权平均成本公式
- 老数据兼容(已有 holding_share/cost_nav 的行,第一次加仓会正确合并)
- list/add/delete API 行为
- GET /api/watchlist 端点附带 transaction_count
"""
import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.app import app
from backend.api.routes import watchlist as watchlist_routes
from backend.db import repository as repo
from backend.db import session as db_session
from backend.db.init_db import init_db
from backend.db.models import FundTransaction, Watchlist
from backend.services import transaction_service as ts
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

    monkeypatch.setattr(db_session, "get_session", _get_session)
    monkeypatch.setattr(ws, "get_session", _get_session)
    monkeypatch.setattr(ts, "get_session", _get_session)
    monkeypatch.setattr(
        watchlist_routes,
        "preload_jobs",
        SimpleNamespace(start_preload_job=lambda fund_code: None),
        raising=False,
    )
    yield s
    s.close()


# --------------------------------------------------------------------------- #
#  recalc_holding 单测                                                         #
# --------------------------------------------------------------------------- #


class TestRecalcEmpty:
    def test_no_transactions_leaves_watchlist_alone(self, session):
        """没有任何交易时,recalc 不改 holding/cost,只把 basis 标 legacy。"""
        repo.add_to_watchlist_full(
            session, "110011",
            {"is_holding": True, "holding_share": 1000, "cost_nav": 1.5},
        )
        result = ts.recalc_holding("110011", session=session)
        assert result is not None
        assert result["holding_share"] == 1000
        assert result["cost_nav"] == 1.5
        assert result["cost_nav_basis"] == "legacy"

    def test_fund_not_in_watchlist_returns_none(self, session):
        assert ts.recalc_holding("999999", session=session) is None


class TestRecalcSingleBuy:
    def test_single_buy_overrides_initial_holding(self, session):
        """老数据里已有 holding,新增第一笔 buy,recalc 用现有 holding 当种子 + 该笔合并。"""
        repo.add_to_watchlist_full(
            session, "110011",
            {"is_holding": True, "holding_share": 1000, "cost_nav": 1.5},
        )
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-03-01",
            "amount": 500.0,
            "nav": 2.0,
        })
        result = ts.recalc_holding("110011", session=session)
        # seed 1000 @ 1.5 = 1500; + buy 500 @ 2.0 = 2000; share = 1000 + 250 = 1250
        # cost = (1500 + 500) / 1250 = 1.6
        assert result["holding_share"] == pytest.approx(1250.0)
        assert result["cost_nav"] == pytest.approx(1.6)
        assert result["cost_nav_basis"] == "transactions"

    def test_single_buy_without_seed_starts_from_zero(self, session):
        """Watchlist 没有 holding 时,从第一笔 buy 开始建仓。"""
        repo.add_to_watchlist(session, "110011")
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-03-01",
            "amount": 1000.0,
            "nav": 2.0,
        })
        result = ts.recalc_holding("110011", session=session)
        assert result["holding_share"] == pytest.approx(500.0)
        assert result["cost_nav"] == pytest.approx(2.0)
        # buy_date 自动从最早一笔交易抄过来
        assert result["buy_date"] == "2026-03-01"


class TestRecalcMultiBuy:
    def test_weighted_average_two_buys(self, session):
        """两笔买入加权平均:第一笔 1000@1.0 = 1000;第二笔 2000@2.0 = 2000;
        share = 1000 + 1000 = 2000; cost = 3000 / 2000 = 1.5。"""
        repo.add_to_watchlist(session, "110011")
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0,
        })
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-06-01", "amount": 2000.0, "nav": 2.0,
        })
        result = ts.recalc_holding("110011", session=session)
        assert result["holding_share"] == pytest.approx(2000.0)
        assert result["cost_nav"] == pytest.approx(1.5)

    def test_three_buys_sequential_average(self, session):
        """三笔累加(预期):
        1: 1000 / 1.0 = 1000 share @ 1.0 cost
        2: +2000 / 2.0 = 1000 share @ (1000*1.0 + 2000)/2000 = 1.5
        3: +3000 / 3.0 = 1000 share @ (2000*1.5 + 3000)/3000 = 2.0
        最终 share=3000, cost=2.0
        """
        repo.add_to_watchlist(session, "110011")
        for d, amt, n in [
            ("2026-01-01", 1000.0, 1.0),
            ("2026-02-01", 2000.0, 2.0),
            ("2026-03-01", 3000.0, 3.0),
        ]:
            repo.add_transaction(session, "110011", {
                "tx_date": d, "amount": amt, "nav": n,
            })
        result = ts.recalc_holding("110011", session=session)
        assert result["holding_share"] == pytest.approx(3000.0)
        assert result["cost_nav"] == pytest.approx(2.0)


class TestRecalcDelete:
    def test_delete_last_buy_resets_to_null(self, session):
        """删掉最后一笔 buy 后,recalc 没有种子可推,应当把 holding 清掉。

        为什么不还原到 seed 1000@1.5:
        - 第一次 recalc 之后 Watchlist.holding_share/cost_nav 已经被
          覆盖成 1250@1.6;原始 seed 已经不存在了。
        - 用户删除"所有"加仓的意图是"我还没真正建仓",所以清成
          None 比还原到一个无法解释的"上次合并值"更可预测。
        - None 也让 pnl_service.calculate_pnl 自动 skip(见
          `test_missing_holding_share`)。
        """
        repo.add_to_watchlist_full(
            session, "110011",
            {"is_holding": True, "holding_share": 1000, "cost_nav": 1.5},
        )
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-03-01", "amount": 500.0, "nav": 2.0,
        })
        # 第一次 recalc 合并 → 1250 / 1.6
        ts.recalc_holding("110011", session=session)
        txs = repo.list_transactions(session, "110011")
        repo.delete_transaction(session, txs[0]["id"])
        # 删完后已经没有交易 → 应当清空 holding,让 PnL skip
        ts.recalc_holding("110011", session=session)
        result = repo.get_watchlist_row(session, "110011")
        assert result["holding_share"] is None
        assert result["cost_nav"] is None


# --------------------------------------------------------------------------- #
#  API 端点测试                                                                #
# --------------------------------------------------------------------------- #


class TestListEndpoint:
    def test_list_includes_transaction_count(self, session):
        repo.add_to_watchlist_full(session, "110011", {"is_holding": True})
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0,
        })
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-02-01", "amount": 500.0, "nav": 1.5,
        })
        repo.add_to_watchlist(session, "000001")
        r = client.get("/api/watchlist")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        by_code = {row["fund_code"]: row for row in body}
        assert by_code["110011"]["transaction_count"] == 2
        assert by_code["000001"]["transaction_count"] == 0


class TestInitialHoldingApi:
    def test_initial_holding_creates_watchlist_transaction_and_recalc(self, session):
        r = client.post("/api/watchlist/110011/initial-holding", json={
            "tx_date": "2026-03-01",
            "amount": 1000.0,
            "nav": 2.0,
            "fee": 1.0,
            "note": "first buy",
            "is_focus": True,
            "watchlist_note": "core fund",
        })

        assert r.status_code == 200, r.text
        body = r.json()
        tx = body["transaction"]
        assert tx["amount"] == pytest.approx(1000.0)
        assert tx["nav"] == pytest.approx(2.0)
        assert tx["share"] == pytest.approx(500.0)
        assert tx["fee"] == pytest.approx(1.0)
        assert tx["note"] == "first buy"

        wl = body["watchlist"]
        assert wl["fund_code"] == "110011"
        assert wl["is_holding"] is True
        assert wl["is_focus"] is True
        assert wl["note"] == "core fund"
        assert wl["holding_share"] == pytest.approx(500.0)
        assert wl["cost_nav"] == pytest.approx(2.0)
        assert wl["holding_amount"] == pytest.approx(1000.0)
        assert wl["buy_date"] == "2026-03-01"
        assert wl["cost_nav_basis"] == "transactions"
        assert repo.count_transactions(session, "110011") == 1

    def test_initial_holding_converts_existing_watchlist_without_duplicate_row(self, session):
        repo.add_to_watchlist_full(session, "110011", {
            "is_focus": True,
            "note": "old note",
        })

        r = client.post("/api/watchlist/110011/initial-holding", json={
            "tx_date": "2026-04-01",
            "amount": 1200.0,
            "nav": 3.0,
            "is_focus": False,
            "watchlist_note": "converted",
        })

        assert r.status_code == 200, r.text
        assert session.scalar(
            select(func.count()).select_from(Watchlist)
        ) == 1
        wl = r.json()["watchlist"]
        assert wl["is_holding"] is True
        assert wl["is_focus"] is False
        assert wl["note"] == "converted"
        assert wl["holding_share"] == pytest.approx(400.0)
        assert wl["cost_nav"] == pytest.approx(3.0)
        assert repo.count_transactions(session, "110011") == 1

    def test_initial_holding_starts_preload_after_success(self, session, monkeypatch):
        calls = []

        def _fake_start(fund_code):
            calls.append(fund_code)
            return {"job_id": "job-110011", "fund_code": fund_code, "status": "pending"}

        monkeypatch.setattr(
            watchlist_routes,
            "preload_jobs",
            SimpleNamespace(start_preload_job=_fake_start),
            raising=False,
        )

        r = client.post("/api/watchlist/110011/initial-holding", json={
            "tx_date": "2026-04-01",
            "amount": 1200.0,
            "nav": 3.0,
        })

        assert r.status_code == 200, r.text
        assert r.json()["preload_job"] == {
            "job_id": "job-110011",
            "fund_code": "110011",
            "status": "pending",
        }
        assert r.json()["watchlist"]["preload_status"] == "pending"
        assert calls == ["110011"]

    def test_initial_holding_rolls_back_when_recalc_fails(self, session, monkeypatch):
        def _fail_recalc(*args, **kwargs):
            raise RuntimeError("recalc failed")

        monkeypatch.setattr(ws, "_recalc", _fail_recalc)

        with pytest.raises(RuntimeError, match="recalc failed"):
            ws.set_initial_holding("110011", {
                "tx_date": "2026-05-01",
                "amount": 1000.0,
                "nav": 2.0,
            }, session=session)

        assert session.scalar(
            select(func.count())
            .select_from(Watchlist)
            .where(Watchlist.fund_code == "110011")
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(FundTransaction)
            .where(FundTransaction.fund_code == "110011")
        ) == 0

    def test_initial_holding_rejects_unsupported_kind_without_writes(self, session):
        r = client.post("/api/watchlist/110011/initial-holding", json={
            "tx_date": "2026-03-01",
            "amount": 1000.0,
            "nav": 2.0,
            "kind": "sell",
        })

        assert r.status_code == 422
        assert session.scalar(select(func.count()).select_from(Watchlist)) == 0
        assert session.scalar(select(func.count()).select_from(FundTransaction)) == 0

    def test_initial_holding_409s_when_fund_already_has_transactions(self, session):
        """已有交易历史的基金不能再走 initial-holding;要追加请用 /transactions。"""
        repo.add_to_watchlist_full(session, "110011", {"is_holding": True})
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-01-01",
            "amount": 500.0,
            "nav": 2.0,
        })
        # 模拟前端"先点 is_holding=false 提交 → 再点 is_holding=true 提交"时
        # row 已有 transaction_count=1 但前端 needsInitialHolding 仍命中。
        r = client.post("/api/watchlist/110011/initial-holding", json={
            "tx_date": "2026-02-01",
            "amount": 800.0,
            "nav": 2.5,
        })

        assert r.status_code == 409, r.text
        assert "transactions" in r.json()["detail"].lower()
        # 老交易不被破坏
        assert repo.count_transactions(session, "110011") == 1


class TestTransactionApi:
    def test_get_transactions_empty(self, session):
        repo.add_to_watchlist(session, "110011")
        r = client.get("/api/watchlist/110011/transactions")
        assert r.status_code == 200
        assert r.json() == []

    def test_post_transaction_recalcs_watchlist(self, session):
        repo.add_to_watchlist(session, "110011")
        r = client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026-03-01", "amount": 1000.0, "nav": 2.0,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["transaction"]["amount"] == 1000.0
        assert body["transaction"]["share"] == pytest.approx(500.0)
        # recalc 后 watchlist 应有 share=500, cost=2.0, basis=transactions
        wl = body["watchlist"]
        assert wl["holding_share"] == pytest.approx(500.0)
        assert wl["cost_nav"] == pytest.approx(2.0)
        assert wl["cost_nav_basis"] == "transactions"
        assert wl["holding_amount"] == pytest.approx(1000.0)

    def test_post_rejects_zero_amount_or_nav(self, session):
        repo.add_to_watchlist(session, "110011")
        r = client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026-03-01", "amount": 0, "nav": 2.0,
        })
        assert r.status_code == 422  # Pydantic 校验
        r = client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026-03-01", "amount": 1000.0, "nav": 0,
        })
        assert r.status_code == 422

    def test_post_rejects_bad_date(self, session):
        repo.add_to_watchlist(session, "110011")
        r = client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026/03/01", "amount": 1000.0, "nav": 2.0,
        })
        assert r.status_code == 422

    def test_post_404_when_fund_not_in_watchlist(self, session):
        r = client.post("/api/watchlist/999999/transactions", json={
            "tx_date": "2026-03-01", "amount": 1000.0, "nav": 2.0,
        })
        assert r.status_code == 404
        assert session.scalar(
            select(func.count()).select_from(FundTransaction)
        ) == 0

    def test_post_rejects_unsupported_kind(self, session):
        repo.add_to_watchlist(session, "110011")
        r = client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026-03-01",
            "amount": 1000.0,
            "nav": 2.0,
            "kind": "sell",
        })
        assert r.status_code == 422
        assert repo.list_transactions(session, "110011") == []

    def test_delete_transaction_recalcs(self, session):
        repo.add_to_watchlist(session, "110011")
        # 加两笔
        client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0,
        })
        r2 = client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026-06-01", "amount": 2000.0, "nav": 2.0,
        })
        tx_id = r2.json()["transaction"]["id"]
        # 删第二笔
        r = client.delete(f"/api/watchlist/110011/transactions/{tx_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["removed"] is True
        # 删完只剩第一笔: share=1000, cost=1.0
        assert body["watchlist"]["holding_share"] == pytest.approx(1000.0)
        assert body["watchlist"]["cost_nav"] == pytest.approx(1.0)

    def test_delete_404_when_absent(self, session):
        r = client.delete("/api/watchlist/110011/transactions/99999")
        assert r.status_code == 404

    def test_delete_rejects_wrong_fund_without_deleting(self, session):
        repo.add_to_watchlist(session, "110011")
        repo.add_to_watchlist(session, "000001")
        r = client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0,
        })
        tx_id = r.json()["transaction"]["id"]

        wrong = client.delete(f"/api/watchlist/000001/transactions/{tx_id}")

        assert wrong.status_code == 400
        assert session.get(FundTransaction, tx_id) is not None

    def test_delete_watchlist_removes_transactions(self, session):
        repo.add_to_watchlist(session, "110011")
        client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0,
        })

        r = client.delete("/api/watchlist/110011")

        assert r.status_code == 200
        assert session.scalar(
            select(func.count())
            .select_from(FundTransaction)
            .where(FundTransaction.fund_code == "110011")
        ) == 0

    def test_get_transactions_returns_in_order(self, session):
        repo.add_to_watchlist(session, "110011")
        for d, amt in [("2026-03-01", 1000.0), ("2026-01-01", 500.0)]:
            client.post("/api/watchlist/110011/transactions", json={
                "tx_date": d, "amount": amt, "nav": 2.0,
            })
        r = client.get("/api/watchlist/110011/transactions")
        assert r.status_code == 200
        dates = [t["tx_date"] for t in r.json()]
        # 应按日期升序
        assert dates == sorted(dates)


# --------------------------------------------------------------------------- #
#  PnL 兼容性回归(确保 recalc 后的 holding 仍然能被 PnL 服务消化)             #
# --------------------------------------------------------------------------- #


class TestPnlCompatibility:
    def test_recalc_watchlist_still_feeds_pnl(self, session):
        """recalc → holding 写入 → PnL 服务直接读出结果,无 schema 冲突。"""
        from backend.db.models import Fund, FundNav
        from backend.services import pnl_service as psvc

        repo.add_to_watchlist_full(
            session, "110011", {"is_holding": True},
        )
        client.post("/api/watchlist/110011/transactions", json={
            "tx_date": "2026-01-01", "amount": 1000.0, "nav": 2.0,
        })
        # 灌一行最新 NAV
        if not session.get(Fund, "110011"):
            session.add(Fund(fund_code="110011", fund_name="易方达"))
            session.commit()
        session.add(FundNav(
            fund_code="110011", nav_date="2026-06-30",
            accumulated_nav=2.5, source="akshare",
        ))
        session.commit()

        result = psvc.calculate_pnl(session=session)
        assert result["totals"]["count"] == 1
        item = result["items"][0]
        # share=500, cost=2.0 → invested=1000, market=500*2.5=1250, pnl=250
        assert item["invested"] == pytest.approx(1000.0)
        assert item["market_value"] == pytest.approx(1250.0)
        assert item["pnl_abs"] == pytest.approx(250.0)
