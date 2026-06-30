"""Deterministic compliance policy for the fund QA graph."""
from dataclasses import dataclass

REFUSAL_MESSAGE = (
    "我只能提供公开信息整理、历史数据分析和风险提示，不能提供买入、卖出、"
    "持有、加仓、减仓、申购、赎回、基金推荐或收益预测建议。"
)

_BLOCK_PATTERNS = (
    "可以买",
    "买入",
    "买进",
    "卖出",
    "要不要卖",
    "持有",
    "加仓",
    "减仓",
    "申购",
    "赎回",
    "推荐",
    "收益大概",
    "收益多少",
    "未来收益",
    "下个月收益",
    "预测收益",
)


@dataclass(frozen=True)
class PolicyResult:
    """Result of a deterministic policy check."""

    allowed: bool
    reason: str = ""


def _normalize(text: str) -> str:
    return "".join((text or "").lower().split())


def check_question(text: str) -> PolicyResult:
    """Return whether a user question may proceed to the LLM/tool graph."""
    normalized = _normalize(text)
    for pattern in _BLOCK_PATTERNS:
        if pattern in normalized:
            return PolicyResult(False, f"blocked pattern: {pattern}")
    return PolicyResult(True)


def check_answer(text: str) -> str:
    """Replace unsafe generated answers with the fixed refusal."""
    return REFUSAL_MESSAGE if not check_question(text).allowed else text
