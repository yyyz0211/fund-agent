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
    from backend.services.briefing.types import (
        BriefTypeProfile,
        ModuleSection,
        get_brief_type_profile,
    )

    assert BriefTypeProfile is not None
    assert ModuleSection is not None
    profile, warnings = get_brief_type_profile("post_market")
    assert profile.brief_type == "post_market"
    assert warnings == []
