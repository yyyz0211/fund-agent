"""FastAPI 应用入口。

只做最小骨架：注册 CORS、五个业务 router、健康检查端点。
业务由 `routes/` 拆分，本文件不应承载任何业务函数。
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import funds as funds_routes
from backend.api.routes import market as market_routes
from backend.api.routes import watchlist as watchlist_routes
from backend.api.routes import announcements as announcements_routes
from backend.api.routes import portfolio as portfolio_routes
from backend.api.routes import admin as admin_routes
from backend.api.routes import briefing as briefing_routes
from backend.api.routes import cls as cls_routes
from backend.api.routes import knowledge as knowledge_routes
from backend.config.settings import get_settings

app = FastAPI(title="Fund Agent API", version="0.1.0")

# CORS 白名单从 Settings.allowed_origins 读取，支持逗号分隔的字符串或列表
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    # 自选池的 POST/PATCH/DELETE 走浏览器预检,必须显式放行;
    # OPTIONS 留给浏览器自动处理(不在这里列出,FastAPI 也能响应)。
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_schema() -> None:
    """进程启动时运行 Alembic 迁移。

    Alembic 是 schema 的唯一权威。PostgreSQL 单一化后，不再使用 create_all。
    """
    import logging
    import subprocess
    import sys

    from backend import scheduler as app_scheduler
    from backend.config.settings import get_settings
    from backend.db.init_db import init_db, MigrationError
    from backend.services import knowledge_reindex_jobs

    logger = logging.getLogger(__name__)

    # 运行 Alembic 迁移
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd="/Users/leon/fund-agent",
        )
        if result.returncode == 0:
            logger.info("[startup] Alembic migrations applied successfully")
        else:
            raise RuntimeError(f"Alembic failed: {result.stderr}")
    except Exception as alembic_exc:
        logger.error("[startup] Alembic migration failed: %s", alembic_exc)
        logger.error("[startup] Application cannot start without valid schema.")
        raise SystemExit(1) from alembic_exc

    # 恢复中断的 jobs
    settings = get_settings()
    try:
        recovered = knowledge_reindex_jobs.recover_interrupted_jobs(
            settings.knowledge_job_stale_seconds,
        )
        if recovered > 0:
            logger.info(
                "[startup] recovered %d interrupted knowledge reindex jobs",
                recovered,
            )
    except Exception:
        logger.exception("[startup] failed to recover interrupted jobs (non-fatal)")

    app_scheduler.start_scheduler()


@app.on_event("shutdown")
def _stop_scheduler() -> None:
    """进程退出时停止调度器,避免后台线程泄漏。"""
    from backend import scheduler as app_scheduler

    app_scheduler.shutdown_scheduler()


@app.get("/api/health")
def health() -> dict:
    from backend import scheduler as app_scheduler
    from backend.config.settings import get_settings
    from backend.db.session import engine
    from backend.services.knowledge_pgvector import (
        database_health_snapshot,
        knowledge_vector_health_snapshot,
    )

    database = database_health_snapshot(engine)
    knowledge_vector = knowledge_vector_health_snapshot(engine, get_settings())
    active_scheduler = app_scheduler._scheduler
    scheduler = {
        "status": "running"
        if active_scheduler is not None and bool(getattr(active_scheduler, "running", True))
        else "stopped"
    }
    return {
        "status": "degraded"
        if database["status"] == "degraded" or knowledge_vector["status"] == "degraded"
        else "ok",
        "database": database,
        "knowledge_vector": knowledge_vector,
        "scheduler": scheduler,
    }


def add_routers(app: FastAPI) -> None:
    app.include_router(funds_routes.router)
    app.include_router(watchlist_routes.router)
    app.include_router(market_routes.router)
    app.include_router(announcements_routes.router)
    app.include_router(portfolio_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(briefing_routes.router)
    app.include_router(cls_routes.router)
    app.include_router(knowledge_routes.router)


add_routers(app)
