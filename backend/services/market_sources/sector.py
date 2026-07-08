"""SectorHeatAdapter: 把当日 MarketSnapshot.industry_sectors 转成 sector 类 evidence。

不发起外部请求, 直接消费 ingestion 阶段拿到的行情数据, 当作 "市场热点" 的次级证据。
"""
from __future__ import annotations


class SectorHeatAdapter:
    """把 top3 / bottom3 行业板块涨跌写入 sector 类别 evidence。"""

    source_name = "akshare"
    reliability = "wire"
    category = "sector"
    base_url = "http://quote.eastmoney.com/center/gridlist.html"

    def __init__(self, *, sector_snapshot: dict, top_n: int = 3):
        # sector_snapshot: dict with key 'industry_sectors': [{"name":..., "change_pct":...}, ...]
        self.sector_snapshot = sector_snapshot or {}
        self.top_n = max(1, int(top_n))

    def fetch(self, *, client=None, trade_date: str, brief_type: str = "post_market") -> list[dict]:
        rows = self.sector_snapshot.get("industry_sectors") or []
        if not rows:
            return []
        # 按涨跌幅排序
        try:
            sorted_rows = sorted(
                (r for r in rows if isinstance(r, dict)),
                key=lambda r: float(r.get("change_pct") or 0),
            )
        except (TypeError, ValueError):
            return []
        top = sorted_rows[-self.top_n:]
        bottom = sorted_rows[: self.top_n]
        out: list[dict] = []
        for label, group in (("强势", top), ("弱势", bottom)):
            for r in group:
                name = r.get("name")
                pct = r.get("change_pct")
                if name is None or pct is None:
                    continue
                try:
                    pct_f = float(pct)
                except (TypeError, ValueError):
                    continue
                out.append({
                    "trade_date": trade_date,
                    "brief_type": brief_type,
                    "category": self.category,
                    "source": self.source_name,
                    "source_url": self.base_url,
                    "title": f"行业板块 {label}: {name} {pct_f:+.2f}%",
                    "summary": f"{name} 当日涨跌幅 {pct_f:+.2f}%",
                    "symbols": [name],
                    "metrics": {"change_pct": pct_f},
                    "published_at": trade_date,
                    "reliability": self.reliability,
                })
        return out