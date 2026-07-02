"""`pnl_service.calculate_pnl` 离线测试。

不联网、不调真实 LLM。直接 in-memory SQLite,写 watchlist + nav,
验证 PnL 计算与 skipped 语义。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import repository as repo
from backend.db.init_db import init_db
from backend.services import pnl_service as psvc


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    yield s
    s.close()


def _seed_holding(s, fund_code, share, cost, fund_name=None, current_nav=None,
                  nav_date="2026-06-30"):
    """把 watchlist + Fund + FundNav 一次性塞满,准备好 PnL 计算。"""
    repo.add_to_watchlist_full(
        s, fund_code,
        {"is_holding": True, "holding_share": share, "cost_nav": cost},
    )
    if fund_name is not None:
        from backend.db.models import Fund
        # add_to_watchlist_full 不写 Fund 表,补一行
        if not s.get(Fund, fund_code):
            s.add(Fund(fund_code=fund_code, fund_name=fund_name))
            s.commit()
    if current_nav is not None:
        from backend.db.models import FundNav
        s.add(FundNav(
            fund_code=fund_code, nav_date=nav_date,
            accumulated_nav=current_nav, source="akshare",
        ))
        s.commit()


class TestSingleFund:
    def test_basic_profit(self, session):
        _seed_holding(session, "110011", share=1000, cost=2.0,
                      fund_name="易方达", current_nav=2.5)
        result = psvc.calculate_pnl(session=session)
        assert result["totals"]["count"] == 1
        assert result["skipped"] == []
        item = result["items"][0]
        assert item["fund_code"] == "110011"
        assert item["fund_name"] == "易方达"
        assert item["current_nav"] == 2.5
        assert item["invested"] == 2000.0          # 1000 * 2.0
        assert item["market_value"] == 2500.0     # 1000 * 2.5
        assert item["pnl_abs"] == 500.0
        assert item["pnl_pct"] == 0.25             # 25%
        assert result["totals"]["pnl_abs"] == 500.0
        assert result["totals"]["pnl_pct"] == 0.25

    def test_loss(self, session):
        _seed_holding(session, "000001", share=500, cost=3.0, current_nav=2.4)
        result = psvc.calculate_pnl(session=session)
        item = result["items"][0]
        assert item["invested"] == 1500.0
        assert item["market_value"] == 1200.0
        assert item["pnl_abs"] == -300.0
        assert item["pnl_pct"] == -0.2             # -20%

    def test_flat_position(self, session):
        """NAV == cost, pnl = 0。"""
        _seed_holding(session, "000003", share=100, cost=1.0, current_nav=1.0)
        result = psvc.calculate_pnl(session=session)
        assert result["items"][0]["pnl_abs"] == 0.0
        assert result["items"][0]["pnl_pct"] == 0.0


class TestMultiFund:
    def test_aggregates_totals(self, session):
        _seed_holding(session, "110011", share=1000, cost=2.0, current_nav=2.5)
        _seed_holding(session, "000001", share=500, cost=3.0, current_nav=2.4)
        result = psvc.calculate_pnl(session=session)
        assert result["totals"]["count"] == 2
        # invested: 2000 + 1500 = 3500; market: 2500 + 1200 = 3700
        assert result["totals"]["invested"] == 3500.0
        assert result["totals"]["market_value"] == 3700.0
        assert result["totals"]["pnl_abs"] == 200.0
        # pnl_pct = 200 / 3500 ≈ 0.057142857...
        assert result["totals"]["pnl_pct"] is not None
        assert abs(result["totals"]["pnl_pct"] - 200 / 3500) < 1e-6

    def test_filters_to_fund_codes_subset(self, session):
        _seed_holding(session, "110011", share=1000, cost=2.0, current_nav=2.5)
        _seed_holding(session, "000001", share=500, cost=3.0, current_nav=2.4)
        result = psvc.calculate_pnl(fund_codes=["110011"], session=session)
        assert result["totals"]["count"] == 1
        assert result["items"][0]["fund_code"] == "110011"

    def test_transaction_count_is_returned_for_each_holding(self, session):
        _seed_holding(session, "110011", share=1000, cost=2.0, current_nav=2.5)
        _seed_holding(session, "000001", share=500, cost=3.0, current_nav=2.4)
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-01-01", "amount": 1000.0, "nav": 2.0,
        })
        repo.add_transaction(session, "110011", {
            "tx_date": "2026-02-01", "amount": 500.0, "nav": 2.5,
        })
        repo.add_transaction(session, "000001", {
            "tx_date": "2026-03-01", "amount": 300.0, "nav": 2.4,
        })

        result = psvc.calculate_pnl(session=session)

        counts = {item["fund_code"]: item["transaction_count"] for item in result["items"]}
        assert counts == {"110011": 2, "000001": 1}

    def test_empty_when_no_holdings(self, session):
        """没有任何 is_holding=true 行时,空 totals + 空 skipped。"""
        result = psvc.calculate_pnl(session=session)
        assert result["items"] == []
        assert result["skipped"] == []
        assert result["totals"]["count"] == 0
        assert result["totals"]["invested"] == 0
        assert result["totals"]["pnl_pct"] is None

    def test_ignores_is_holding_false(self, session):
        """`is_holding=False` 的行根本不进 PnL 计算。"""
        _seed_holding(session, "110011", share=1000, cost=2.0, current_nav=2.5)
        # 加一个 is_holding=False 的行
        repo.add_to_watchlist_full(
            session, "000001",
            {"is_holding": False, "holding_share": 100, "cost_nav": 1.0},
        )
        result = psvc.calculate_pnl(session=session)
        codes = {i["fund_code"] for i in result["items"]}
        assert codes == {"110011"}


class TestSkipped:
    def test_missing_holding_share(self, session):
        repo.add_to_watchlist_full(
            session, "110011",
            {"is_holding": True, "holding_share": None, "cost_nav": 2.0},
        )
        result = psvc.calculate_pnl(session=session)
        assert result["items"] == []
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["fund_code"] == "110011"
        assert "holding_share" in result["skipped"][0]["reason"]

    def test_missing_cost_nav(self, session):
        repo.add_to_watchlist_full(
            session, "110011",
            {"is_holding": True, "holding_share": 1000, "cost_nav": None},
        )
        result = psvc.calculate_pnl(session=session)
        assert len(result["skipped"]) == 1
        assert "cost_nav" in result["skipped"][0]["reason"]

    def test_no_nav_data(self, session):
        """watchlist 行齐了,但 FundNav 缺失 → 跳进 skipped。"""
        repo.add_to_watchlist_full(
            session, "110011",
            {"is_holding": True, "holding_share": 1000, "cost_nav": 2.0},
        )
        result = psvc.calculate_pnl(session=session)
        assert len(result["skipped"]) == 1
        assert "no nav data" in result["skipped"][0]["reason"]

    def test_zero_share_or_cost(self, session):
        """share=0 / cost=0 不应该进 PnL(投资额是 0,百分比无意义)。"""
        repo.add_to_watchlist_full(
            session, "110011",
            {"is_holding": True, "holding_share": 0, "cost_nav": 2.0},
        )
        result = psvc.calculate_pnl(session=session)
        assert result["items"] == []
        assert len(result["skipped"]) == 1
        assert "non-positive" in result["skipped"][0]["reason"]

    def test_skipped_does_not_distort_totals(self, session):
        """一只正常 + 一只 skipped, totals 只算正常那只。"""
        _seed_holding(session, "110011", share=1000, cost=2.0, current_nav=2.5)
        repo.add_to_watchlist_full(
            session, "000001",
            {"is_holding": True, "holding_share": 100, "cost_nav": None},
        )
        result = psvc.calculate_pnl(session=session)
        assert result["totals"]["count"] == 1
        assert result["totals"]["invested"] == 2000.0
        assert len(result["skipped"]) == 1


class TestAsOf:
    def test_as_of_uses_latest_nav_date(self, session):
        _seed_holding(session, "110011", share=1000, cost=2.0, current_nav=2.5,
                      nav_date="2026-06-15")
        _seed_holding(session, "000001", share=500, cost=3.0, current_nav=2.4,
                      nav_date="2026-06-30")
        result = psvc.calculate_pnl(session=session)
        assert result["as_of"] == "2026-06-30"
