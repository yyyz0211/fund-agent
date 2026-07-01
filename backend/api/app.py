"""FastAPI 应用入口。

只做最小骨架：注册 CORS、四个业务 router、健康检查端点。
业务由 `routes/` 拆分，本文件不应承载任何业务函数。
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import funds as funds_routes
from backend.api.routes import market as market_routes
from backend.api.routes import watchlist as watchlist_routes
from backend.api.routes import announcements as announcements_routes

app = FastAPI(title="Fund Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=False,
    # 自选池的 POST/PATCH/DELETE 走浏览器预检,必须显式放行;
    # OPTIONS 留给浏览器自动处理(不在这里列出,FastAPI 也能响应)。
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


def add_routers(app: FastAPI) -> None:
    app.include_router(funds_routes.router)
    app.include_router(watchlist_routes.router)
    app.include_router(market_routes.router)
    app.include_router(announcements_routes.router)


add_routers(app)
