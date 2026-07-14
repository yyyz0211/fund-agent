"""Domain Types: Briefing 输入输出类型和端口定义。

这些类型定义了 briefing 领域的稳定接口，不依赖外部实现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Protocol, Sequence, TypeVar

# Generic type variables for Protocol
InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


# ---------------------------------------------------------------------------
# ChatModel Protocol (dependency injection port)
# ---------------------------------------------------------------------------


class ChatModel(Protocol[InputT, OutputT]):
    """聊天模型的最小接口定义。

    用于依赖注入，允许在测试时替换为 FakeModel。
    """

    def invoke(self, input: InputT, **kwargs: Any) -> OutputT:
        """同步调用模型。"""
        ...


class StreamableChatModel(Protocol[InputT, OutputT]):
    """支持流式输出的聊天模型接口。"""

    def invoke(self, input: InputT, **kwargs: Any) -> OutputT:
        """同步调用模型。"""
        ...

    def stream(self, input: InputT, **kwargs: Any) -> Any:
        """流式调用模型。"""
        ...


# ---------------------------------------------------------------------------
# Briefing Types
# ---------------------------------------------------------------------------


@dataclass
class WatchlistSnapshot:
    """自选池快照。"""
    fund_codes: list[str]
    holdings: dict[str, dict]
    metrics: dict[str, dict]
    errors: list[str]


@dataclass
class MarketSnapshot:
    """市场快照。"""
    indices: list[dict]
    breadth: dict
    industry_sectors: list[dict]
    concept_sectors: list[dict]
    industry_flows: list[dict]
    concept_flows: list[dict]
    themes: list[dict]
    breadth_indicators: dict
    overseas: list[dict]
    announcements: list[dict]
    errors: list[str]
    collect_meta: dict


@dataclass
class EvidenceRecord:
    """市场证据记录。"""
    id: int
    trade_date: str
    category: str
    title: str
    summary: Optional[str]
    symbols: list[str]
    source: str
    source_url: str
    reliability: str


@dataclass
class BriefingInput:
    """简报生成输入。"""
    briefing_date: str
    brief_type: str
    watchlist_snapshot: WatchlistSnapshot
    market_snapshot: MarketSnapshot
    evidence: list[EvidenceRecord]
    data_quality: str
    confidence: str
    missing_data: list[str]


@dataclass
class ModuleEnvelope:
    """简报模块信封。"""
    module_name: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class BriefingResult:
    """简报生成结果。"""
    title: str
    markdown: str
    sections: dict[str, Any]
    data_quality: str
    confidence: str
    missing_data: list[str]
    evidence_count: int
    modules: list[ModuleEnvelope]
