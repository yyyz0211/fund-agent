"""metric_service tests."""
from __future__ import annotations

import pytest

from backend.services import metric_service


def test_period_return_supports_1d():
    """Regression: 1d = 1 个交易日窗口。
    之前 _PERIOD_RODS 没有 1d 导致 fund_service.get_metrics("1d") 抛 ValueError,
    briefing table 拿不到 "1d", 最终 LLM 只能写"近1日收益率数据缺失"。
    修复: 1d = 1, 与 1w/1m 共用同一算法 (window[-1] / window[-2] - 1)。
    """
    navs = [1.00, 1.01, 1.02, 1.03]  # 4 个点
    # 1d: 用最后 2 个点, window = [1.02, 1.03] -> 1.03/1.02 - 1
    ret = metric_service.period_return(navs, "1d")
    assert ret is not None
    assert ret == pytest.approx(1.03 / 1.02 - 1)


def test_period_return_1d_needs_two_points():
    """1d 至少需要 2 个点 (今天 + 昨天), 1 个点时返回 None。"""
    navs = [1.0]
    assert metric_service.period_return(navs, "1d") is None


def test_period_return_1w_unchanged():
    """1w 行为没被 1d 改动污染: 仍是 5 个交易日窗口,需要 6 个点。"""
    navs = [1.00, 1.01, 1.02, 1.03, 1.04, 1.05]
    ret = metric_service.period_return(navs, "1w")
    # window = navs[-6:] = [1.00, 1.01, 1.02, 1.03, 1.04, 1.05], ret = 1.05/1.00 - 1
    assert ret == pytest.approx(1.05 / 1.00 - 1)