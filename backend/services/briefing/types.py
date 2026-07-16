"""Briefing 领域的稳定输入、输出类型和依赖注入端口。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional, Protocol, TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


@dataclass
class BriefTypeProfile:
    brief_type: str
    title: str
    required_modules: list[str]
    optional_modules: list[str]
    forbidden_modules: list[str]
    data_window: str
    max_markdown_words: int

    @classmethod
    def post_market(cls) -> "BriefTypeProfile":
        return cls(
            brief_type="post_market",
            title="盘后简报",
            required_modules=[
                "quick_summary", "market_state", "themes_and_flows",
                "watchlist_impact", "risk_radar", "key_evidence",
                "data_statement",
            ],
            optional_modules=[],
            forbidden_modules=["overnight", "intraday_anomaly"],
            data_window="trade_date_full_day",
            max_markdown_words=1000,
        )

    @classmethod
    def pre_market(cls) -> "BriefTypeProfile":
        return cls(
            brief_type="pre_market",
            title="盘前简报",
            required_modules=[
                "quick_summary", "overnight", "key_evidence",
                "watchlist_impact", "risk_radar", "data_statement",
            ],
            optional_modules=["events"],
            forbidden_modules=["themes_and_flows", "intraday_anomaly"],
            data_window="pre_market",
            max_markdown_words=800,
        )

    @classmethod
    def intraday(cls) -> "BriefTypeProfile":
        return cls(
            brief_type="intraday",
            title="盘中简报",
            required_modules=[
                "quick_summary", "market_state", "themes_and_flows",
                "intraday_anomaly", "watchlist_impact", "risk_radar",
                "data_statement",
            ],
            optional_modules=["key_evidence"],
            forbidden_modules=["overnight"],
            data_window="intraday",
            max_markdown_words=600,
        )


@dataclass
class ModuleSection:
    key: str
    title: str
    status: Literal["ready", "partial", "missing", "failed"] = "ready"
    summary: str = ""
    content: dict = field(default_factory=dict)
    evidence_ids: list[int] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"

    def to_dict(self) -> dict:
        return asdict(self)


class ChatModel(Protocol[InputT, OutputT]):
    """聊天模型的最小同步调用接口。"""

    def invoke(self, input: InputT, **kwargs: Any) -> OutputT: ...


class StreamableChatModel(Protocol[InputT, OutputT]):
    """支持同步和流式输出的聊天模型接口。"""

    def invoke(self, input: InputT, **kwargs: Any) -> OutputT: ...

    def stream(self, input: InputT, **kwargs: Any) -> Any: ...


@dataclass
class WatchlistSnapshot:
    fund_codes: list[str]
    holdings: dict[str, dict]
    metrics: dict[str, dict]
    errors: list[str]


@dataclass
class MarketSnapshot:
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
    module_name: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class BriefingResult:
    title: str
    markdown: str
    sections: dict[str, Any]
    data_quality: str
    confidence: str
    missing_data: list[str]
    evidence_count: int
    modules: list[ModuleEnvelope]


__all__ = [
    "BriefTypeProfile",
    "BriefingInput",
    "BriefingResult",
    "ChatModel",
    "EvidenceRecord",
    "MarketSnapshot",
    "ModuleEnvelope",
    "ModuleSection",
    "StreamableChatModel",
    "WatchlistSnapshot",
]
