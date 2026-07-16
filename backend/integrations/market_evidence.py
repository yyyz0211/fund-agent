"""Default market-evidence adapter composition."""
from __future__ import annotations

import logging

from backend.config.settings import get_settings
from backend.integrations.cls import ClsTelegraphAdapter
from backend.integrations.cninfo import CninfoAnnouncementAdapter
from backend.integrations.fred import FredSeriesAdapter
from backend.integrations.policy import PolicyPageAdapter
from backend.integrations.sector import SectorHeatAdapter


logger = logging.getLogger(__name__)


DEFAULT_POLICY_ADAPTERS: list[tuple[str, str, str]] = [
    ("NMPA", "https://www.nmpa.gov.cn/yaopin/", "official"),
    ("CSRC", "https://www.csrc.gov.cn/csrc/c100028/common_list.shtml", "official"),
    ("PBOC", "http://www.pbc.gov.cn/zhengwugongkai/4081330/index.html", "official"),
    ("NDRC", "https://www.ndrc.gov.cn/xxgk/zcfb/", "official"),
    ("MOF", "http://www.mof.gov.cn/zhengwuxinxi/zhengcefabu/", "official"),
]

DEFAULT_FRED_SERIES: list[tuple[str, str]] = [
    ("DFF", "美国联邦基金有效利率"),
    ("CPIAUCSL", "美国 CPI 月环比"),
    ("UNRATE", "美国失业率"),
]


def build_default_adapters(
    *,
    client,
    fetch_cls_roll_list,
    fetch_announcements,
    brief_type: str = "post_market",
    sector_snapshot: dict | None = None,
) -> list:
    """Build the configured production market-evidence adapter list."""
    adapters: list = []
    if brief_type == "pre_market":
        adapters.extend(
            FredSeriesAdapter(series_id=series_id, title=title)
            for series_id, title in DEFAULT_FRED_SERIES
        )
        adapters.extend(
            PolicyPageAdapter(
                source=name,
                url=url,
                reliability=reliability,
            )
            for name, url, reliability in DEFAULT_POLICY_ADAPTERS
        )
    else:
        adapters.extend(
            PolicyPageAdapter(
                source=name,
                url=url,
                reliability=reliability,
            )
            for name, url, reliability in DEFAULT_POLICY_ADAPTERS
        )
        adapters.append(CninfoAnnouncementAdapter(
            fetch_announcements=fetch_announcements,
        ))
        adapters.extend(
            FredSeriesAdapter(series_id=series_id, title=title)
            for series_id, title in DEFAULT_FRED_SERIES
        )
        if sector_snapshot is not None:
            adapters.append(SectorHeatAdapter(sector_snapshot=sector_snapshot))
        try:
            settings = get_settings()
            if settings.cls_enabled:
                adapters.append(ClsTelegraphAdapter(
                    fetch_roll_list=fetch_cls_roll_list,
                    client=client,
                    categories=settings.cls_categories,
                    per_category_limit=settings.cls_per_category_limit,
                    timeout_seconds=settings.cls_timeout_seconds,
                    app_version=settings.cls_app_version,
                    max_attempts=int(getattr(settings, "cls_max_attempts", 1)),
                    retry_base_seconds=float(
                        getattr(settings, "cls_retry_base_seconds", 1.0)
                    ),
                ))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "CLS adapter disabled due to configuration error: %s",
                exc,
                exc_info=True,
            )
    return adapters


__all__ = [
    "build_default_adapters",
    "DEFAULT_POLICY_ADAPTERS",
    "DEFAULT_FRED_SERIES",
]
