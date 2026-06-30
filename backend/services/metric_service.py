import math

_PERIOD_ROWS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126, "1y": 252}


def daily_returns(navs: list[float]) -> list[float]:
    return [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]


def cumulative_return(navs: list[float]) -> float | None:
    if len(navs) < 2:
        return None
    return navs[-1] / navs[0] - 1


def max_drawdown(navs: list[float]) -> float | None:
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
    dr = daily_returns(navs)
    if len(dr) < 2:
        return None
    mean = sum(dr) / len(dr)
    var = sum((x - mean) ** 2 for x in dr) / (len(dr) - 1)
    std = math.sqrt(var)
    return std * math.sqrt(periods_per_year) if annualize else std


def period_return(navs: list[float], period: str) -> float | None:
    if period not in _PERIOD_ROWS:
        raise ValueError(f"unsupported period: {period}")
    n = _PERIOD_ROWS[period]
    if len(navs) < n + 1:
        return None
    window = navs[-(n + 1):]
    return window[-1] / window[0] - 1
