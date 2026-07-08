"""CLS adapter builder integration tests."""
from __future__ import annotations

import logging


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


def test_build_default_adapters_logs_cls_configuration_failure(monkeypatch, caplog):
    from backend.config import settings as settings_mod
    from backend.services.market_sources import build_default_adapters

    def broken_settings():
        raise RuntimeError("bad cls settings")

    monkeypatch.setattr(settings_mod, "get_settings", broken_settings)

    with caplog.at_level(logging.WARNING):
        build_default_adapters(client=object(), brief_type="post_market")

    assert "CLS adapter disabled" in caplog.text
    assert "bad cls settings" in caplog.text
