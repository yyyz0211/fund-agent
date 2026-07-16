"""Market repository: 市场快照、市场证据相关持久化。"""
from __future__ import annotations

from sqlalchemy import and_, or_, select

from backend.db.models import MarketEvidence, MarketSnapshot


def upsert_market_snapshot(
    s,
    trade_date: str,
    snapshot_type: str,
    payload: dict,
) -> MarketSnapshot:
    """upsert market_snapshots 表，返回行。payload keys 对应模型 JSON 列。"""
    import json as _json

    json_keys = (
        "indices_json", "breadth_json", "industry_sectors_json",
        "concept_sectors_json", "industry_flows_json", "concept_flows_json",
        "themes_json", "breadth_indicators_json", "overseas_json",
        "announcements_json",
    )
    values = {"trade_date": trade_date, "snapshot_type": snapshot_type, "source": "akshare"}
    for key in json_keys:
        val = payload.get(key.replace("_json", ""))
        if isinstance(val, (list, dict)):
            values[key] = _json.dumps(val, ensure_ascii=False)
        else:
            values[key] = _json.dumps(val or [])
    values["as_of"] = payload.get("as_of", trade_date)

    row = s.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.trade_date == trade_date,
            MarketSnapshot.snapshot_type == snapshot_type,
        )
    )
    if row is None:
        row = MarketSnapshot(**values)
        s.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
    s.flush()
    return row


# ---------------------------------------------------------------------------
# MarketEvidence
# ---------------------------------------------------------------------------

def _evidence_to_dict(row: MarketEvidence) -> dict:
    """MarketEvidence 的可序列化投影。"""
    import json as _json
    symbols: list = []
    metrics: dict | None = None
    if row.symbols_json:
        try:
            parsed = _json.loads(row.symbols_json)
            if isinstance(parsed, list):
                symbols = parsed
        except (TypeError, ValueError):
            symbols = []
    if row.metrics_json:
        try:
            parsed = _json.loads(row.metrics_json)
            if isinstance(parsed, dict):
                metrics = parsed
        except (TypeError, ValueError):
            metrics = None
    return {
        "id": row.id,
        "trade_date": row.trade_date,
        "brief_type": row.brief_type,
        "category": row.category,
        "title": row.title,
        "summary": row.summary,
        "symbols": symbols,
        "metrics": metrics,
        "source": row.source,
        "source_url": row.source_url,
        "published_at": row.published_at,
        "reliability": row.reliability,
    }


def upsert_market_evidence(s, row: dict) -> bool:
    """按 `(trade_date, brief_type, source_url)` 去重插入。

    返回 True 表示新建，False 表示已存在。
    """
    import hashlib
    import json as _json
    from datetime import datetime

    symbols = row.get("symbols") or []
    metrics = row.get("metrics")
    if not isinstance(symbols, list):
        symbols = [str(symbols)]
    raw_hash = hashlib.sha256(
        f"{row['source_url']}|{row['title']}".encode()
    ).hexdigest()[:32]
    now = datetime.utcnow()
    payload = {
        "trade_date": row["trade_date"],
        "brief_type": row["brief_type"],
        "category": row["category"],
        "title": row["title"],
        "summary": row.get("summary"),
        "symbols_json": _json.dumps(symbols, ensure_ascii=False) if symbols else None,
        "metrics_json": _json.dumps(metrics, ensure_ascii=False) if metrics else None,
        "source": row.get("source") or "unknown",
        "source_url": row["source_url"],
        "published_at": row.get("published_at"),
        "reliability": row.get("reliability") or "official",
        "raw_hash": raw_hash,
        "fetched_at": now,
        "created_at": now,
        "updated_at": now,
    }
    existing = s.scalar(
        select(MarketEvidence).where(
            or_(
                and_(
                    MarketEvidence.trade_date == payload["trade_date"],
                    MarketEvidence.brief_type == payload["brief_type"],
                    MarketEvidence.source_url == payload["source_url"],
                ),
                MarketEvidence.raw_hash == payload["raw_hash"],
            )
        )
    )
    if existing is not None:
        return False
    s.add(MarketEvidence(**payload))
    s.flush()
    return True


def search_market_evidence(
    s,
    *,
    trade_date: str,
    category: str | None = None,
    query: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """按日期 / 类别 / 关键词查询 evidence；按 id 倒序（新→旧）。

    - `query` 为空字符串或 None 时不过滤关键词。
    - `category` 为空字符串或 None 时不过滤类别。
    - 结果以 `_evidence_to_dict` 投影返回。
    """
    stmt = select(MarketEvidence).where(MarketEvidence.trade_date == trade_date)
    if category:
        stmt = stmt.where(MarketEvidence.category == category)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            (MarketEvidence.title.like(like)) | (MarketEvidence.summary.like(like))
        )
    stmt = stmt.order_by(MarketEvidence.id.desc()).limit(max(1, int(limit)))
    rows = s.scalars(stmt).all()
    return [_evidence_to_dict(r) for r in rows]


__all__ = [
    "upsert_market_snapshot",
    "upsert_market_evidence",
    "search_market_evidence",
]
