"""FastAPI 应用入口。

只做最小骨架：注册 CORS、五个业务 router、健康检查端点。
业务由 `routes/` 拆分，本文件不应承载任何业务函数。
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import funds as funds_routes
from backend.api.routes import market as market_routes
from backend.api.routes import watchlist as watchlist_routes
from backend.api.routes import announcements as announcements_routes
from backend.api.routes import portfolio as portfolio_routes
from backend.api.routes import admin as admin_routes
from backend.api.routes import briefing as briefing_routes

app = FastAPI(title="Fund Agent API", version="0.1.0")

# CORS 白名单从环境变量 ALLOWED_ORIGINS 读,逗号分隔。
# 本地开发默认 http://localhost:3000;部署时通过 .env / docker-compose 注入 Tailscale IP。
# 空字符串 / 没设 → fallback 到 localhost,保证本地启动可用。
_allowed = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
allow_origins = [o.strip() for o in _allowed.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    # 自选池的 POST/PATCH/DELETE 走浏览器预检,必须显式放行;
    # OPTIONS 留给浏览器自动处理(不在这里列出,FastAPI 也能响应)。
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_schema() -> None:
    """进程启动时把 ORM 表建齐 + 给老表补列,并启动定时刷新调度器。

    生产级项目会用 alembic,本项目当前没引入迁移工具,这里
    `init_db` 自带"反射 → 缺列 ALTER"逻辑,幂等可重复跑。

    调度器随进程启动;`SCHEDULER_ENABLED=false`(测试/CI)时 `start_scheduler`
    直接返回 None,不起后台线程。
    """
    from backend.db.init_db import init_db
    from backend import scheduler as app_scheduler

    init_db()
    app_scheduler.start_scheduler()


@app.on_event("shutdown")
def _stop_scheduler() -> None:
    """进程退出时停止调度器,避免后台线程泄漏。"""
    from backend import scheduler as app_scheduler

    app_scheduler.shutdown_scheduler()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


def add_routers(app: FastAPI) -> None:
    app.include_router(funds_routes.router)
    app.include_router(watchlist_routes.router)
    app.include_router(market_routes.router)
    app.include_router(announcements_routes.router)
    app.include_router(portfolio_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(briefing_routes.router)


add_routers(app)
