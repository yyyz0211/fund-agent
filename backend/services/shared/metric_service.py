"""纯 Python 实现的金融指标计算。

无 I/O、无第三方依赖,所有输入都是 `list[float]`(累计净值序列),
所有输出都是 Python 原生数值或 `None`。这让指标可以被
`fund_service`、测试、未来的分析脚本同时复用,而且结果可以
逐位复现。

`_PERIOD_ROWS` 是中国 A 股交易日的常用口径:
    1w ≈ 5 个交易日,1m ≈ 21,3m ≈ 63,6m ≈ 126,1y ≈ 252,
    all 表示本地全量历史。
"""
import math

from backend.exceptions import InputValidationError

_PERIOD_ROWS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "6m": 126, "1y": 252, "all": None}


def daily_returns(navs: list[float]) -> list[float]:
    """逐日收益率序列:第 i 个值 = navs[i] / navs[i-1] - 1。长度比 navs 少 1。"""
    return [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]


def cumulative_return(navs: list[float]) -> float | None:
    """区间累计收益:末值 / 首值 - 1。少于 2 个点返回 None。"""
    if len(navs) < 2:
        return None
    return navs[-1] / navs[0] - 1


def max_drawdown(navs: list[float]) -> float | None:
    """最大回撤(负值或 0):从历史最高点到此后任一最低点的最大跌幅。

    一遍扫描即可:对每个点更新 peak(历史最高),并用
    `value / peak - 1` 更新 worst(最深的相对回撤)。少于 2 个点返回 None。
    """
    if len(navs) < 2:
        return None
    peak = navs[0]
    worst = 0.0
    for v in navs:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def volatility(navs: list[float], annualize: bool = True,
               periods_per_year: int = 252) -> float | None:
    """波动率(年化标准差,默认)。

    - `annualize=True`  → 用日收益样本标准差 × √252 折算成年化。
    - 日收益少于 2 个点(累计净值少于 3 个点)时返回 None,
      因为无法估计方差。
    """
    dr = daily_returns(navs)
    if len(dr) < 2:
        return None
    mean = sum(dr) / len(dr)
    var = sum((x - mean) ** 2 for x in dr) / (len(dr) - 1)
    std = math.sqrt(var)
    return std * math.sqrt(periods_per_year) if annualize else std


def period_return(navs: list[float], period: str) -> float | None:
    """区间收益率:`period ∈ {"1w","1m","3m","6m","1y","all"}`。

    固定窗口取最近 N+1 个点。之所以要 N+1 个点(而不是 N 个)是为了
    在累计净值序列上得到恰好 N 个日收益。`all` 使用本地全量历史。
    点数不够时返回 None(而不是抛错),让上层 service 可以走"数据不足"分支。
    不支持的 period 抛 `ValueError`,因为那是调用方 bug。
    """
    if period not in _PERIOD_ROWS:
        raise InputValidationError(
            f"unsupported period: {period}",
            field="period",
            details={"allowed": sorted(k for k in _PERIOD_ROWS if _PERIOD_ROWS[k] is not None)},
        )
    n = _PERIOD_ROWS[period]
    if n is None:
        return cumulative_return(navs)
    if len(navs) < n + 1:
        return None
    window = navs[-(n + 1):]
    return window[-1] / window[0] - 1
