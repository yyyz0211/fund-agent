"""Briefing repository: 简报相关持久化。"""
from __future__ import annotations

from sqlalchemy import select

from backend.db.models import Briefing


def upsert_briefing(
    session,
    briefing_date: str,
    payload: dict,
    brief_type: str = "post_market",
) -> Briefing:
    """按 (briefing_date, brief_type) 联合唯一键 upsert 简报;payload 的字段写入 Briefing 各列。"""
    row = session.scalar(
        select(Briefing).where(
            Briefing.briefing_date == briefing_date,
            Briefing.brief_type == brief_type,
        )
    )
    # payload 显式携带 brief_type 时覆盖入参；否则用入参
    payload_eff = {**payload}
    payload_eff.setdefault("brief_type", brief_type)
    if row is None:
        row = Briefing(briefing_date=briefing_date, **payload_eff)
        session.add(row)
    else:
        for key, value in payload_eff.items():
            if hasattr(row, key):
                setattr(row, key, value)
    session.flush()
    return row


__all__ = ["upsert_briefing"]
