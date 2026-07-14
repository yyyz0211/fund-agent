"""What-if 历史回测服务。

定位:
- 让 LLM 在用户做"决策假设"提问时(比如"如果我之前减仓 X 加仓 Y 会怎样")
  能调到**真实历史回测**结果,而不是编数字。
- 严格只读本地 NAV 表,不联网、不调 LLM、不预测未来。
- 返回 dict 里**强制**带 disclaimer 字段 —— 调用方必须在回答里引用,
  把"假设性分析"和"未来建议"在 UI 上区分开。

边界:
- 权重和不必为 1;内部按"窗口最后一天有 NAV 的 fund"重新归一化。
- 窗口里某 fund 缺数据 → 不报错,放进 `missing_funds`,按可用 fund 归一化。
- 所有 fund 都缺数据 → 返回 error dict,LLM 提示用户"先 refresh_fund"。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from backend.db.models import FundNav
from backend.services.market import data_collector as dc
from backend.services.shared import metric_service as metrics


# ─── 常量 ────────────────────────────────────────────────────────────────────

DISCLAIMER = (
    "本结果是基于本地历史 NAV 的纯回测,不构成对未来收益的预测,"
    "也不构成买入、卖出、持有或调仓建议。"
)

# 窗口边界值:N 个交易日不强制 —— 只按日历日取窗口内所有 NAV 行。
# 缺失数据按"窗口最后一天有 NAV 的 fund"归一化权重。


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _maybe_round(value: float | None, ndigits: int = 6) -> float | None:
    """None 安全 round,metric_service 在 navs < 2 时返回 None。"""
    if value is None:
        return None
    return round(value, ndigits)


def _fetch_window_navs(session, fund_code: str,
                        start_date: str, end_date: str) -> list[tuple[str, float]]:
    """取一只基金在 [start_date, end_date] 窗口内的 (nav_date, accumulated_nav) 列表。

    按 nav_date 升序。无数据返回空列表。
    """
    stmt = (
        select(FundNav.nav_date, FundNav.accumulated_nav)
        .where(FundNav.fund_code == fund_code)
        .where(FundNav.nav_date >= start_date)
        .where(FundNav.nav_date <= end_date)
        .order_by(FundNav.nav_date)
    )
    rows = session.execute(stmt).all()
    return [(d, float(nv)) for d, nv in rows if nv is not None]


def _align_to_dates(
    fund_navs: dict[str, list[tuple[str, float]]],
) -> tuple[list[str], dict[str, dict[str, float]]]:
    """把所有 fund 的 NAV 对齐到统一日期序列。

    返回:
        dates: 升序的窗口日期列表(交集体,不是并集 — 否则组合 NAV
               无法逐日计算)。
        series: {fund_code: {nav_date: accumulated_nav}}

    对齐策略:某天某 fund 没数据 → 用最近一次已知 NAV 前向填充。
    整个窗口都缺的 fund 会在调用方被识别为 missing。
    """
    if not fund_navs:
        return [], {}

    # 取所有 fund 的日期并集
    all_dates = sorted({d for rows in fund_navs.values() for d, _ in rows})
    if not all_dates:
        return [], {}

    series: dict[str, dict[str, float]] = {}
    for code, rows in fund_navs.items():
        # 按日期排序
        rows_sorted = sorted(rows, key=lambda r: r[0])
        # 前向填充
        filled: dict[str, float] = {}
        last_known: float | None = None
        idx = 0
        for d in all_dates:
            # 跳过 idx 已用完的行
            while idx < len(rows_sorted) and rows_sorted[idx][0] < d:
                last_known = rows_sorted[idx][1]
                idx += 1
            if idx < len(rows_sorted) and rows_sorted[idx][0] == d:
                last_known = rows_sorted[idx][1]
                idx += 1
            if last_known is not None:
                filled[d] = last_known
        series[code] = filled

    # 取交集日期(所有 fund 都必须有 NAV,否则组合无法算)
    if not series:
        return [], {}
    codes = list(series.keys())
    common_dates = sorted(
        d for d in all_dates
        if all(d in series[c] for c in codes)
    )
    return common_dates, series


def _normalize_weights(
    holdings: dict[str, float],
    available_codes: list[str],
) -> dict[str, float]:
    """把权重重新归一化到可用 fund 上。

    - 输入:原始 holdings(可能含窗口里没数据的 fund)
    - 输出:只保留 available_codes 的 fund,权重按比例放大到和 = 1
    - 没有可用 fund → 返回空 dict
    """
    total = sum(holdings.get(c, 0.0) for c in available_codes)
    if total <= 0:
        return {}
    return {c: holdings[c] / total for c in available_codes}


def _portfolio_nav_series(
    dates: list[str],
    series: dict[str, dict[str, float]],
    weights: dict[str, float],
) -> list[float]:
    """按权重合成组合 NAV 序列。起点归一化到 1.0。

    portfolio_nav_t = sum_i( weight_i × nav_i_t / nav_i_0 )
    """
    if not dates or not weights:
        return []
    first_idx = dates[0]
    components: dict[str, list[float]] = {}
    for code, w in weights.items():
        if code not in series:
            continue
        base = series[code].get(first_idx)
        if not base:
            continue
        components[code] = [w * series[code].get(d, base) / base for d in dates]
    if not components:
        return []
    return [sum(components[c][i] for c in components) for i in range(len(dates))]


# ─── 主入口 ──────────────────────────────────────────────────────────────────

def backtest(
    session,
    *,
    start_date: str,
    end_date: str,
    holdings: dict[str, float],
) -> dict[str, Any]:
    """在 [start_date, end_date] 窗口内对给定权重组合做历史回测。

    参数:
        session: SQLAlchemy session(测试可传 in-memory)
        start_date / end_date: ISO-8601 字符串 "YYYY-MM-DD"
        holdings: {fund_code: weight},weight 任意正数,内部归一化

    返回 dict 结构:
        {
          "error": str | None,
          "window": {"start": ..., "end": ..., "trading_days": int},
          "funds": {
            code: {
              "weight": float (归一化后),
              "fund_return": float | None,  (窗口累计)
              "fund_max_drawdown": float | None,
            }, ...
          },
          "missing_funds": [code, ...],  (全窗口无 NAV 的 fund)
          "portfolio_return": float | None,
          "portfolio_max_drawdown": float | None,
          "source": "akshare",
          "as_of": end_date,
          "disclaimer": str,
        }
    """
    if not holdings:
        return _error_result("holdings 为空", start_date, end_date)

    if start_date > end_date:
        return _error_result("start_date 晚于 end_date", start_date, end_date)

    fund_navs: dict[str, list[tuple[str, float]]] = {}
    missing: list[str] = []
    for code in holdings:
        rows = _fetch_window_navs(session, code, start_date, end_date)
        if not rows:
            missing.append(code)
        else:
            fund_navs[code] = rows

    if not fund_navs:
        return _error_result(
            f"窗口内所有基金均无 NAV,需要先 refresh_fund;missing={missing}",
            start_date, end_date,
        )

    dates, series = _align_to_dates(fund_navs)
    available_codes = list(fund_navs.keys())

    # 算每个 fund 单独的窗口指标
    per_fund: dict[str, dict] = {}
    for code in available_codes:
        navs_window = [series[code][d] for d in dates if d in series[code]]
        if len(navs_window) < 1:
            continue
        per_fund[code] = {
            "fund_return": metrics.cumulative_return(navs_window),
            "fund_max_drawdown": metrics.max_drawdown(navs_window),
        }

    # 归一化权重并算组合
    weights = _normalize_weights(holdings, available_codes)
    portfolio_navs = _portfolio_nav_series(dates, series, weights)

    # 单点窗口的语义:用户选 start==end,组合未发生任何变化 → 收益/回撤 = 0
    if len(dates) <= 1:
        portfolio_return: float | None = 0.0
        portfolio_max_drawdown: float | None = 0.0
    else:
        portfolio_return = _maybe_round(metrics.cumulative_return(portfolio_navs))
        portfolio_max_drawdown = _maybe_round(metrics.max_drawdown(portfolio_navs))

    return {
        "error": None,
        "window": {
            "start": start_date,
            "end": end_date,
            "trading_days": len(dates),
        },
        "funds": {
            code: {
                "weight": round(weights.get(code, 0.0), 6),
                **per_fund.get(code, {}),
            }
            for code in available_codes
        },
        "missing_funds": missing,
        "portfolio_return": portfolio_return,
        "portfolio_max_drawdown": portfolio_max_drawdown,
        "source": "akshare",
        "as_of": end_date,
        "disclaimer": DISCLAIMER,
    }


def _error_result(msg: str, start_date: str, end_date: str) -> dict[str, Any]:
    """统一错误返回结构,LLM 可以直接把 error 字段复述给用户。"""
    return {
        "error": msg,
        "window": {"start": start_date, "end": end_date, "trading_days": 0},
        "funds": {},
        "missing_funds": [],
        "portfolio_return": None,
        "portfolio_max_drawdown": None,
        "source": "akshare",
        "as_of": end_date,
        "disclaimer": DISCLAIMER,
    }