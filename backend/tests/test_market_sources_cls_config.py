"""CLS adapter builder integration tests."""
from __future__ import annotations

import pytest


def _factory_kwargs() -> dict:
    return {
        "client": object(),
        "fetch_cls_roll_list": lambda **_: [],
        "fetch_announcements": lambda **_: [],
    }


@pytest.fixture(autouse=True)
def _clear_settings_cache_after_test():
    yield
    from backend.config.settings import get_settings

    get_settings.cache_clear()


def test_build_default_adapters_includes_cls_only_for_post_market(monkeypatch):
    from backend.config.settings import get_settings
    from backend.integrations.cls import ClsTelegraphAdapter
    from backend.integrations.market_evidence import build_default_adapters

    monkeypatch.setenv("CLS_ENABLED", "true")
    monkeypatch.setenv("CLS_CATEGORIES", "fund,watch")
    monkeypatch.setenv("CLS_PER_CATEGORY_LIMIT", "3")
    get_settings.cache_clear()

    pre = build_default_adapters(brief_type="pre_market", **_factory_kwargs())
    post = build_default_adapters(brief_type="post_market", **_factory_kwargs())

    assert not any(isinstance(adapter, ClsTelegraphAdapter) for adapter in pre)
    cls_adapters = [adapter for adapter in post if isinstance(adapter, ClsTelegraphAdapter)]
    assert len(cls_adapters) == 1
    assert cls_adapters[0].categories == ["fund", "watch"]
    assert cls_adapters[0].per_category_limit == 3


def test_build_default_adapters_excludes_cls_when_disabled(monkeypatch):
    from backend.config.settings import get_settings
    from backend.integrations.cls import ClsTelegraphAdapter
    from backend.integrations.market_evidence import build_default_adapters

    monkeypatch.setenv("CLS_ENABLED", "false")
    get_settings.cache_clear()

    adapters = build_default_adapters(
        brief_type="post_market",
        **_factory_kwargs(),
    )

    assert not any(isinstance(adapter, ClsTelegraphAdapter) for adapter in adapters)


def test_build_default_adapters_logs_cls_configuration_failure(monkeypatch):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    market_evidence = importlib.import_module("backend.integrations.market_evidence")
    build_default_adapters = market_evidence.build_default_adapters
    monkeypatch.setitem(
        build_default_adapters.__globals__,
        "get_settings",
        lambda: SimpleNamespace(
            cls_enabled=True,
            cls_categories="fund",
            cls_per_category_limit=1,
            cls_timeout_seconds=1.0,
            cls_app_version="test",
            cls_max_attempts=1,
            cls_retry_base_seconds=0.0,
        ),
    )
    monkeypatch.setitem(
        build_default_adapters.__globals__,
        "ClsTelegraphAdapter",
        MagicMock(side_effect=RuntimeError("bad cls settings")),
    )
    warning = MagicMock()
    monkeypatch.setattr(market_evidence.logger, "warning", warning)

    build_default_adapters(brief_type="post_market", **_factory_kwargs())

    warning.assert_called_once()
    assert "CLS adapter disabled" in warning.call_args.args[0]
    assert "bad cls settings" in str(warning.call_args.args[1])


def test_build_default_adapters_preserves_type_order(monkeypatch):
    from backend.config.settings import get_settings
    from backend.integrations.cninfo import CninfoAnnouncementAdapter
    from backend.integrations.fred import FredSeriesAdapter
    from backend.integrations.market_evidence import build_default_adapters
    from backend.integrations.policy import PolicyPageAdapter
    from backend.integrations.sector import SectorHeatAdapter

    monkeypatch.setenv("CLS_ENABLED", "false")
    get_settings.cache_clear()

    pre = build_default_adapters(brief_type="pre_market", **_factory_kwargs())
    post = build_default_adapters(
        brief_type="post_market",
        sector_snapshot={"industry_sectors": []},
        **_factory_kwargs(),
    )

    assert [type(adapter) for adapter in pre] == (
        [FredSeriesAdapter] * 3 + [PolicyPageAdapter] * 5
    )
    assert [type(adapter) for adapter in post] == (
        [PolicyPageAdapter] * 5
        + [CninfoAnnouncementAdapter]
        + [FredSeriesAdapter] * 3
        + [SectorHeatAdapter]
    )


def test_build_default_adapters_requires_both_fetch_callables():
    from backend.integrations.market_evidence import build_default_adapters

    with pytest.raises(TypeError):
        build_default_adapters(client=object())
