"""财联社信息源路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.services.knowledge import cls_telegraph_sync_service


router = APIRouter(prefix="/api/cls", tags=["cls"])


@router.get("/telegraph")
def get_cls_telegraph(
    limit: int = Query(default=50, ge=1, le=200),
    category: str | None = Query(default=None),
    since_id: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
):
    rows = cls_telegraph_sync_service.list_cls_telegraph_items(
        session=session,
        limit=limit,
        category=category,
        since_id=since_id,
        keyword=keyword,
    )
    return {"count": len(rows), "items": rows}


@router.get("/telegraph/sync/status")
def get_cls_telegraph_sync_status(session: Session = Depends(get_db_session)):
    return cls_telegraph_sync_service.get_cls_telegraph_sync_status(session=session)
