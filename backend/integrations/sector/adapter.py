"""Market sector snapshots to market-evidence rows."""
from __future__ import annotations


class SectorHeatAdapter:
    """Map the strongest and weakest industry sectors to evidence."""

    source_name = "akshare"
    reliability = "wire"
    category = "sector"
    base_url = "http://quote.eastmoney.com/center/gridlist.html"

    def __init__(self, *, sector_snapshot: dict, top_n: int = 3):
        self.sector_snapshot = sector_snapshot or {}
        self.top_n = max(1, int(top_n))

    def fetch(
        self,
        *,
        client=None,
        trade_date: str,
        brief_type: str = "post_market",
    ) -> list[dict]:
        rows = self.sector_snapshot.get("industry_sectors") or []
        if not rows:
            return []
        try:
            sorted_rows = sorted(
                (row for row in rows if isinstance(row, dict)),
                key=lambda row: float(row.get("change_pct") or 0),
            )
        except (TypeError, ValueError):
            return []
        top = sorted_rows[-self.top_n:]
        bottom = sorted_rows[: self.top_n]
        out: list[dict] = []
        for label, group in (("强势", top), ("弱势", bottom)):
            for row in group:
                name = row.get("name")
                change_pct = row.get("change_pct")
                if name is None or change_pct is None:
                    continue
                try:
                    change_pct_float = float(change_pct)
                except (TypeError, ValueError):
                    continue
                out.append({
                    "trade_date": trade_date,
                    "brief_type": brief_type,
                    "category": self.category,
                    "source": self.source_name,
                    "source_url": self.base_url,
                    "title": (
                        f"行业板块 {label}: {name} {change_pct_float:+.2f}%"
                    ),
                    "summary": f"{name} 当日涨跌幅 {change_pct_float:+.2f}%",
                    "symbols": [name],
                    "metrics": {"change_pct": change_pct_float},
                    "published_at": trade_date,
                    "reliability": self.reliability,
                })
        return out
