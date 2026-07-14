"""适配器注册表.

提供运行时适配器发现和配置管理。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .protocols import MarketSourceAdapter, IntegrationConfig

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """适配器注册表"""

    _adapters: dict[str, type["MarketSourceAdapter"]] = {}

    @classmethod
    def register(cls, name: str, adapter_class: type["MarketSourceAdapter"]) -> None:
        """注册适配器类"""
        cls._adapters[name] = adapter_class
        logger.debug("Registered adapter: %s", name)

    @classmethod
    def get(cls, name: str) -> type["MarketSourceAdapter"] | None:
        """获取已注册的适配器类"""
        return cls._adapters.get(name)

    @classmethod
    def list_adapters(cls) -> list[str]:
        """列出所有已注册的适配器名称"""
        return list(cls._adapters.keys())

    @classmethod
    def clear(cls) -> None:
        """清空注册表 (主要用于测试)"""
        cls._adapters.clear()


def get_adapter_config(name: str) -> "IntegrationConfig | None":
    """根据现有 Settings 契约构造适配器配置。

    尚未接入 Settings 的 adapter 明确返回 ``None``，避免通过不存在的
    复合属性隐式猜测配置。
    """
    if name != "ClsTelegraphAdapter":
        return None

    from backend.config.settings import get_settings
    from backend.integrations.protocols import ClsConfig, RetryConfig

    settings = get_settings()
    categories = [
        category.strip()
        for category in settings.cls_categories.split(",")
        if category.strip()
    ]
    return ClsConfig(
        enabled=settings.cls_enabled,
        timeout_seconds=settings.cls_timeout_seconds,
        retry=RetryConfig(
            max_attempts=settings.cls_max_attempts,
            base_seconds=settings.cls_retry_base_seconds,
        ),
        categories=categories,
        per_category_limit=settings.cls_per_category_limit,
        app_version=settings.cls_app_version,
    )


__all__ = [
    "AdapterRegistry",
    "get_adapter_config",
]
