"""每日基金简报路由。

- GET  /api/briefing/latest       最近一篇
- GET  /api/briefing/list?limit=N 按日期降序列表
- POST /api/briefing/run          本地触发,仅当请求携带 `X-Local-Trigger` 时通过
- POST /api/briefing/feedback     提交用户反馈（用于评估简报质量）

简报数据完全本地化,不查询策略(policy.py);后端信任前端页面与本地进程。
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Briefing, BriefingFeedback
from backend.db.session import get_session
from backend.services import briefing_service


router = APIRouter(prefix="/api/briefing", tags=["briefing"])


def _briefing_to_dict(row: Briefing) -> dict:
    sections = {}
    try:
        sections = json.loads(row.sections_json) if row.sections_json else {}
    except (json.JSONDecodeError, TypeError):
        sections = {}
    missing_data: list[str] = []
    if row.missing_data_json:
        try:
            parsed = json.loads(row.missing_data_json)
            if isinstance(parsed, list):
                missing_data = [str(x) for x in parsed]
        except (json.JSONDecodeError, TypeError):
            missing_data = []
    return {
        "id": row.id,
        "briefing_date": row.briefing_date,
        "title": row.title,
        "markdown": row.markdown,
        "sections": sections,
        "source": row.source,
        "as_of": row.as_of,
        "data_quality": row.data_quality,
        "confidence": row.confidence,
        "missing_data": missing_data,
        "evidence_count": row.evidence_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _briefing_summary(row: Briefing) -> dict:
    return {
        "id": row.id,
        "briefing_date": row.briefing_date,
        "title": row.title,
        "as_of": row.as_of,
        "data_quality": row.data_quality,
        "evidence_count": row.evidence_count,
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


# ---------------------------------------------------------------------------
# User Feedback (Phase 5)
# ---------------------------------------------------------------------------

class FeedbackPayload(BaseModel):
    """用户反馈请求体。"""
    briefing_id: int = Field(..., description="目标简报 ID")
    user_id: str = Field(default="default", max_length=64)
    risk_accuracy: int | None = Field(default=None, ge=1, le=5)
    theme_accuracy: int | None = Field(default=None, ge=1, le=5)
    evidence_quality: int | None = Field(default=None, ge=1, le=5)
    overall_satisfaction: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    feedback_meta: dict = Field(default_factory=dict)


@router.post("/feedback", status_code=201)
def submit_feedback(payload: FeedbackPayload, session: Session = Depends(get_session)) -> dict:
    """提交简报反馈。同一 (briefing_id, user_id) 重复提交时更新现有记录。"""
    briefing = session.get(Briefing, payload.briefing_id)
    if briefing is None:
        raise HTTPException(status_code=404, detail=f"briefing {payload.briefing_id} not found")

    existing = session.scalar(
        select(BriefingFeedback).where(
            BriefingFeedback.briefing_id == payload.briefing_id,
            BriefingFeedback.user_id == payload.user_id,
        )
    )
    if existing is None:
        existing = BriefingFeedback(
            briefing_id=payload.briefing_id,
            user_id=payload.user_id,
        )
        session.add(existing)

    existing.risk_accuracy = payload.risk_accuracy
    existing.theme_accuracy = payload.theme_accuracy
    existing.evidence_quality = payload.evidence_quality
    existing.overall_satisfaction = payload.overall_satisfaction
    existing.comment = payload.comment
    existing.feedback_meta_json = json.dumps(payload.feedback_meta, ensure_ascii=False)
    session.commit()
    session.refresh(existing)

    return {
        "id": existing.id,
        "briefing_id": existing.briefing_id,
        "user_id": existing.user_id,
        "created_at": existing.created_at.isoformat() if existing.created_at else None,
    }


@router.get("/feedback/{briefing_id}")
def list_feedback(briefing_id: int, session: Session = Depends(get_session)) -> dict:
    """查询指定简报的所有用户反馈。"""
    rows = session.scalars(
        select(BriefingFeedback).where(BriefingFeedback.briefing_id == briefing_id)
    ).all()
    return {
        "briefing_id": briefing_id,
        "feedbacks": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "risk_accuracy": r.risk_accuracy,
                "theme_accuracy": r.theme_accuracy,
                "evidence_quality": r.evidence_quality,
                "overall_satisfaction": r.overall_satisfaction,
                "comment": r.comment,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }