"""CLS adapter builder integration tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache_after_test():
    yield
    from backend.config.settings import get_settings

    get_settings.cache_clear()


def test_build_default_adapters_includes_cls_only_for_post_market(monkeypatch):
    from backend.config.settings import get_settings
    from backend.services.market_sources import ClsTelegraphAdapter, build_default_adapters

    monkeypatch.setenv("CLS_ENABLED", "true")
    monkeypatch.setenv("CLS_CATEGORIES", "fund,watch")
    monkeypatch.setenv("CLS_PER_CATEGORY_LIMIT", "3")
    get_settings.cache_clear()

    pre = build_default_adapters(client=object(), brief_type="pre_market")
    post = build_default_adapters(client=object(), brief_type="post_market")

    assert not any(isinstance(adapter, ClsTelegraphAdapter) for adapter in pre)
    cls_adapters = [adapter for adapter in post if isinstance(adapter, ClsTelegraphAdapter)]
    assert len(cls_adapters) == 1
    assert cls_adapters[0].categories == ["fund", "watch"]
    assert cls_adapters[0].per_category_limit == 3


def test_build_default_adapters_excludes_cls_when_disabled(monkeypatch):
    from backend.config.settings import get_settings
    from backend.services.market_sources import ClsTelegraphAdapter, build_default_adapters

    monkeypatch.setenv("CLS_ENABLED", "false")
    get_settings.cache_clear()

    adapters = build_default_adapters(client=object(), brief_type="post_market")

    assert not any(isinstance(adapter, ClsTelegraphAdapter) for adapter in adapters)


def test_build_default_adapters_logs_cls_configuration_failure(monkeypatch):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    market_sources = importlib.import_module("backend.services.market_sources")
    build_default_adapters = market_sources.build_default_adapters
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
    monkeypatch.setattr(market_sources.logger, "warning", warning)

    build_default_adapters(client=object(), brief_type="post_market")

    warning.assert_called_once()
    assert "CLS adapter disabled" in warning.call_args.args[0]
    assert "bad cls settings" in str(warning.call_args.args[1])
