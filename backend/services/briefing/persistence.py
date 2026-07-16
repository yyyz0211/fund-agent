"""Briefing persistence: 简报读写用例."""
from __future__ import annotations

import json

from sqlalchemy import select

from backend.db.models import Briefing
from backend.db.repositories import briefing as briefing_repository
from backend.db.session_scope import session_scope


def persist_briefing(
    session,
    *,
    briefing_date: str,
    payload: dict,
    brief_type: str = "post_market",
) -> Briefing:
    """Delegate a briefing upsert to the flush-only repository."""
    return briefing_repository.upsert_briefing(
        session,
        briefing_date=briefing_date,
        payload=payload,
        brief_type=brief_type,
    )


def read_briefing(brief_date: str | None = None, brief_type: str = "post_market") -> dict | None:
    """从 DB 读取 briefing（None=最近），返回 dict（含新 data_quality 字段）。

    brief_type: 按 type 过滤；None 表示不限定。

    Phase 1.2: 顶层事务 — 自动 commit/rollback/close via `session_scope()`。
    不带 session 参数的纯读接口。
    """
    with session_scope() as s:
        if brief_date:
            stmt = select(Briefing).where(Briefing.briefing_date == brief_date)
            if brief_type:
                stmt = stmt.where(Briefing.brief_type == brief_type)
            row = s.scalar(stmt)
        else:
            stmt = select(Briefing)
            if brief_type:
                stmt = stmt.where(Briefing.brief_type == brief_type)
            row = s.scalar(stmt.order_by(Briefing.briefing_date.desc()))
        if row is None:
            return None
        sections = {}
        try:
            sections = json.loads(row.sections_json) if row.sections_json else {}
        except Exception:
            pass
        missing_data: list[str] = []
        failed_modules: list[dict] = []
        data_sources_last_updated: dict = {}
        if row.missing_data_json:
            try:
                parsed = json.loads(row.missing_data_json)
                if isinstance(parsed, list):
                    missing_data = [str(x) for x in parsed]
            except Exception:
                pass
        # 从 sections_json 中提取 failed_modules 和 data_sources_last_updated
        # V2: 在 sections.modules.data_statement 中；legacy: 在 sections.data_statement 中
        v2_ds = (sections.get("modules") or {}).get("data_statement") or {}
        legacy_ds = sections.get("data_statement") or {}
        ds = v2_ds.get("content", v2_ds) or legacy_ds
        if ds:
            failed_modules = ds.get("failed_modules", []) or []
            data_sources_last_updated = ds.get("data_sources_last_updated", {}) or {}
        return {
            "id": row.id,
            "briefing_date": row.briefing_date,
            "brief_type": getattr(row, "brief_type", "post_market"),
            "title": row.title,
            "markdown": row.markdown,
            "sections": sections,
            "source": row.source,
            "as_of": row.as_of,
            "data_quality": row.data_quality,
            "confidence": row.confidence,
            "missing_data": missing_data,
            "evidence_count": row.evidence_count,
            "failed_modules": failed_modules,
            "data_sources_last_updated": data_sources_last_updated,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


__all__ = ["persist_briefing", "read_briefing"]
