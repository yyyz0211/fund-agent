"""每日基金简报路由。

- GET  /api/briefing/latest       最近一篇
- GET  /api/briefing/list?limit=N 按日期降序列表
- POST /api/briefing/run          本地触发,仅当请求携带 `X-Local-Trigger` 时通过

简报数据完全本地化,不查询策略(policy.py);后端信任前端页面与本地进程。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from backend.db.models import Briefing
from backend.db.session import get_session
from backend.services import briefing_service
from sqlalchemy import select


router = APIRouter(prefix="/api/briefing", tags=["briefing"])


def _briefing_to_dict(row: Briefing) -> dict:
    sections = {}
    try:
        sections = json.loads(row.sections_json) if row.sections_json else {}
    except (json.JSONDecodeError, TypeError):
        sections = {}
    return {
        "id": row.id,
        "briefing_date": row.briefing_date,
        "title": row.title,
        "markdown": row.markdown,
        "sections": sections,
        "source": row.source,
        "as_of": row.as_of,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _briefing_summary(row: Briefing) -> dict:
    return {
        "id": row.id,
        "briefing_date": row.briefing_date,
        "title": row.title,
        "as_of": row.as_of,
    }


@router.get("/latest")
def get_latest_briefing(session: Session = Depends(get_session)) -> dict:
    """返回最近一篇简报;无则返回 {briefing: null}。"""
    row = session.scalar(select(Briefing).order_by(Briefing.briefing_date.desc()).limit(1))
    if row is None:
        return {"briefing": None}
    return {"briefing": _briefing_to_dict(row)}


@router.get("/list")
def list_briefings(limit: int = Query(default=30, ge=1, le=200),
                   session: Session = Depends(get_session)) -> dict:
    """按 briefing_date 降序返回最近 N 篇概要。"""
    rows = session.scalars(
        select(Briefing).order_by(Briefing.briefing_date.desc()).limit(limit)
    ).all()
    return {
        "briefings": [_briefing_summary(r) for r in rows],
        "limit": limit,
    }


@router.post("/run", status_code=202)
def run_now(x_local_trigger: str | None = Header(default=None)) -> dict:
    """本地触发:必须带 `X-Local-Trigger=1`(或 true)。不带返回 403。

    这条端点供前端 `/briefing` 页"立即生成今日简报"按钮调用;
    部署对外暴露时可通过反向代理禁掉 `/api/briefing/run`。
    """
    if not x_local_trigger or x_local_trigger.lower() not in ("1", "true"):
        raise HTTPException(status_code=403, detail="missing X-Local-Trigger header")
    return briefing_service.start_run_async(trigger="manual")