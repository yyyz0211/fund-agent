"""what_if_service 历史回测服务测试。

测试 4 个核心场景:
1. 单基金维持原持仓 → 用起始日 + 截止日窗口里的 NAV 计算累计收益 / 最大回撤
2. 多基金组合:输入权重,组合 NAV = sum(weight_i × nav_i),累计收益 / 最大回撤
3. 窗口里有 fund 缺数据 → 不报错,但 `missing_funds` 列出,组合按可用 fund 重新归一化权重
4. 任意 fund 全窗口无 NAV → 报 `error: no nav data`,不抛异常

回测本身只依赖本地 NAV 表 + 窗口日期 + 权重,不联网、不调 LLM。
"""
import pytest

import backend.db.models  # noqa: F401  (ensure ORM mapping registered)
from backend.db import repository as repo
from backend.services.fund import what_if_service as wsvc

pytestmark = pytest.mark.db

@pytest.fixture()
def session(db_session):
    return db_session


# ─── 测试 fixtures ─────────────────────────────────────────────────────────────

def _seed(session, *, fund_code: str, nav_rows: list[tuple[str, float]]):
    """插入 FundNav 行 + 必要的 Fund 行(避免外键)。"""
    from backend.db import repository as repo
    repo.upsert_fund(session, {"fund_code": fund_code, "fund_name": f"Fund {fund_code}"})
    repo.upsert_navs(session, fund_code, [
        {"nav_date": d, "accumulated_nav": nv}
        for d, nv in nav_rows
    ])
    session.commit()


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestSingleFundBacktest:
    """单基金维持原持仓。"""

    def test_single_fund_window_return_and_drawdown(self, session):
        _seed(session, fund_code="110011", nav_rows=[
            ("2026-01-01", 1.00),
            ("2026-01-02", 1.01),
            ("2026-01-03", 1.02),
            ("2026-01-04", 0.99),
            ("2026-01-05", 1.03),
        ])
        result = wsvc.backtest(
            session,
            start_date="2026-01-01",
            end_date="2026-01-05",
            holdings={"110011": 1.0},
        )
        # 单 fund 100% 权重 → 累计 = 1.03/1.00 - 1 = 3%
        assert result["error"] is None
        assert result["portfolio_return"] == pytest.approx(0.03, abs=1e-6)
        # 最大回撤:1.02 → 0.99 → 0.99/1.02 - 1 = -2.94%
        # (回撤以"局部最高点"为基准,不是"窗口全局最高 1.03")
        assert result["portfolio_max_drawdown"] == pytest.approx(-0.0294, abs=1e-3)
        assert result["funds"]["110011"]["weight"] == 1.0
        assert result["funds"]["110011"]["fund_return"] == pytest.approx(0.03, abs=1e-6)


class TestMultiFundPortfolio:
    """多基金按权重组合。"""

    def test_two_funds_with_weights(self, session):
        _seed(session, fund_code="A", nav_rows=[
            ("2026-01-01", 1.00),
            ("2026-01-02", 1.05),  # A +5%
        ])
        _seed(session, fund_code="B", nav_rows=[
            ("2026-01-01", 1.00),
            ("2026-01-02", 0.95),  # B -5%
        ])
        result = wsvc.backtest(
            session,
            start_date="2026-01-01",
            end_date="2026-01-02",
            holdings={"A": 0.5, "B": 0.5},
        )
        # 组合 NAV 起点 = 1.00,终点 = 0.5*1.05 + 0.5*0.95 = 1.00 → 收益 0
        assert result["error"] is None
        assert result["portfolio_return"] == pytest.approx(0.0, abs=1e-6)
        assert "A" in result["funds"] and "B" in result["funds"]


class TestMissingData:
    """窗口里 fund 缺数据 / 全窗口无数据。"""

    def test_partial_missing_forward_fills_then_computes(self, session):
        """fund B 在窗口里只有 1 天有数据 → 前向填充后照常算组合 NAV。

        设计取舍:partial-missing 不是 error,前向填充已经够稳健。
        "全窗口无数据"的 fund 才会进 missing_funds(见下一个测试)。
        """
        _seed(session, fund_code="A", nav_rows=[
            ("2026-01-01", 1.00),
            ("2026-01-02", 1.10),
        ])
        _seed(session, fund_code="B", nav_rows=[
            ("2026-01-01", 1.00),
            # 2026-01-02 缺 — 前向填充为 1.00
        ])
        result = wsvc.backtest(
            session,
            start_date="2026-01-01",
            end_date="2026-01-02",
            holdings={"A": 0.5, "B": 0.5},
        )
        assert result["error"] is None
        # B 在 2026-01-01 有 1.00,前向填充为 1.00,所以 B 收益 = 0
        # 组合 = 0.5*1.10 + 0.5*1.00 = 1.05,起点 = 1.00,收益 = 5%
        assert result["portfolio_return"] == pytest.approx(0.05, abs=1e-6)
        # B 不算 missing(因为它至少有 1 个 NAV 行)
        assert "B" not in result["missing_funds"]

    def test_fund_completely_outside_window_goes_to_missing(self, session):
        """fund 在窗口内完全没有 NAV 行 → 进 missing_funds,组合按可用 fund 归一化。"""
        _seed(session, fund_code="A", nav_rows=[
            ("2026-01-01", 1.00),
            ("2026-01-02", 1.10),
        ])
        _seed(session, fund_code="B", nav_rows=[
            # B 的 NAV 都在窗口外
            ("2025-12-31", 1.00),
        ])
        result = wsvc.backtest(
            session,
            start_date="2026-01-01",
            end_date="2026-01-02",
            holdings={"A": 0.5, "B": 0.5},
        )
        assert result["error"] is None
        assert "B" in result["missing_funds"]
        # B 被丢掉,A 归一化到 1.0,组合收益 = A 的 +10%
        assert result["portfolio_return"] == pytest.approx(0.10, abs=1e-6)

    def test_no_nav_at_all_returns_error_dict(self, session):
        """fund 完全无 NAV → 不抛异常,返回 error dict。"""
        # 不 seed,直接调
        result = wsvc.backtest(
            session,
            start_date="2026-01-01",
            end_date="2026-01-02",
            holdings={"X": 1.0},
        )
        assert result["error"] is not None
        assert "no nav" in result["error"].lower() or "missing" in result["error"].lower()


class TestEdgeCases:
    """边界。"""

    def test_zero_window(self, session):
        """start_date == end_date → 收益 0,回撤 0。"""
        _seed(session, fund_code="A", nav_rows=[
            ("2026-01-01", 1.00),
        ])
        result = wsvc.backtest(
            session,
            start_date="2026-01-01",
            end_date="2026-01-01",
            holdings={"A": 1.0},
        )
        assert result["error"] is None
        assert result["portfolio_return"] == 0.0
        assert result["portfolio_max_drawdown"] == 0.0

    def test_weights_dont_sum_to_one_normalizes(self, session):
        """权重和不为 1(比如 0.3 + 0.3)→ 内部归一化,不让结果爆炸。"""
        _seed(session, fund_code="A", nav_rows=[
            ("2026-01-01", 1.00),
            ("2026-01-02", 1.20),
        ])
        result = wsvc.backtest(
            session,
            start_date="2026-01-01",
            end_date="2026-01-02",
            holdings={"A": 0.3, "B": 0.3},  # B 没数据,会被丢掉
        )
        assert result["error"] is None
        # B 被丢掉,A 归一化到 1.0,组合 = +20%
        assert result["portfolio_return"] == pytest.approx(0.20, abs=1e-6)

    def test_includes_disclaimer_field(self, session):
        """结果必须带 disclaimer 字段,LLM 引用以满足"非建议"边界。"""
        _seed(session, fund_code="A", nav_rows=[
            ("2026-01-01", 1.00),
            ("2026-01-02", 1.05),
        ])
        result = wsvc.backtest(
            session,
            start_date="2026-01-01",
            end_date="2026-01-02",
            holdings={"A": 1.0},
        )
        assert "disclaimer" in result
        assert "历史" in result["disclaimer"] or "回测" in result["disclaimer"]
        assert "不构成" in result["disclaimer"] or "不预测" in result["disclaimer"]

    def test_returns_source_and_as_of(self, session):
        """结果带 source + as_of,LLM 必须引用。"""
        _seed(session, fund_code="A", nav_rows=[
            ("2026-01-01", 1.00),
            ("2026-01-02", 1.05),
        ])
        result = wsvc.backtest(
            session,
            start_date="2026-01-01",
            end_date="2026-01-02",
            holdings={"A": 1.0},
        )
        assert result["source"] == "akshare"
        assert result["as_of"] == "2026-01-02"
        assert result["window"]["start"] == "2026-01-01"
        assert result["window"]["end"] == "2026-01-02"
