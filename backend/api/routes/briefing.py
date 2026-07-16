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

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.db.models import Briefing, BriefingFeedback
from backend.db.session_scope import session_scope
from backend.services.briefing import jobs as briefing_jobs


router = APIRouter(prefix="/api/briefing", tags=["briefing"])


def _extract_data_statement(sections: dict) -> dict:
    """从 sections JSON 中提取 data_statement 内容（兼容 V2 modules.* 和 legacy 平铺）。"""
    v2_ds = (sections.get("modules") or {}).get("data_statement") or {}
    legacy_ds = sections.get("data_statement") or {}
    return v2_ds.get("content", v2_ds) or legacy_ds or {}


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
    ds = _extract_data_statement(sections)
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
        "failed_modules": ds.get("failed_modules", []) or [],
        "data_sources_last_updated": ds.get("data_sources_last_updated", {}) or {},
        "evidence_count": row.evidence_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _briefing_summary(row: Briefing) -> dict:
    return {
        "id": row.id,
        "briefing_date": row.briefing_date,
        "brief_type": getattr(row, "brief_type", "post_market"),
        "title": row.title,
        "as_of": row.as_of,
        "data_quality": row.data_quality,
        "evidence_count": row.evidence_count,
    }


@router.get("/latest")
def get_latest_briefing(
    type: str | None = Query(default=None, alias="type", description="按 brief_type 过滤"),
    session: Session = Depends(get_db_session),
) -> dict:
    """返回最近一篇简报;无则返回 {briefing: null}。

    type: 可选 brief_type(post_market / pre_market / intraday)。未传则按
    briefing_date 降序返回最近一篇(保持向后兼容)。
    """
    stmt = select(Briefing)
    if type:
        stmt = stmt.where(Briefing.brief_type == type)
    row = session.scalar(stmt.order_by(Briefing.briefing_date.desc()).limit(1))
    if row is None:
        return {"briefing": None}
    return {"briefing": _briefing_to_dict(row)}


@router.get("/list")
def list_briefings(
    limit: int = Query(default=30, ge=1, le=200),
    type: str | None = Query(default=None, alias="type", description="按 brief_type 过滤"),
    session: Session = Depends(get_db_session),
) -> dict:
    """按 briefing_date 降序返回最近 N 篇概要。"""
    stmt = select(Briefing).order_by(Briefing.briefing_date.desc()).limit(limit)
    if type:
        stmt = stmt.where(Briefing.brief_type == type)
    rows = session.scalars(stmt).all()
    return {
        "briefings": [_briefing_summary(r) for r in rows],
        "limit": limit,
        "brief_type": type,
    }


class RunPayload(BaseModel):
    """手动触发简报请求体。"""
    brief_type: str = Field(default="post_market", max_length=32)


@router.post("/run", status_code=202)
def run_now(
    payload: RunPayload | None = Body(default=None),
    type: str | None = Query(default=None, alias="type", description="brief_type,默认 post_market"),
    x_local_trigger: str | None = Header(default=None),
) -> dict:
    """本地触发:必须带 `X-Local-Trigger=1`(或 true)。不带返回 403。

    这条端点供前端 `/briefing` 页"立即生成今日简报"按钮调用;
    部署对外暴露时可通过反向代理禁掉 `/api/briefing/run`。

    type: 可选 brief_type。未传则使用 post_market（向后兼容）。
    """
    if not x_local_trigger or x_local_trigger.lower() not in ("1", "true"):
        raise HTTPException(status_code=403, detail="missing X-Local-Trigger header")
    brief_type = (payload.brief_type if payload is not None else None) or type or "post_market"
    # Phase 1.1: 显式构造 model 注入 service,而不是让 service lazy import graph.model。
    # 失败时 model 构造抛 RuntimeError,FastAPI handler 转成 503 让前端区分"系统问题"。
    try:
        from backend.graph.model import build_model
        model = build_model()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"briefing_model_unavailable: {exc}")
    return briefing_jobs.start_run_async(
        trigger="manual",
        brief_type=brief_type,
        model=model,
    )


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
def submit_feedback(payload: FeedbackPayload) -> dict:
    """提交简报反馈。同一 (briefing_id, user_id) 重复提交时更新现有记录。"""
    with session_scope() as s:
        briefing = s.get(Briefing, payload.briefing_id)
        if briefing is None:
            raise HTTPException(status_code=404, detail=f"briefing {payload.briefing_id} not found")

        existing = s.scalar(
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
            s.add(existing)

        existing.risk_accuracy = payload.risk_accuracy
        existing.theme_accuracy = payload.theme_accuracy
        existing.evidence_quality = payload.evidence_quality
        existing.overall_satisfaction = payload.overall_satisfaction
        existing.comment = payload.comment
        existing.feedback_meta_json = json.dumps(payload.feedback_meta, ensure_ascii=False)
        s.flush()
        s.refresh(existing)

        return {
            "id": existing.id,
            "briefing_id": existing.briefing_id,
            "user_id": existing.user_id,
            "created_at": existing.created_at.isoformat() if existing.created_at else None,
        }


@router.get("/feedback/{briefing_id}")
def list_feedback(briefing_id: int, session: Session = Depends(get_db_session)) -> dict:
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
