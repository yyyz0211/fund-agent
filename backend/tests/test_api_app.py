"""API 启动与 health 端点（不依赖任何业务）。"""
from fastapi.testclient import TestClient

from backend.api.app import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_has_four_routers():
    """四个 router 模块都设置好 prefix —— 通过 router 暴露的 prefix 字段验证。

    Task 2/3 填上 `@router.get(...)` 后，OpenAPI 自动会出现具体路径。
    """
    from backend.api.routes import funds, market, watchlist, announcements
    assert funds.router.prefix == "/api/funds"
    assert watchlist.router.prefix == "/api/watchlist"
    assert market.router.prefix == "/api/market"
    assert announcements.router.prefix == "/api/announcements"


def test_openapi_paths_match_spec():
    """/api/health 是 app.py 自身的端点，必须存在；Task 2/3 会填充更多 path。"""
    r = client.get("/openapi.json")
    paths = r.json()["paths"]
    assert "/api/health" in paths
