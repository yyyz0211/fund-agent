"""市场证据服务。

职责:
- 归一化外部证据为 `market_evidence` 行
- 通过 title/summary/symbols 做轻量关键词搜索
- 返回可直接给 QA/简报使用的 dict,包含 source/source_url/as_of
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from backend.db import repository as repo
from backend.db.session import get_session


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stable_hash(payload: dict) -> str:
    if payload.get("raw_hash"):
        return str(payload["raw_hash"])
    seed = payload.get("source_url") or "|".join(
        str(payload.get(key) or "")
        for key in ("category", "title", "published_at", "source")
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _json_dumps(value, fallback) -> str:
    if value is None:
        value = fallback
    return json.dumps(value, ensure_ascii=False)


def _normalize(payload: dict) -> dict:
    category = str(payload.get("category") or "news")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    return {
        "trade_date": payload.get("trade_date"),
        "brief_type": payload.get("brief_type"),
        "category": category,
        "title": title,
        "summary": payload.get("summary"),
        "symbols_json": _json_dumps(payload.get("symbols"), []),
        "metrics_json": _json_dumps(payload.get("metrics"), {}),
        "source": payload.get("source"),
        "source_url": payload.get("source_url"),
        "published_at": payload.get("published_at"),
        "collected_at": payload.get("collected_at") or _now_iso(),
        "reliability": payload.get("reliability") or "unknown",
        "raw_excerpt": payload.get("raw_excerpt"),
        "raw_hash": _stable_hash(payload),
    }


def upsert_evidence(payload: dict, *, session=None) -> dict:
    """写入或更新一条市场证据。"""
    owns = session is None
    s = session or get_session()
    try:
        return repo.upsert_market_evidence(s, _normalize(payload or {}))
    finally:
        if owns:
            s.close()


def search_evidence(
    query: str,
    *,
    trade_date: str = "",
    category: str = "",
    limit: int = 5,
    session=None,
) -> list[dict]:
    """搜索市场证据。无结果时返回空列表,不抛异常。"""
    owns = session is None
    s = session or get_session()
    try:
        return repo.search_market_evidence(
            s,
            query=(query or "").strip(),
            trade_date=trade_date or "",
            category=category or "",
            limit=limit,
        )
    finally:
        if owns:
            s.close()
