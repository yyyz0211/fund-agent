"""Briefing deterministic module boundary tests."""
from __future__ import annotations


def test_pre_market_overnight_module_uses_evidence():
    from backend.services.briefing import modules

    profile, warnings = modules.get_brief_type_profile("pre_market")
    built, order, module_warnings = modules.run_module_builders(
        profile=profile,
        snapshot={},
        evidence=[{
            "id": 1,
            "category": "news",
            "title": "美股上涨",
            "summary": "纳指收涨",
            "source": "wire",
        }],
        context={},
    )

    assert warnings == []
    assert "overnight" in built
    assert "overnight" in order
    assert built["overnight"].key == "overnight"
    assert built["overnight"].status == "ready"
    assert built["overnight"].content["events"][0]["name"] == "美股上涨"
    assert module_warnings == []


def test_modules_owns_builders_without_legacy_reexport():
    import inspect

    from backend.services.briefing import modules

    source = inspect.getsource(modules)
    assert "module_briefing" not in source
    assert modules.run_module_builders.__module__ == modules.__name__
