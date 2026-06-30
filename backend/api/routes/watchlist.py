"""自选池路由（只读）。

本阶段不暴露写操作：增删改走 CLI 脚本（参见
`backend/scripts/smoke_fetch.py`）。
"""
from fastapi import APIRouter

from backend.services import watchlist_service as ws

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("")
def list_watchlist() -> list[dict]:
    return ws.list_watchlist()
