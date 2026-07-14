"""Integration Registry 配置映射测试。"""
from __future__ import annotations

from types import SimpleNamespace

from backend.integrations.protocols import ClsConfig
from backend.integrations.registry import get_adapter_config


def test_cls_adapter_config_uses_existing_flat_settings(monkeypatch):
    from backend.config import settings as settings_module

    settings = SimpleNamespace(
        cls_enabled=True,
        cls_timeout_seconds=12.5,
        cls_max_attempts=3,
        cls_retry_base_seconds=0.75,
        cls_categories="fund, watch,announcement",
        cls_per_category_limit=7,
        cls_app_version="9.0.0",
    )
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)

    config = get_adapter_config("ClsTelegraphAdapter")

    assert isinstance(config, ClsConfig)
    assert config.enabled is True
    assert config.timeout_seconds == 12.5
    assert config.retry.max_attempts == 3
    assert config.retry.base_seconds == 0.75
    assert config.categories == ["fund", "watch", "announcement"]
    assert config.per_category_limit == 7
    assert config.app_version == "9.0.0"


def test_unconfigured_or_unknown_adapter_returns_none(monkeypatch):
    from backend.config import settings as settings_module

    monkeypatch.setattr(settings_module, "get_settings", lambda: SimpleNamespace())

    assert get_adapter_config("PolicyPageAdapter") is None
    assert get_adapter_config("UnknownAdapter") is None
