"""管理端点:定时刷新状态查询 + 手动全量触发。

当前无鉴权,与项目其余 API 一致,信任模型依赖部署侧的 Tailscale 网络边界
(见 DOCKER.md)。`/api/admin/*` 前缀便于将来统一加保护。
"""
from fastapi import APIRouter

from backend.services.market import scheduled_refresh as sr

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/refresh-status")
def refresh_status() -> dict:
    """返回最近一次批量刷新的内存快照;从未跑过时返回全零快照。"""
    return sr.get_last_run()


@router.post("/refresh-all", status_code=202)
def refresh_all() -> dict:
    """在后台线程触发一次全量刷新,立即返回 {status, total}。"""
    return sr.start_refresh_all_async(trigger="manual")
