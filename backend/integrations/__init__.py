"""Integrations: 外部数据源适配器.

本目录包含所有外部数据源 (akshare, cls, cninfo, fred, policy 等) 的适配器实现。
"""
from __future__ import annotations

from .protocols import (
    AdapterMetadata,
    BriefType,
    IntegrationConfig,
    MarketSourceAdapter,
    RetryConfig,
)
from .registry import AdapterRegistry, get_adapter_config

__all__ = [
    # Protocols
    "AdapterMetadata",
    "BriefType",
    "IntegrationConfig",
    "MarketSourceAdapter",
    "RetryConfig",
    # Registry
    "AdapterRegistry",
    "get_adapter_config",
]
