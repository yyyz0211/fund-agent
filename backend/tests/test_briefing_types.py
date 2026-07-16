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


def test_briefing_profile_types_are_owned_by_types_module():
    from backend.services.briefing import types

    assert types.BriefTypeProfile.__module__ == types.__name__
    assert types.ModuleSection.__module__ == types.__name__
    assert hasattr(types.BriefTypeProfile, "__dataclass_fields__")
    assert hasattr(types.ModuleSection, "__dataclass_fields__")

    profile = types.BriefTypeProfile.post_market()
    section = types.ModuleSection(key="market_state", title="市场状态")

    assert profile.brief_type == "post_market"
    assert section.to_dict()["status"] == "ready"


def test_types_module_does_not_import_other_briefing_modules():
    import ast
    import inspect

    from backend.services.briefing import types

    tree = ast.parse(inspect.getsource(types))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(
        name.startswith("backend.services.briefing.")
        for name in imported
    )


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
