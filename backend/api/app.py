"""FastAPI 应用入口。

只做最小骨架：注册 CORS、五个业务 router、健康检查端点。
业务由 `routes/` 拆分，本文件不应承载任何业务函数。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from backend.exceptions import (
    DependencyUnavailableError,
    FundAgentError,
    InputValidationError,
    ResourceNotFoundError,
    http_status_for,
    redact_dict,
)

app = FastAPI(title="Fund Agent API", version="0.1.0")

logger = logging.getLogger(__name__)

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


def _register_exception_handlers(app: FastAPI) -> None:
    """把业务异常统一映射到 HTTP 响应(spec 4.3 错误处理矩阵)。

    - ResourceNotFoundError → 404
    - InputValidationError → 422
    - DataSourceError / DataSourceTimeoutError → 502/504
    - DatabaseConflictError → 409
    - DependencyUnavailableError → 503(caller 决定是否降级到 200)
    - 其它 FundAgentError → 500
    - 未分类 Exception → 500,不泄露 stack trace
    """

    @app.exception_handler(ResourceNotFoundError)
    async def _resource_not_found(_: Request, exc: ResourceNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=_payload(exc, code="resource_not_found"),
        )

    @app.exception_handler(InputValidationError)
    async def _input_validation(_: Request, exc: InputValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_payload(exc, code="input_validation", extra={"field": exc.field}),
        )

    @app.exception_handler(FundAgentError)
    async def _generic_business(_: Request, exc: FundAgentError) -> JSONResponse:
        return JSONResponse(
            status_code=http_status_for(exc),
            content=_payload(exc, code=_code_for(exc)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # 未分类异常：仅暴露 message,避免泄露内部栈
        logger.exception("unhandled API exception")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": str(exc) or exc.__class__.__name__,
                }
            },
        )


def _payload(exc: FundAgentError, *, code: str, extra: dict | None = None) -> dict:
    payload: dict = {
        "error": {
            "code": code,
            "message": str(exc),
            "details": redact_dict(exc.details or {}),
        }
    }
    if extra:
        payload["error"].update(extra)
    return payload


def _code_for(exc: FundAgentError) -> str:
    from backend.exceptions import (
        DatabaseConflictError,
        DataSourceError,
        DataSourceTimeoutError,
    )

    if isinstance(exc, ResourceNotFoundError):
        return "resource_not_found"
    if isinstance(exc, InputValidationError):
        return "input_validation"
    if isinstance(exc, DataSourceTimeoutError):
        return "data_source_timeout"
    if isinstance(exc, DataSourceError):
        return "data_source_error"
    if isinstance(exc, DatabaseConflictError):
        return "database_conflict"
    if isinstance(exc, DependencyUnavailableError):
        return "dependency_unavailable"
    return "internal_error"


_register_exception_handlers(app)


@app.on_event("startup")
def _ensure_schema() -> None:
    """进程启动时建库并做非破坏性初始化。

    schema 直接由 SQLAlchemy 模型（`Base.metadata`）建立，数据可丢弃，
    不保留迁移历史；`init_db()` 同时管理 pgvector schema 与 watchlist 回填。
    """
    from backend import scheduler as app_scheduler
    from backend.db.init_db import init_db
    from backend.services.knowledge import knowledge_reindex_jobs

    # 建库
    try:
        init_db()
        logger.info("[startup] database schema initialized")
    except Exception as schema_exc:
        logger.error("[startup] schema initialization failed: %s", schema_exc)
        logger.error("[startup] Application cannot start without valid schema.")
        raise SystemExit(1) from schema_exc

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
    from backend.services.knowledge.knowledge_pgvector import (
        database_health_snapshot,
        knowledge_vector_health_snapshot,
    )

    database = database_health_snapshot(engine)
    knowledge_vector = knowledge_vector_health_snapshot(engine, get_settings())
    active_scheduler = app_scheduler.get_scheduler()
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
