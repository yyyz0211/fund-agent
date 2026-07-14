"""market_sources: 统一的 source adapter 集合。

每个 adapter 暴露一个 `.fetch(*, client, trade_date, brief_type="post_market") -> list[dict]`
方法,返回标准化的 evidence dict:

    {
        "trade_date": "YYYY-MM-DD",
        "brief_type": "pre_market" | "post_market",
        "category": "policy" | "announcement" | "overseas_disclosure" | "macro" | "sector",
        "title": "...",
        "summary": "...",
        "symbols": [...],
        "metrics": {...} | None,
        "source": "...",
        "source_url": "...",
        "published_at": "YYYY-MM-DD" | None,
        "reliability": "official" | "wire" | "rumor",
    }

约定:
- adapter 必须**永不抛出**: 网络异常、解析异常一律返回空列表, 让 ingestion 层隔离失败。
- HTTP 客户端由调用方注入, 测试用 MagicMock; 生产用 httpx.Client。
- URL 字段必须是**绝对 URL**, 便于前端直接渲染 `<a href={source_url}>`。
"""
from __future__ import annotations

import logging
from typing import Iterable

from backend.services.market_sources.policy_page import PolicyPageAdapter
from backend.services.market_sources.fred import FredSeriesAdapter
from backend.services.market_sources.cninfo import CninfoAnnouncementAdapter
from backend.services.market_sources.sector import SectorHeatAdapter
from backend.services.market_sources.cls_telegraph import ClsTelegraphAdapter


logger = logging.getLogger(__name__)


# 盘前 (pre_market) 关心的政策/宏观源
DEFAULT_POLICY_ADAPTERS: list[tuple[str, str, str]] = [
    # (source_name, url, reliability)
    ("NMPA", "https://www.nmpa.gov.cn/yaopin/", "official"),
    ("CSRC", "https://www.csrc.gov.cn/csrc/c100028/common_list.shtml", "official"),
    ("PBOC", "http://www.pbc.gov.cn/zhengwugongkai/4081330/index.html", "official"),
    ("NDRC", "https://www.ndrc.gov.cn/xxgk/zcfb/", "official"),
    ("MOF", "http://www.mof.gov.cn/zhengwuxinxi/zhengcefabu/", "official"),
]


# FRED 公开 CSV 系列 — 盘前宏观参考 (无需 API key)
DEFAULT_FRED_SERIES: list[tuple[str, str]] = [
    ("DFF", "美国联邦基金有效利率"),
    ("CPIAUCSL", "美国 CPI 月环比"),
    ("UNRATE", "美国失业率"),
]


def build_default_adapters(*, client, brief_type: str = "post_market",
                           sector_snapshot: dict | None = None) -> list:
    """构造 production 用的全量 adapter 列表。

    参数:
        client: 注入的 httpx.Client (测试可传 MagicMock)
        brief_type: 决定取哪些 adapter
            - "pre_market": 仅宏观 + 政策
            - "post_market": 政策 + 公告 + 宏观 + 行业热点(sector)
        sector_snapshot: SectorHeatAdapter 需要当日 industry_sectors; 传 None 时跳过 sector 类别
    """
    adapters: list = []
    if brief_type == "pre_market":
        adapters.extend(
            FredSeriesAdapter(series_id=sid, title=title)
            for sid, title in DEFAULT_FRED_SERIES
        )
        adapters.extend(
            PolicyPageAdapter(source=name, url=url, reliability=reli)
            for name, url, reli in DEFAULT_POLICY_ADAPTERS
        )
    else:
        # post_market
        adapters.extend(
            PolicyPageAdapter(source=name, url=url, reliability=reli)
            for name, url, reli in DEFAULT_POLICY_ADAPTERS
        )
        adapters.append(CninfoAnnouncementAdapter())
        adapters.extend(
            FredSeriesAdapter(series_id=sid, title=title)
            for sid, title in DEFAULT_FRED_SERIES
        )
        if sector_snapshot is not None:
            adapters.append(SectorHeatAdapter(sector_snapshot=sector_snapshot))
        try:
            from backend.config.settings import get_settings
            settings = get_settings()
            if settings.cls_enabled:
                adapters.append(ClsTelegraphAdapter(
                    client=client,
                    categories=settings.cls_categories,
                    per_category_limit=settings.cls_per_category_limit,
                    timeout_seconds=settings.cls_timeout_seconds,
                    app_version=settings.cls_app_version,
                    max_attempts=int(getattr(settings, "cls_max_attempts", 1)),
                    retry_base_seconds=float(getattr(settings, "cls_retry_base_seconds", 1.0)),
                ))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CLS adapter disabled due to configuration error: %s",
                exc,
                exc_info=True,
            )
    return adapters


__all__ = [
    "PolicyPageAdapter",
    "FredSeriesAdapter",
    "CninfoAnnouncementAdapter",
    "SectorHeatAdapter",
    "ClsTelegraphAdapter",
    "build_default_adapters",
    "DEFAULT_POLICY_ADAPTERS",
    "DEFAULT_FRED_SERIES",
]
