"""Briefing 稳定领域类型的兼容测试。"""
from __future__ import annotations


def test_briefing_domain_types_remain_public_and_constructible():
    from backend.services.briefing.types import (
        BriefingInput,
        BriefingResult,
        ChatModel,
        EvidenceRecord,
        MarketSnapshot,
        ModuleEnvelope,
        WatchlistSnapshot,
    )

    watchlist = WatchlistSnapshot([], {}, {}, [])
    market = MarketSnapshot([], {}, [], [], [], [], [], {}, [], [], [], {})
    evidence = EvidenceRecord(1, "2026-07-14", "policy", "title", None, [], "source", "", "official")
    briefing_input = BriefingInput(
        "2026-07-14", "post_market", watchlist, market, [evidence], "complete", "high", []
    )
    envelope = ModuleEnvelope("overview", "content")
    result = BriefingResult("title", "markdown", {}, "complete", "high", [], 1, [envelope])

    assert hasattr(ChatModel, "invoke")
    assert briefing_input.evidence == [evidence]
    assert envelope.metadata == {}
    assert result.modules == [envelope]


def test_briefing_profile_types_are_still_reexported():
    """`BriefTypeProfile` / `ModuleSection` 在 module_briefing 定义,作为
    briefing 领域的稳定 dataclass;`get_brief_type_profile` 是工厂函数。
    `types` 模块通过 TYPE_CHECKING 暴露类型名,不在运行时 re-export,避免
    与 module_briefing 形成循环 import。
    """
    from backend.services.briefing.module_briefing import (
        BriefTypeProfile,
        ModuleSection,
        get_brief_type_profile,
    )

    assert hasattr(BriefTypeProfile, "__dataclass_fields__")
    assert hasattr(ModuleSection, "__dataclass_fields__")
    profile, warnings = get_brief_type_profile("post_market")
    assert profile.brief_type == "post_market"
    assert warnings == []


def test_types_module_exposes_dataclass_signatures():
    """`types` 模块的 dataclass 字段在 runtime 也能 introspect,因为
    `from __future__ import annotations` 不会把字段真正替换成字符串,
    只是让注解变为 lazy evaluation。
    """
    from backend.services.briefing.types import (
        BriefingInput,
        BriefingResult,
        WatchlistSnapshot,
    )

    assert hasattr(WatchlistSnapshot, "__dataclass_fields__")
    assert "fund_codes" in WatchlistSnapshot.__dataclass_fields__
    assert "briefing_date" in BriefingInput.__dataclass_fields__
    assert "markdown" in BriefingResult.__dataclass_fields__
