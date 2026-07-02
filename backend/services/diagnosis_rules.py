"""Deterministic fund diagnosis rules."""
from __future__ import annotations


THRESHOLDS_BY_CATEGORY: dict[str, dict[str, tuple[float, ...]]] = {
    "偏股混合": {
        "drawdown": (-0.30, -0.15),
        "volatility": (0.25, 0.15),
        "period_return": (-0.15, -0.05, 0.50, 0.25),
    },
    "股票型": {
        "drawdown": (-0.30, -0.15),
        "volatility": (0.28, 0.18),
        "period_return": (-0.18, -0.08, 0.55, 0.30),
    },
    "债券型": {
        "drawdown": (-0.10, -0.05),
        "volatility": (0.08, 0.04),
        "period_return": (-0.05, -0.02, 0.18, 0.10),
    },
}


def _thresholds(category: str | None) -> dict[str, tuple[float, ...]]:
    if category:
        for key, value in THRESHOLDS_BY_CATEGORY.items():
            if key in category:
                return value
    return THRESHOLDS_BY_CATEGORY["偏股混合"]


def level_for_drawdown(value: float | None, category: str = "偏股混合") -> str:
    """最大回撤风险灯。value 通常是负数。"""
    if value is None:
        return "gray"
    red, yellow = _thresholds(category)["drawdown"]
    if value <= red:
        return "red"
    if value <= yellow:
        return "yellow"
    return "green"


def level_for_volatility(value: float | None, category: str = "偏股混合") -> str:
    """波动率风险灯。"""
    if value is None:
        return "gray"
    red, yellow = _thresholds(category)["volatility"]
    if value >= red:
        return "red"
    if value >= yellow:
        return "yellow"
    return "green"


def level_for_period_return(value: float | None, category: str = "偏股混合") -> str:
    """区间收益风险灯:大跌和短期暴涨都算风险。"""
    if value is None:
        return "gray"
    red_down, yellow_down, red_up, yellow_up = _thresholds(category)["period_return"]
    if value <= red_down or value >= red_up:
        return "red"
    if value <= yellow_down or value >= yellow_up:
        return "yellow"
    return "green"


def level_for_age_years(value: float | None) -> str:
    """成立时间灯:时间过短时历史样本不足。"""
    if value is None:
        return "gray"
    if value < 1:
        return "red"
    if value < 3:
        return "yellow"
    return "green"


def level_for_scale(value: float | None) -> str:
    """规模灯。单位按 AkShare 返回的亿元口径处理。"""
    if value is None:
        return "gray"
    if value < 0.5:
        return "red"
    if value < 2:
        return "yellow"
    return "green"


def level_for_concentration(value: float | None) -> str:
    """集中度灯。value 是 0-1 比例。"""
    if value is None:
        return "gray"
    if value >= 0.60:
        return "red"
    if value >= 0.40:
        return "yellow"
    return "green"


def choose_decision_label(lights: list[dict], missing_data: list[str]) -> str:
    """Combine risk lights into a local decision-aid label."""
    if any(item.get("level") == "red" for item in lights):
        return "暂不碰"
    core_missing = {"fund", "nav", "latest_nav", "metrics", "core"}
    if core_missing.intersection(missing_data or []):
        return "暂不碰"
    yellow_count = sum(1 for item in lights if item.get("level") == "yellow")
    green_count = sum(1 for item in lights if item.get("level") == "green")
    if yellow_count >= 2:
        return "观察"
    if yellow_count == 1:
        return "小仓试验"
    if green_count >= 4 and not missing_data:
        return "候选"
    return "观察"


def confidence_for(core_complete: bool, profile_complete: bool, peers_count: int) -> str:
    """Return low/medium/high confidence for diagnosis output."""
    if not core_complete:
        return "low"
    if profile_complete and peers_count >= 3:
        return "high"
    return "medium"
