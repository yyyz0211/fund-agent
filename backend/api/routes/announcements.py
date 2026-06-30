"""公告路由（阶段 2 占位）。

RAG 检索将在阶段 5 接入；本阶段只返回空列表与说明。前端在
`/announcements` 页面用此响应做 empty state 提示。
"""
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


@router.get("")
def list_announcements(fund_code: str = Query(default=""),
                       limit: int = Query(default=20, ge=1, le=100)) -> dict:
    return {
        "announcements": [],
        "note": "公告 RAG 检索将在阶段 5 接入；当前为空列表。",
        "fund_code": fund_code,
        "limit": limit,
    }
