"""CninfoAnnouncementAdapter: 把 data_collector 拉到的基金分红公告包装成 evidence。

第一轮保守实现: 不直连巨潮 (cninfo) 搜索接口, 而是复用 `data_collector.fetch_announcements`
的输出 + 补一个东方财富 detail 页 URL 作为可追溯来源。

后续可替换为巨潮直连。
"""
from __future__ import annotations

from backend.services.data_collector import fetch_announcements


class CninfoAnnouncementAdapter:
    source_name = "akshare/eastmoney"
    reliability = "wire"
    category = "announcement"
    base_url = "https://fundf10.eastmoney.com/jjgg.html"

    def __init__(self, *, limit: int = 20):
        self.limit = max(1, int(limit))

    def fetch(self, *, client=None, trade_date: str, brief_type: str = "post_market") -> list[dict]:
        """拉取公告并转 evidence。`client` 参数保留以与统一契约对齐, 实际不使用。"""
        try:
            rows = fetch_announcements(limit=self.limit)
        except Exception:
            return []
        out: list[dict] = []
        for r in rows or []:
            title = r.get("title")
            if not title:
                continue
            ann_date = r.get("ann_date") or trade_date
            fund_code = r.get("fund_code") or ""
            source_url = (
                f"https://fundf10.eastmoney.com/jjgg_{fund_code}_{ann_date}.html"
                if fund_code and ann_date
                else self.base_url
            )
            symbols = [s for s in (r.get("fund_name"), fund_code) if s]
            out.append({
                "trade_date": trade_date,
                "brief_type": brief_type,
                "category": self.category,
                "source": self.source_name,
                "source_url": source_url,
                "title": title,
                "summary": f"{r.get('fund_name') or fund_code or '基金'} - {ann_date}",
                "symbols": symbols,
                "metrics": None,
                "published_at": ann_date,
                "reliability": self.reliability,
            })
            if len(out) >= self.limit:
                break
        return out