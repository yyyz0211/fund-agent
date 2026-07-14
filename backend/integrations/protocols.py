"""Integrations 外部数据源适配器.

本模块定义外部数据源适配器的公共协议和注册表。

适配器约定:
- adapter 必须永不抛出: 网络异常、解析异常一律返回空列表
- HTTP 客户端由调用方注入, 测试用 MagicMock, 生产用 httpx.Client
- URL 必须是绝对 URL, 便于前端直接渲染
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Evidence 标准格式
EvidenceDict = dict[str, Any]

BriefType = Literal["pre_market", "post_market"]


@dataclass(frozen=True, slots=True)
class AdapterMetadata:
    """适配器元信息"""

    name: str
    category: str  # policy | announcement | overseas_disclosure | macro | sector
    source: str
    source_url: str | None = None
    reliability: Literal["official", "wire", "rumor"] = "official"
    timeout_seconds: int = 30
    max_attempts: int = 1


@runtime_checkable
class MarketSourceAdapter(Protocol):
    """市场数据源适配器协议"""

    @property
    def metadata(self) -> AdapterMetadata:
        """返回适配器元信息"""
        ...

    def fetch(
        self,
        *,
        trade_date: date,
        brief_type: BriefType = "post_market",
        client: Any | None = None,
        **kwargs: Any,
    ) -> list[EvidenceDict]:
        """拉取证据列表, 失败时返回空列表"""
        ...


@dataclass
class RetryConfig:
    """重试配置"""

    max_attempts: int = 1
    base_seconds: float = 1.0
    max_seconds: float = 10.0


@dataclass
class IntegrationConfig:
    """集成配置基类"""

    timeout_seconds: float = 30.0
    retry: RetryConfig = field(default_factory=RetryConfig)
    enabled: bool = True


@dataclass
class PolicyConfig(IntegrationConfig):
    """政策源配置"""

    source: str = ""
    url: str = ""
    reliability: Literal["official", "wire", "rumor"] = "official"


@dataclass
class FredConfig(IntegrationConfig):
    """FRED 配置"""

    series_id: str = ""
    title: str = ""


@dataclass
class CninfoConfig(IntegrationConfig):
    """巨潮资讯配置"""

    pass


@dataclass
class SectorConfig(IntegrationConfig):
    """行业热点配置"""

    pass


@dataclass
class ClsConfig(IntegrationConfig):
    """财联社电报配置"""

    categories: list[str] = field(default_factory=list)
    per_category_limit: int = 10
    app_version: str = ""
    enabled: bool = False
