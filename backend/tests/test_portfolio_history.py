"""持仓组合每日盈亏时间序列测试。"""
import pytest
from sqlalchemy.orm import sessionmaker

import backend.db.models  # noqa: F401
from backend.db import repository as repo
from backend.db.init_db import init_db
from backend.db.models import Watchlist
from backend.db.session import make_engine


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


def _seed_fund(session, code, nav_rows, tx_rows, *, fund_name=None):
    """给一只基金写入基础信息、NAV 历史、买入交易,并标记为持仓。"""
    repo.upsert_fund(session, {"fund_code": code, "fund_name": fund_name or f"Fund {code}"})
    if nav_rows:
        repo.upsert_navs(session, code, nav_rows)
    session.add(Watchlist(fund_code=code, is_holding=True))
    session.commit()
    for tx in tx_rows:
        repo.add_transaction(session, code, tx, commit=False)
    session.commit()


def _nav(nav_date, acc):
    return {
        "nav_date": nav_date,
        "unit_nav": acc,
        "accumulated_nav": acc,
        "daily_return": None,
        "source": "akshare",
        "source_updated_at": nav_date,
    }


def test_calculate_pnl_series_one_buy(session):
    from backend.services import portfolio_history as ph

    _seed_fund(
        session, "110011",
        [_nav("2026-01-01", 1.0), _nav("2026-01-02", 1.1)],
        [{"tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0, "kind": "buy"}],
    )

    out = ph.calculate_pnl_series(
        fund_codes=["110011"], start="2026-01-01", end="2026-01-02", session=session,
    )
    assert out["dates"][0]["invested"] == 1000.0
    assert out["dates"][0]["market_value"] == 1000.0
    assert out["dates"][0]["pnl"] == 0.0
    assert out["dates"][1]["market_value"] == 1100.0
    assert out["dates"][1]["pnl"] == 100.0
    assert out["summary"]["invested"] == 1000.0
    assert out["summary"]["market_value"] == 1100.0
    assert out["summary"]["pnl_abs"] == 100.0


def test_calculate_pnl_series_forward_fills_nav(session):
    from backend.services import portfolio_history as ph

    # 1/1 有 NAV,1/2 缺失 → 1/2 市值前向填充 1/1 的 NAV,不算缺失。
    _seed_fund(
        session, "110011",
        [_nav("2026-01-01", 1.0)],
        [{"tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0, "kind": "buy"}],
    )

    out = ph.calculate_pnl_series(
        fund_codes=["110011"], start="2026-01-01", end="2026-01-02", session=session,
    )
    assert out["dates"][1]["market_value"] == 1000.0
    assert out["dates"][1]["missing_funds"] == []


def test_calculate_pnl_series_multi_fund_totals(session):
    from backend.services import portfolio_history as ph

    _seed_fund(
        session, "110011",
        [_nav("2026-01-01", 1.0), _nav("2026-01-02", 1.2)],
        [{"tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0, "kind": "buy"}],
    )
    _seed_fund(
        session, "000001",
        [_nav("2026-01-01", 2.0), _nav("2026-01-02", 2.0)],
        [{"tx_date": "2026-01-02", "amount": 2000.0, "nav": 2.0, "kind": "buy"}],
    )

    out = ph.calculate_pnl_series(
        fund_codes=None, start="2026-01-01", end="2026-01-02", session=session,
    )
    # 1/1 仅 110011 买入 1000。
    assert out["dates"][0]["invested"] == 1000.0
    # 1/2 两只都买入:1000 + 2000 = 3000。
    assert out["dates"][1]["invested"] == 3000.0
    # 1/2 市值:110011 = 1000 份 * 1.2 = 1200;000001 = 1000 份 * 2.0 = 2000。
    assert out["dates"][1]["market_value"] == 3200.0


def test_calculate_pnl_series_excludes_fund_with_no_nav_at_all(session):
    from backend.services import portfolio_history as ph

    _seed_fund(
        session, "110011", [],
        [{"tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0, "kind": "buy"}],
    )
    out = ph.calculate_pnl_series(
        fund_codes=["110011"], start="2026-01-01", end="2026-01-02", session=session,
    )
    assert out["dates"] == []
    assert "110011" in out["uncovered_funds"]


def test_calculate_pnl_series_empty_watchlist(session):
    from backend.services import portfolio_history as ph

    out = ph.calculate_pnl_series(
        fund_codes=None, start="2026-01-01", end="2026-01-02", session=session,
    )
    assert out["dates"] == []
    assert out["summary"] == {
        "invested": 0.0, "market_value": 0.0, "pnl_abs": 0.0, "pnl_pct": 0.0,
        "daily_points": 0,
    }


def test_calculate_pnl_series_pct_zero_not_none(session):
    from backend.services import portfolio_history as ph

    # 投入为 0(无买入)但有 NAV 的关注基金不进 dates(has_position=False)。
    # 这里验证 summary 的 pnl_pct 恒为 0.0 而非 None。
    out = ph.calculate_pnl_series(
        fund_codes=None, start="2026-01-01", end="2026-01-02", session=session,
    )
    assert out["summary"]["pnl_pct"] == 0.0


def test_calculate_pnl_series_skips_days_before_first_buy(session):
    from backend.services import portfolio_history as ph

    _seed_fund(
        session, "110011",
        [_nav("2026-01-01", 1.0), _nav("2026-01-02", 1.0), _nav("2026-01-03", 1.1)],
        [{"tx_date": "2026-01-02", "amount": 1000.0, "nav": 1.0, "kind": "buy"}],
    )
    out = ph.calculate_pnl_series(
        fund_codes=["110011"], start="2026-01-01", end="2026-01-03", session=session,
    )
    # 1/1 还没买入 → 不产生数据点;第一个点应是 1/2。
    assert out["dates"][0]["date"] == "2026-01-02"
    assert len(out["dates"]) == 2
