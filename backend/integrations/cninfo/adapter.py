"""Announcement collector rows to market-evidence rows."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


FetchAnnouncements = Callable[..., list[dict[str, Any]]]


class CninfoAnnouncementAdapter:
    source_name = "akshare/eastmoney"
    reliability = "wire"
    category = "announcement"
    base_url = "https://fundf10.eastmoney.com/jjgg.html"

    def __init__(
        self,
        *,
        fetch_announcements: FetchAnnouncements,
        limit: int = 20,
    ):
        self._fetch_announcements = fetch_announcements
        self.limit = max(1, int(limit))

    def fetch(
        self,
        *,
        client=None,
        trade_date: str,
        brief_type: str = "post_market",
    ) -> list[dict]:
        """Fetch announcements and normalize them without leaking failures."""
        try:
            rows = self._fetch_announcements(limit=self.limit)
        except Exception:
            return []
        out: list[dict] = []
        for row in rows or []:
            title = row.get("title")
            if not title:
                continue
            ann_date = row.get("ann_date") or trade_date
            fund_code = row.get("fund_code") or ""
            source_url = (
                f"https://fundf10.eastmoney.com/jjgg_{fund_code}_{ann_date}.html"
                if fund_code and ann_date
                else self.base_url
            )
            symbols = [
                symbol
                for symbol in (row.get("fund_name"), fund_code)
                if symbol
            ]
            out.append({
                "trade_date": trade_date,
                "brief_type": brief_type,
                "category": self.category,
                "source": self.source_name,
                "source_url": source_url,
                "title": title,
                "summary": (
                    f"{row.get('fund_name') or fund_code or '基金'} - {ann_date}"
                ),
                "symbols": symbols,
                "metrics": None,
                "published_at": ann_date,
                "reliability": self.reliability,
            })
            if len(out) >= self.limit:
                break
        return out
