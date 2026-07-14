"""Briefing 领域的稳定输入、输出类型和依赖注入端口。

注意 `module_briefing` 仅在 `TYPE_CHECKING` 模式下导入 — 否则会与
`module_briefing` 的顶层 import 形成循环:
  types → module_briefing (获取 dataclass 类型)
  module_briefing → types (获取 ChatModel Protocol)

这是 Python dataclass + Protocol 跨文件的常见坑。运行时 dataclass 字段
不需要从 `module_briefing` 导入也能工作(只要 dataclass 自己已经定义),
所以这里只在类型检查时引入它。运行时 type hint 使用 `from __future__
import annotations` 已经全部转为字符串解析。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Protocol, TypeVar

if TYPE_CHECKING:
    from backend.services.briefing.module_briefing import (
        BriefTypeProfile,
        ModuleSection,
    )

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


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
