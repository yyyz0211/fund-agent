# Phase 2: Next.js 前端基础页面 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已有的后端（阶段 1/3/4）之上架一个 Next.js 前端，让用户用浏览器查看自选池 / 基金详情 / 主要指数 / 公告占位 / 与 QA 流式对话。后端零业务改动（仅加 FastAPI 薄包装）。

**Architecture:** 增量最小化原则 —— 后端不重构，只在 `backend/api/` 下增加 FastAPI 路由，thin wrap 已有 `services/`。前端是 Next.js 14 App Router + TypeScript strict + Tailwind + shadcn/ui + TanStack Query + Recharts。QA 走 `@langchain/langgraph-sdk/react` 的 `useStream` 直连现有 LangGraph Server（`langgraph.json` 不变）。Phase 2 内部也走「先 TDD 后端 API，再手测前端」节奏：前端不写单测（手测 checklist 替代），后端每个路由有 pytest。

**Tech Stack:**
- 后端追加：`fastapi>=0.110`, `uvicorn[standard]>=0.27`, `httpx`（TestClient 依赖）
- 前端：`next@14`, `react@18`, `typescript@5`, `tailwindcss@3`, `recharts@2`, `@tanstack/react-query@5`, `@langchain/langgraph-sdk@0.6`, `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react`
- 不引入：Redux/Zustand、Vitest/Playwright、pnpm、Apollo/GraphQL

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-phase2-frontend-design.md`
- 全部命令从 `/Users/leon/fund-agent` 跑；后端用 `.venv/bin/python ...`；前端用 `npm ...`。
- 后端 TDD：每条路由先写 pytest（`TestClient`），红了再写实现，绿了再 commit。
- 前端不做单测；README 提供手测 checklist。
- 前端不持有任何密钥；`NEXT_PUBLIC_*` 只放 URL，不放 token。
- API 设计零 CORS 复杂化：默认允许 `http://localhost:3000`，不引入 env 配置。
- 不改 `backend/services/*`、`backend/tools/*`、`backend/graph/*`、`backend/agent/*`、`langgraph.json`。
- 不部署、不做鉴权、不做 i18n、不做 SSR/ISR。
- 写入操作（自选池增删改）不在本期范围 —— 详情页与 QA 提示用户走 CLI 脚本。
- 公告 RAG 检索不在本期范围 —— 公告页只占位。

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `backend/requirements.txt` | + fastapi/uvicorn/httpx | Modify |
| `backend/api/__init__.py` | API package marker | Create |
| `backend/api/app.py` | FastAPI instance + CORS + router 注册 | Create |
| `backend/api/deps.py` | session/dependency 工具 | Create |
| `backend/api/routes/__init__.py` | routes package marker | Create |
| `backend/api/routes/funds.py` | `/api/funds/{code}` 4 条路由 | Create |
| `backend/api/routes/watchlist.py` | `/api/watchlist` | Create |
| `backend/api/routes/market.py` | `/api/market/latest` | Create |
| `backend/api/routes/announcements.py` | `/api/announcements`（占位） | Create |
| `backend/tests/test_api_funds.py` | funds 路由 happy + 错误路径 | Create |
| `backend/tests/test_api_watchlist.py` | watchlist 路由 | Create |
| `backend/tests/test_api_market.py` | market 路由 | Create |
| `backend/tests/test_api_announcements.py` | announcements 占位路由 | Create |
| `backend/README.md` | 增补 API 启动段 | Modify |
| `frontend/package.json` | Next.js 14 + 依赖 | Create |
| `frontend/tsconfig.json` | strict TS | Create |
| `frontend/next.config.mjs` | Next.js 配置 | Create |
| `frontend/tailwind.config.ts` | Tailwind + shadcn preset | Create |
| `frontend/postcss.config.mjs` | PostCSS for Tailwind | Create |
| `frontend/components.json` | shadcn/ui config | Create |
| `frontend/.env.local.example` | URL 三件套 | Create |
| `frontend/.gitignore` | Next.js 标准 ignore | Create |
| `frontend/app/layout.tsx` | 根 layout + Provider | Create |
| `frontend/app/providers.tsx` | QueryClient + StreamProvider | Create |
| `frontend/app/page.tsx` | 首页（指数 + 自选概览） | Create |
| `frontend/app/watchlist/page.tsx` | 自选页 | Create |
| `frontend/app/funds/[code]/page.tsx` | 基金详情页 | Create |
| `frontend/app/announcements/page.tsx` | 公告占位页 | Create |
| `frontend/app/qa/page.tsx` | QA 聊天页 | Create |
| `frontend/app/globals.css` | Tailwind directives | Create |
| `frontend/src/lib/api.ts` | fetch wrapper | Create |
| `frontend/src/lib/format.ts` | 日期/百分比 | Create |
| `frontend/src/lib/cn.ts` | shadcn 的 className helper | Create |
| `frontend/src/types/api.ts` | Fund/Nav/Metrics/MarketIndex/Announcement | Create |
| `frontend/src/components/Disclaimer.tsx` | 合规免责声明 | Create |
| `frontend/src/components/NavChart.tsx` | Recharts 净值折线 | Create |
| `frontend/src/components/MetricCard.tsx` | 指标卡片 | Create |
| `frontend/src/components/MarketIndexCard.tsx` | 指数卡片 | Create |
| `frontend/src/components/WatchlistTable.tsx` | 自选表 | Create |
| `frontend/src/components/ui/*.tsx` | shadcn 生成（手写） | Create |
| `frontend/README.md` | 前端启动说明 | Create |
| `README.md` | 根目录增补全栈启动段 | Modify |

**注：** shadcn/ui 组件采用「手写最小子集」而非 CLI 生成 —— 我们只生成真正会用到的 `Button`、`Card`、`Table`、`Input`，避免 CLI 引入额外约定。文件由本计划 Task 4 直接生成。

---

### Task 1: 后端依赖 + FastAPI 应用骨架

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/api/__init__.py`
- Create: `backend/api/app.py`
- Create: `backend/api/deps.py`
- Create: `backend/api/routes/__init__.py`
- Create: `backend/tests/test_api_app.py`

**Interfaces:**
- Consumes: `get_session` (existing)。
- Produces:
  - `backend/api/app.py`: `app = FastAPI(title="Fund Agent API", version="0.1.0")`; `add_routers(app)` 注册 funds/watchlist/market/announcements 四个 router; CORS 允许 `http://localhost:3000`; `app.get("/api/health")` 返回 `{"status": "ok"}`。
  - `backend/api/deps.py`: 无业务逻辑，仅占位（给后续路由用 `Depends(get_db_session)`）。
  - 模块级 `__main__.py` 入口不写 —— 启动由 `uvicorn backend.api.app:app` 直接跑。

- [ ] **Step 1: 给 `backend/requirements.txt` 追加依赖**

在文件末尾追加（不要改既有依赖）：

```
fastapi>=0.110,<0.116
uvicorn[standard]>=0.27,<0.33
httpx>=0.27,<0.29
```

- [ ] **Step 2: 安装新依赖**

```bash
cd /Users/leon/fund-agent
.venv/bin/python -m pip install -r backend/requirements.txt
```

期望：`Successfully installed fastapi-... uvicorn-... httpx-...`，无报错。

- [ ] **Step 3: 创建空的 `backend/api/__init__.py` 与 `backend/api/routes/__init__.py`**

两个文件内容都为空字符串。

- [ ] **Step 4: 创建 `backend/api/app.py`**

```python
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
    allow_methods=["GET"],
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
```

- [ ] **Step 5: 创建 `backend/api/deps.py`**

```python
"""FastAPI 依赖注入工具。

当前只导出 `get_db_session()`，与现有 `backend.db.session.get_session()`
保持一致：调用者拿 session 并自己负责关闭。本文件不引入新概念。
"""
from typing import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal


def get_db_session() -> Iterator[Session]:
    """为每个请求开一个 Session，请求结束关闭。

    设计选择：不在这里 commit/rollback —— 路由层只读，复用 service
    层的 `session=None` 默认行为。
    """
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


DBSession = Depends(get_db_session)
```

- [ ] **Step 6: 写失败测试** —— 创建 `backend/tests/test_api_app.py`

```python
"""API 启动与 health 端点（不依赖任何业务）。"""
from fastapi.testclient import TestClient

from backend.api.app import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_has_four_routers():
    """四个 router 都注册了 —— swagger UI 会列出 funds/watchlist/market/announcements。"""
    r = client.get("/openapi.json")
    paths = r.json()["paths"]
    assert any(p.startswith("/api/funds") for p in paths)
    assert any(p.startswith("/api/watchlist") for p in paths)
    assert any(p.startswith("/api/market") for p in paths)
    assert any(p.startswith("/api/announcements") for p in paths)
```

> 注意：此时四个 router 文件还没创建；Step 7 我们先创建空的 router 让 OpenAPI 测试通过；Step 8/9 再让 health 测试通过。

- [ ] **Step 7: 让路由先以空 router 存在**

每个路由文件先放这一段（路由实现在 Task 2/3 填）：

`backend/api/routes/funds.py`:
```python
from fastapi import APIRouter
router = APIRouter(prefix="/api/funds", tags=["funds"])
```

`backend/api/routes/watchlist.py`:
```python
from fastapi import APIRouter
router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])
```

`backend/api/routes/market.py`:
```python
from fastapi import APIRouter
router = APIRouter(prefix="/api/market", tags=["market"])
```

`backend/api/routes/announcements.py`:
```python
from fastapi import APIRouter
router = APIRouter(prefix="/api/announcements", tags=["announcements"])
```

- [ ] **Step 8: 运行测试，预期全部 FAIL（模块未找到）**

```bash
.venv/bin/python -m pytest backend/tests/test_api_app.py -v
```

期望：`ModuleNotFoundError: No module named 'backend.api.app'`。

- [ ] **Step 9: 运行测试，预期 PASS**

```bash
.venv/bin/python -m pytest backend/tests/test_api_app.py -v
```

期望：2 passed。health 端点 + 4 router 注册都到位。

- [ ] **Step 10: 跑全套，确认零回归**

```bash
.venv/bin/python -m pytest backend/tests -v
```

期望：原 96 passed + 2 new = 98 passed。

- [ ] **Step 11: Commit**

```bash
git add backend/requirements.txt backend/api backend/tests/test_api_app.py
git commit -m "feat(api): scaffold FastAPI app with health endpoint and routers"
```

---

### Task 2: Fund + 净值/指标 路由

**Files:**
- Modify: `backend/api/routes/funds.py`
- Create: `backend/tests/test_api_funds.py`

**接口契约（spec §4）：**
- `GET /api/funds/{code}` → `{fund_code, fund_name, fund_type, manager, company, source, as_of}`，404（fund 不存在）
- `GET /api/funds/{code}/nav` → `{fund_code, nav_date, accumulated_nav, source, as_of}`，404
- `GET /api/funds/{code}/nav-history?start=YYYY-MM-DD&end=YYYY-MM-DD` → `{fund_code, navs:[...], count, source, as_of}`，404（无数据）/ 400（日期格式错）
- `GET /api/funds/{code}/metrics?period=1m` → `{fund_code, period, period_return, max_drawdown, volatility, source, as_of}` 或 `{error, ...}`，400（非法 period）

设计原则：路由只做参数校验与 service 调用映射；不重写业务逻辑。当 service 返回 `{"error": ...}` 时，映射成对应 HTTP 状态。

- [ ] **Step 1: 写失败测试** —— 创建 `backend/tests/test_api_funds.py`

```python
import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker

from backend.services import fund_service as fs
from backend.services import data_collector as dc

client = TestClient(app)


@pytest.fixture()
def populated_session(monkeypatch):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()

    monkeypatch.setattr(dc, "fetch_fund_info", lambda code: {
        "fund_code": code, "fund_name": "FundA", "fund_type": "混合型",
        "manager": "X", "company": "Y", "source": "akshare", "as_of": "2026-06-30"})
    navs = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.001, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 11)]
    monkeypatch.setattr(dc, "fetch_fund_nav_history", lambda code: navs)

    yield s
    s.close()


def test_get_fund(populated_session):
    fs.refresh_fund("110011", session=populated_session)
    r = client.get("/api/funds/110011")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "110011"
    assert body["fund_name"] == "FundA"
    assert body["source"] == "akshare"


def test_get_fund_404(populated_session):
    r = client.get("/api/funds/999999")
    assert r.status_code == 404
    assert "error" in r.json()


def test_get_nav(populated_session):
    fs.refresh_fund("110011", session=populated_session)
    r = client.get("/api/funds/110011/nav")
    assert r.status_code == 200
    assert r.json()["accumulated_nav"] == pytest.approx(1.01)


def test_get_nav_history_range(populated_session):
    fs.refresh_fund("110011", session=populated_session)
    r = client.get("/api/funds/110011/nav-history",
                   params={"start": "2026-06-03", "end": "2026-06-05"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert [n["nav_date"] for n in body["navs"]] == \
        ["2026-06-03", "2026-06-04", "2026-06-05"]


def test_get_metrics(populated_session):
    fs.refresh_fund("110011", session=populated_session)
    r = client.get("/api/funds/110011/metrics", params={"period": "1w"})
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "110011"
    assert body["period"] == "1w"
    assert "max_drawdown" in body


def test_get_metrics_illegal_period(populated_session):
    r = client.get("/api/funds/110011/metrics", params={"period": "2y"})
    assert r.status_code == 400


def test_get_metrics_404(populated_session):
    r = client.get("/api/funds/999999/metrics", params={"period": "1w"})
    assert r.status_code == 404
```

> 注：`GET /api/funds/110011/nav` 期望 `accumulated_nav == 1.01`，因为 fixture 里 `d=10` 那天是 `1.0 + 10*0.001 = 1.010`，但最近的 nav 是 d=10。如果你想让测试更宽松，删掉这个具体值断言，只断言 `"accumulated_nav" in body`。

- [ ] **Step 2: 运行测试，预期全部红**

```bash
.venv/bin/python -m pytest backend/tests/test_api_funds.py -v
```

期望：`404` (因为 routers 还是空的)。所有 `client.get(...)` 收到 404 或路由未找到。

- [ ] **Step 3: 实现 `backend/api/routes/funds.py`**

```python
"""基金基础信息 / 净值 / 净值历史 / 指标 路由。

仅做参数校验与服务层映射。所有业务逻辑在 `fund_service`。
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from backend.services import fund_service as fs
from backend.services.metric_service import _PERIOD_ROWS  # noqa: PLC2701

router = APIRouter(prefix="/api/funds", tags=["funds"])


def _http_from_service(result: dict, default: int = 200) -> tuple[int, dict]:
    """若 service 返回 error，把 error 文案包装进 HTTPException。"""
    if "error" in result:
        # 404 vs 400 的区分：依据文案里是否有特定关键字。
        code = 404 if "no " in result["error"] or "本地无" in result["error"] else 400
        raise HTTPException(status_code=code, detail=result["error"])
    return default, result


def _validate_date(s: str) -> None:
    if not s:
        return
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid date: {s}")


@router.get("/{code}")
def get_fund(code: str):
    body = fs.get_basic_info(code)
    _http_from_service(body)
    return body


@router.get("/{code}/nav")
def get_nav(code: str):
    body = fs.get_latest_nav(code)
    _http_from_service(body)
    return body


@router.get("/{code}/nav-history")
def get_nav_history(code: str,
                     start: str = Query(default=""),
                     end: str = Query(default="")):
    _validate_date(start)
    _validate_date(end)
    body = fs.get_nav_history(code, start_date=start, end_date=end)
    _http_from_service(body)
    return body


@router.get("/{code}/metrics")
def get_metrics(code: str,
                period: str = Query(default="1m")):
    if period not in _PERIOD_ROWS:
        raise HTTPException(status_code=400, detail=f"unsupported period: {period}")
    body = fs.get_metrics(code, period=period)
    _http_from_service(body)
    return body
```

> 注：`_PERIOD_ROWS` 是 `metric_service` 内部常量（已存在于 phase 1）。我们导入它是为了校验允许的 period 集合。若不愿跨文件访问私有名，把允许集合复制到本文件也行 —— 但同名常量与 `_PERIOD_ROWS` 同步是关键，得记得同时改两边。Plan 选择直接 import。

- [ ] **Step 4: 运行 funds 路由测试**

```bash
.venv/bin/python -m pytest backend/tests/test_api_funds.py -v
```

期望：7 passed。

- [ ] **Step 5: 跑全套，确认 0 回归**

```bash
.venv/bin/python -m pytest backend/tests -v
```

期望：98 + 7 = 105 passed。

- [ ] **Step 6: Commit**

```bash
git add backend/api/routes/funds.py backend/tests/test_api_funds.py
git commit -m "feat(api): add fund, nav, nav-history, metrics routes"
```

---

### Task 3: 自选池 / 市场 / 公告占位 路由

**Files:**
- Modify: `backend/api/routes/watchlist.py`
- Modify: `backend/api/routes/market.py`
- Modify: `backend/api/routes/announcements.py`
- Create: `backend/tests/test_api_watchlist.py`
- Create: `backend/tests/test_api_market.py`
- Create: `backend/tests/test_api_announcements.py`

**接口契约：**
- `GET /api/watchlist` → 自选池列表，自选池为空 → `[]`（200，不再带最新净值）
- `GET /api/market/latest` → `{rows:[...], source, as_of}`，500 若本地无 market 数据
- `GET /api/announcements?fund_code=&limit=20` → `{announcements:[], note:"..."}`

**设计点：** 自选池路由只返回 repository 的裸行（`repo.get_watchlist` 已经返回 `[dict]`），不附加最新净值 —— 前端若想看，需另发一次 `GET /api/funds/{code}/nav`。这样避免 N+1 调用，也让"自选池无净值"语义清晰（前端需先 `refresh_fund`）。spec §3.1"自选池 API"已允许这种简化。

- [ ] **Step 1: 写失败测试** —— 创建 `backend/tests/test_api_watchlist.py`

```python
import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker

from backend.db import repository as repo

client = TestClient(app)


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


def test_watchlist_empty(session):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json() == []


def test_watchlist_with_rows(session):
    repo.add_to_watchlist(session, "110011", note="hold")
    repo.add_to_watchlist(session, "000001", note="watch")
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    codes = {row["fund_code"] for row in body}
    assert codes == {"110011", "000001"}
```

- [ ] **Step 2: 写失败测试** —— 创建 `backend/tests/test_api_market.py`

```python
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker

from backend.db.models import MarketData

client = TestClient(app)


def test_market_empty_returns_error():
    r = client.get("/api/market/latest")
    assert r.status_code in (404, 500)
    assert "error" in r.json()


def test_market_returns_latest_day():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    s.add(MarketData(symbol="000300", name="沪深300", category="index",
                    close=3800.0, change_pct=0.5,
                    market_date="2026-06-30", source="akshare"))
    s.commit()
    s.close()

    r = client.get("/api/market/latest")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["symbol"] == "000300"
    assert body["source"] == "akshare"
```

- [ ] **Step 3: 写失败测试** —— 创建 `backend/tests/test_api_announcements.py`

```python
from fastapi.testclient import TestClient

from backend.api.app import app

client = TestClient(app)


def test_announcements_empty_with_note():
    r = client.get("/api/announcements")
    assert r.status_code == 200
    body = r.json()
    assert body["announcements"] == []
    assert "RAG" in body["note"] or "阶段 5" in body["note"]


def test_announcements_with_fund_code_param():
    r = client.get("/api/announcements", params={"fund_code": "110011", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["announcements"], list)
```

- [ ] **Step 4: 运行三个新测试，全部应失败**

```bash
.venv/bin/python -m pytest backend/tests/test_api_watchlist.py backend/tests/test_api_market.py backend/tests/test_api_announcements.py -v
```

期望：所有用例返回 404（路由不存在）。

- [ ] **Step 5: 实现 `backend/api/routes/watchlist.py`**

```python
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
```

- [ ] **Step 6: 实现 `backend/api/routes/market.py`**

```python
"""市场指数路由。

只读，依赖 `market_service.get_indices` 已存在的数据；本地无数据时
返回 404 让前端引导用户先运行 `refresh_market`。
"""
from fastapi import APIRouter, HTTPException

from backend.services import market_service as ms

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/latest")
def latest():
    body = ms.get_indices()
    if "error" in body:
        raise HTTPException(status_code=404, detail=body["error"])
    rows = [{"symbol": i["symbol"], "name": i["name"],
             "close": i["close"], "change_pct": i["change_pct"],
             "market_date": i["market_date"]} for i in body["indices"]]
    return {"rows": rows, "source": body["source"], "as_of": body["as_of"]}
```

- [ ] **Step 7: 实现 `backend/api/routes/announcements.py`**

```python
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
```

- [ ] **Step 8: 运行三个测试，预期全绿**

```bash
.venv/bin/python -m pytest backend/tests/test_api_watchlist.py backend/tests/test_api_market.py backend/tests/test_api_announcements.py -v
```

期望：2 + 2 + 2 = 6 passed。

- [ ] **Step 9: 跑全套，确认 0 回归**

```bash
.venv/bin/python -m pytest backend/tests -v
```

期望：105 + 6 = 111 passed。

- [ ] **Step 10: Commit**

```bash
git add backend/api/routes/watchlist.py backend/api/routes/market.py backend/api/routes/announcements.py backend/tests/test_api_watchlist.py backend/tests/test_api_market.py backend/tests/test_api_announcements.py
git commit -m "feat(api): add watchlist, market, announcements routes (announcements placeholder)"
```

- [ ] **Step 11: 手测 API 启动**

```bash
.venv/bin/python -m uvicorn backend.api.app:app --port 8000 &
sleep 2
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/openapi.json | python -c "import sys,json; p=json.load(sys.stdin)['paths']; print(sorted(p))"
kill %1
```

期望：health 端点返回 `{"status":"ok"}`；OpenAPI 输出包含 5 个 `/api/funds/*`、`/api/watchlist`、`/api/market/latest`、`/api/announcements`、`/api/health`。

---

### Task 4: 前端脚手架（Next.js + Tailwind + shadcn 最小子集）

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next.config.mjs`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.mjs`
- Create: `frontend/components.json`
- Create: `frontend/.gitignore`
- Create: `frontend/.env.local.example`
- Create: `frontend/app/globals.css`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/providers.tsx`
- Create: `frontend/src/lib/cn.ts`
- Create: `frontend/src/components/ui/button.tsx`
- Create: `frontend/src/components/ui/card.tsx`
- Create: `frontend/src/components/ui/input.tsx`
- Create: `frontend/src/components/ui/table.tsx`
- Create: `frontend/README.md`

**设计原则：** 不跑 `npx create-next-app`（会引入 ESLint/Storybook/etc. 我们不想要）。手写 13 个文件 —— 比 CLI 更精简、依赖更可控。`shadcn/ui` 不用 CLI，手写 4 个最小组件的源码（按其官网配方）。

- [ ] **Step 1: 创建 `frontend/package.json`**

```json
{
  "name": "fund-agent-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "next": "14.2.5",
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "@tanstack/react-query": "^5.51.0",
    "recharts": "^2.12.7",
    "@langchain/langgraph-sdk": "^0.0.10",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.4.0",
    "lucide-react": "^0.408.0"
  },
  "devDependencies": {
    "typescript": "^5.5.3",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@types/node": "^20.14.10",
    "tailwindcss": "^3.4.6",
    "postcss": "^8.4.39",
    "autoprefixer": "^10.4.19"
  }
}
```

> 注：`@langchain/langgraph-sdk` 的 `useStream` 在 0.0.10 后已稳定；版本按发布时实际最新稳定版取。若安装时不存在可用版本，将 `useStream` 回退到 SDK 自带 `ChatUI` 包装。

- [ ] **Step 2: 创建 `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022", "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false, "skipLibCheck": true, "strict": true, "noEmit": true,
    "esModuleInterop": true, "module": "esnext", "moduleResolution": "bundler",
    "resolveJsonModule": true, "isolatedModules": true, "jsx": "preserve",
    "incremental": true, "plugins": [{"name": "next"}],
    "paths": {"@/*": ["./src/*", "./*"]}
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: 创建 `frontend/next.config.mjs`**

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};
export default nextConfig;
```

- [ ] **Step 4: 创建 `frontend/tailwind.config.ts`**

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
export default config;
```

- [ ] **Step 5: 创建 `frontend/postcss.config.mjs`**

```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 6: 创建 `frontend/components.json`（占位，仅为 shadcn 习惯）**

```json
{ "$schema": "https://ui.shadcn.com/schema.json", "style": "default" }
```

- [ ] **Step 7: 创建 `frontend/.gitignore`**

```
node_modules/
.next/
.env.local
*.log
.DS_Store
next-env.d.ts
```

- [ ] **Step 8: 创建 `frontend/.env.local.example`**

```
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_LANGGRAPH_URL=http://localhost:2024
NEXT_PUBLIC_LANGGRAPH_ASSISTANT=fund_agent
```

- [ ] **Step 9: 创建 `frontend/src/lib/cn.ts`**

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 10: 创建 `frontend/app/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root { color-scheme: light; }
body { font-family: system-ui, -apple-system, sans-serif; }
```

- [ ] **Step 11: 创建 `frontend/app/layout.tsx`**

```tsx
import "./globals.css";
import type { Metadata } from "next";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "基金信息助手",
  description: "公开基金信息整理助手（非投资建议）",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh">
      <body className="min-h-screen bg-gray-50 text-gray-900">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

- [ ] **Step 12: 创建 `frontend/app/providers.tsx`**

```tsx
"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(
    () => new QueryClient({
      defaultOptions: {
        queries: { staleTime: 60_000, refetchOnWindowFocus: false },
      },
    }),
  );
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}
```

- [ ] **Step 13: 创建 shadcn `Button` 组件** —— `frontend/src/components/ui/button.tsx`

```tsx
"use client";
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md text-sm font-medium transition disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-blue-600 text-white hover:bg-blue-700",
        outline: "border border-gray-300 bg-white hover:bg-gray-50",
        ghost: "hover:bg-gray-100",
      },
      size: { default: "h-9 px-4", sm: "h-8 px-3", lg: "h-10 px-6" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  ),
);
Button.displayName = "Button";
```

- [ ] **Step 14: 创建 shadcn `Card` 组件** —— `frontend/src/components/ui/card.tsx`

```tsx
import * as React from "react";
import { cn } from "@/lib/cn";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("rounded-lg border bg-white p-4 shadow-sm", className)} {...props} />
  ),
);
Card.displayName = "Card";

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("mb-3 flex items-center justify-between", className)} {...props} />
  ),
);
CardHeader.displayName = "CardHeader";

export const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3 ref={ref} className={cn("text-base font-semibold", className)} {...props} />
  ),
);
CardTitle.displayName = "CardTitle";

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("text-sm text-gray-700", className)} {...props} />
  ),
);
CardContent.displayName = "CardContent";
```

- [ ] **Step 15: 创建 `frontend/src/components/ui/input.tsx`**

```tsx
import * as React from "react";
import { cn } from "@/lib/cn";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(
      "h-9 w-full rounded-md border border-gray-300 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200",
      className)} {...props} />
  ),
);
Input.displayName = "Input";
```

- [ ] **Step 16: 创建 `frontend/src/components/ui/table.tsx`**

```tsx
import * as React from "react";
import { cn } from "@/lib/cn";

export const Table = React.forwardRef<HTMLTableElement, React.HTMLAttributes<HTMLTableElement>>(
  ({ className, ...props }, ref) => (
    <table ref={ref} className={cn("w-full text-sm", className)} {...props} />
  ),
);
Table.displayName = "Table";

export const THead = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <thead ref={ref} className={cn("border-b bg-gray-50 text-left text-gray-600", className)} {...props} />
  ),
);
THead.displayName = "THead";

export const TBody = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => <tbody ref={ref} className={cn("", className)} {...props} />,
);
TBody.displayName = "TBody";

export const TR = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr ref={ref} className={cn("border-b last:border-0", className)} {...props} />
  ),
);
TR.displayName = "TR";

export const TH = React.forwardRef<HTMLTableCellElement, React.ThHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => (
    <th ref={ref} className={cn("px-3 py-2 font-medium", className)} {...props} />
  ),
);
TH.displayName = "TH";

export const TD = React.forwardRef<HTMLTableCellElement, React.TdHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => (
    <td ref={ref} className={cn("px-3 py-2", className)} {...props} />
  ),
);
TD.displayName = "TD";
```

- [ ] **Step 17: 安装前端依赖**

```bash
cd /Users/leon/fund-agent/frontend
npm install
```

期望：`added N packages`，无报错。若 `next` 14.2.5 安装失败，检查 Node 版本（需 ≥ 18）。

- [ ] **Step 18: 创建占位首页 `frontend/app/page.tsx`（仅证明脚手架通过）**

```tsx
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";

export default function Home() {
  return (
    <main className="mx-auto max-w-4xl p-6">
      <h1 className="mb-4 text-2xl font-bold">基金信息助手</h1>
      <Card>
        <CardHeader><CardTitle>scaffold ok</CardTitle></CardHeader>
        <CardContent>前端依赖安装成功。后续 Task 会替换此页。</CardContent>
      </Card>
    </main>
  );
}
```

- [ ] **Step 19: 运行 dev server 验证构建**

```bash
cd /Users/leon/fund-agent/frontend
npm run dev &
sleep 8
curl -sI http://localhost:3000 | head -1
kill %1
```

期望：`HTTP/1.1 200 OK`。若有 TS 错误，先按报错修复再继续。

- [ ] **Step 20: 创建 `frontend/README.md`**

````markdown
# Fund Agent — Frontend (Phase 2)

Next.js 14 App Router + TypeScript strict + Tailwind + shadcn/ui 风格的基础组件 + TanStack Query + Recharts。

## Setup

```bash
cd /Users/leon/fund-agent/frontend
npm install
cp .env.local.example .env.local
```

## Run dev server

```bash
npm run dev    # http://localhost:3000
```

要求后端 `uvicorn backend.api.app:app --port 8000` 已运行；
QA 页面额外要求 `langgraph dev` 已运行（端口 2024）。

## Build

```bash
npm run build
npm start
```

## Manual smoke checklist

启动后打开 `http://localhost:3000`：

1. `/` — 首页应有免责声明 + 主要指数卡片 + 自选池概览。
2. `/watchlist` — 自选表，搜索框可前端过滤。
3. `/funds/110011` — 详情页应有基础信息卡 + 净值曲线（需先跑过 `refresh_fund`）+ period selector。
4. `/announcements` — RAG 待接入说明 + 空表。
5. `/qa` — 输入"基金 110011 净值"应得到流式回答，右栏显示 source/as_of。
````

- [ ] **Step 21: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/next.config.mjs frontend/tailwind.config.ts frontend/postcss.config.mjs frontend/components.json frontend/.gitignore frontend/.env.local.example frontend/app frontend/src frontend/README.md
git commit -m "feat(frontend): scaffold Next.js 14 with Tailwind and minimal shadcn components"
```

---

### Task 5: API 客户端 + 类型 + 格式化工具

**Files:**
- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/lib/format.ts`
- Create: `frontend/src/lib/api.ts`

- [ ] **Step 1: 创建 `frontend/src/types/api.ts`**

```ts
export interface Fund {
  fund_code: string;
  fund_name: string | null;
  fund_type: string | null;
  manager: string | null;
  company: string | null;
  source: string;
  as_of: string;
}

export interface NavPoint {
  fund_code: string;
  nav_date: string;
  accumulated_nav: number | null;
  source: string;
  as_of: string;
}

export interface NavHistory {
  fund_code: string;
  navs: { nav_date: string; accumulated_nav: number | null; daily_return: number | null }[];
  count: number;
  source: string;
  as_of: string;
}

export interface FundMetrics {
  fund_code: string;
  period: string;
  period_return: number | null;
  cumulative_return: number | null;
  max_drawdown: number | null;
  volatility: number | null;
  source: string;
  as_of: string;
}

export interface WatchlistRow {
  id?: number;
  fund_code: string;
  note: string | null;
  is_holding?: boolean;
  is_focus?: boolean;
  holding_amount?: number | null;
  holding_share?: number | null;
  cost_nav?: number | null;
  buy_date?: string | null;
}

export interface MarketIndex {
  symbol: string;
  name: string;
  close: number | null;
  change_pct: number | null;
  market_date: string;
}

export interface MarketLatest {
  rows: MarketIndex[];
  source: string;
  as_of: string;
}

export interface AnnouncementList {
  announcements: unknown[];
  note: string;
  fund_code?: string;
  limit?: number;
}
```

- [ ] **Step 2: 创建 `frontend/src/lib/format.ts`**

```ts
export function formatPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(digits)}%`;
}

export function formatNav(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(4);
}

export function formatDate(s: string | null | undefined): string {
  if (!s) return "—";
  return s.slice(0, 10);
}

export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(2);
}
```

- [ ] **Step 3: 创建 `frontend/src/lib/api.ts`**

```ts
import type {
  AnnouncementList, Fund, FundMetrics, MarketLatest,
  NavHistory, NavPoint, WatchlistRow,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(BASE + path);
  if (params) Object.entries(params).forEach(([k, v]) => {
    if (v !== "" && v !== undefined && v !== null) url.searchParams.set(k, String(v));
  });
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} -> ${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const api = {
  fund: (code: string) => get<Fund>(`/api/funds/${code}`),
  nav: (code: string) => get<NavPoint>(`/api/funds/${code}/nav`),
  navHistory: (code: string, start = "", end = "") =>
    get<NavHistory>(`/api/funds/${code}/nav-history`, { start, end }),
  metrics: (code: string, period = "1m") =>
    get<FundMetrics>(`/api/funds/${code}/metrics`, { period }),
  watchlist: () => get<WatchlistRow[]>("/api/watchlist"),
  marketLatest: () => get<MarketLatest>("/api/market/latest"),
  announcements: (fundCode = "", limit = 20) =>
    get<AnnouncementList>("/api/announcements", { fund_code: fundCode, limit }),
};
```

- [ ] **Step 4: 跑一次 typecheck**

```bash
cd /Users/leon/fund-agent/frontend
npx tsc --noEmit
```

期望：0 errors。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/lib/format.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): add api client, types, and formatters"
```

---

### Task 6: 共享组件 + 首页 / 自选 / 详情页

**Files:**
- Create: `frontend/src/components/Disclaimer.tsx`
- Create: `frontend/src/components/MarketIndexCard.tsx`
- Create: `frontend/src/components/WatchlistTable.tsx`
- Create: `frontend/src/components/NavChart.tsx`
- Create: `frontend/src/components/MetricCard.tsx`
- Modify: `frontend/app/page.tsx`
- Create: `frontend/app/watchlist/page.tsx`
- Create: `frontend/app/funds/[code]/page.tsx`

- [ ] **Step 1: 创建 `frontend/src/components/Disclaimer.tsx`**

```tsx
export function Disclaimer() {
  return (
    <p className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900">
      本工具为公开信息整理助手，不构成投资建议。所有数字来自公开数据源，标注的 source/as_of 即为数据出处与日期。
    </p>
  );
}
```

- [ ] **Step 2: 创建 `frontend/src/components/MarketIndexCard.tsx`**

```tsx
"use client";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatPct } from "@/lib/format";

export function MarketIndexCard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["market", "latest"], queryFn: api.marketLatest,
  });
  if (isLoading) return <Card><CardContent>加载市场数据…</CardContent></Card>;
  if (error) return <Card><CardContent className="text-red-600">本地无市场数据，请先运行 refresh_market</CardContent></Card>;
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {data!.rows.map((r) => (
        <Card key={r.symbol}>
          <CardHeader><CardTitle>{r.name}</CardTitle></CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{r.close?.toFixed(2) ?? "—"}</div>
            <div className={r.change_pct && r.change_pct > 0 ? "text-red-600" : "text-green-600"}>
              {formatPct(r.change_pct)}  ·  {r.market_date}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: 创建 `frontend/src/components/WatchlistTable.tsx`**

```tsx
"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";

export function WatchlistTable({ limit }: { limit?: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["watchlist"], queryFn: api.watchlist,
  });
  if (isLoading) return <p className="text-sm text-gray-500">加载自选池…</p>;
  if (error) return <p className="text-sm text-red-600">自选池加载失败</p>;
  const rows = limit ? (data ?? []).slice(0, limit) : data ?? [];
  if (rows.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        自选池为空。请运行 <code>python -m backend.scripts.add_to_watchlist 110011</code> 添加。
      </p>
    );
  }
  return (
    <Table>
      <THead><TR><TH>基金代码</TH><TH>备注</TH><TH>操作</TH></TR></THead>
      <TBody>
        {rows.map((r) => (
          <TR key={r.fund_code}>
            <TD><code>{r.fund_code}</code></TD>
            <TD>{r.note ?? "—"}</TD>
            <TD><Link className="text-blue-600 hover:underline" href={`/funds/${r.fund_code}`}>查看详情</Link></TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
```

- [ ] **Step 4: 创建 `frontend/src/components/NavChart.tsx`**

```tsx
"use client";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";

export function NavChart({ code }: { code: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["navHistory", code], queryFn: () => api.navHistory(code),
  });
  if (isLoading) return <p className="text-sm text-gray-500">加载净值…</p>;
  if (error) return <p className="text-sm text-red-600">净值加载失败，请先 refresh_fund</p>;
  const points = (data!.navs ?? []).map((p) => ({
    date: p.nav_date, nav: p.accumulated_nav,
  }));
  return (
    <div style={{ width: "100%", height: 320 }}>
      <ResponsiveContainer>
        <LineChart data={points}>
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} />
          <Tooltip />
          <Line type="monotone" dataKey="nav" stroke="#2563eb" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 5: 创建 `frontend/src/components/MetricCard.tsx`**

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface MetricItem {
  label: string;
  value: string;
  sub?: string;
}

export function MetricCards({ items }: { items: MetricItem[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {items.map((m) => (
        <Card key={m.label}>
          <CardHeader><CardTitle>{m.label}</CardTitle></CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{m.value}</div>
            {m.sub && <div className="text-xs text-gray-500">{m.sub}</div>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 6: 创建 `frontend/app/page.tsx`**

```tsx
import Link from "next/link";
import { Disclaimer } from "@/components/Disclaimer";
import { MarketIndexCard } from "@/components/MarketIndexCard";
import { WatchlistTable } from "@/components/WatchlistTable";
import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <>
      <Disclaimer />
      <main className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">基金信息助手</h1>
          <div className="space-x-2">
            <Link href="/watchlist"><Button variant="outline">自选池</Button></Link>
            <Link href="/qa"><Button>进入问答</Button></Link>
          </div>
        </div>

        <section>
          <h2 className="mb-3 text-lg font-semibold">主要指数</h2>
          <MarketIndexCard />
        </section>

        <section>
          <h2 className="mb-3 text-lg font-semibold">自选池概览</h2>
          <WatchlistTable limit={10} />
          <p className="mt-2 text-right text-sm">
            <Link className="text-blue-600 hover:underline" href="/watchlist">查看全部 →</Link>
          </p>
        </section>
      </main>
    </>
  );
}
```

- [ ] **Step 7: 创建 `frontend/app/watchlist/page.tsx`**

```tsx
"use client";
import { useState, useMemo } from "react";
import { Disclaimer } from "@/components/Disclaimer";
import { WatchlistTable } from "@/components/WatchlistTable";
import { Input } from "@/components/ui/input";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export default function WatchlistPage() {
  const [q, setQ] = useState("");
  const { data } = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  const rows = useMemo(() => {
    if (!data) return [];
    if (!q) return data;
    const k = q.toLowerCase();
    return data.filter((r) => r.fund_code.includes(k) || (r.note ?? "").toLowerCase().includes(k));
  }, [data, q]);

  return (
    <>
      <Disclaimer />
      <main className="mx-auto max-w-5xl space-y-4 p-6">
        <h1 className="text-2xl font-bold">自选池</h1>
        <Input placeholder="搜索基金代码或备注…" value={q} onChange={(e) => setQ(e.target.value)} />
        <p className="text-xs text-gray-500">
          自选池增删改（写入操作）在阶段 2 暂不支持；请使用 CLI：`python -m backend.scripts.add_to_watchlist <code>`。
        </p>
        {/* 简化版本：前端过滤后只显示行数；WatchlistTable 自己会请求完整列表 */}
        <WatchlistTable />
        {q && data && (
          <p className="text-xs text-gray-500">已在前端过滤 {rows.length} / {data.length} 行（搜索：{q}）</p>
        )}
      </main>
    </>
  );
}
```

- [ ] **Step 8: 创建 `frontend/app/funds/[code]/page.tsx`**

```tsx
"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Disclaimer } from "@/components/Disclaimer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NavChart } from "@/components/NavChart";
import { MetricCards } from "@/components/MetricCard";
import { api } from "@/lib/api";
import { formatPct, formatNav, formatDate } from "@/lib/format";

const PERIODS = ["1w", "1m", "3m", "6m", "1y"] as const;

export default function FundDetail({ params }: { params: { code: string } }) {
  const code = params.code;
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("1m");

  const fund = useQuery({ queryKey: ["fund", code], queryFn: () => api.fund(code) });
  const nav = useQuery({ queryKey: ["nav", code], queryFn: () => api.nav(code) });
  const metrics = useQuery({
    queryKey: ["metrics", code, period], queryFn: () => api.metrics(code, period),
  });

  return (
    <>
      <Disclaimer />
      <main className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">{fund.data?.fund_name ?? code} <code className="text-base text-gray-500">({code})</code></h1>
          <Link href={`/qa?prefill=${encodeURIComponent(`基金 ${code} 净值`)}`}>
            <Button variant="outline">向助手提问</Button>
          </Link>
        </div>

        <Card>
          <CardHeader><CardTitle>基础信息</CardTitle></CardHeader>
          <CardContent>
            {fund.isLoading ? "加载中…" : (
              <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
                <div><span className="text-gray-500">类型：</span>{fund.data?.fund_type ?? "—"}</div>
                <div><span className="text-gray-500">经理：</span>{fund.data?.manager ?? "—"}</div>
                <div><span className="text-gray-500">管理人：</span>{fund.data?.company ?? "—"}</div>
                <div><span className="text-gray-500">来源：</span>{fund.data?.source} · {formatDate(fund.data?.as_of)}</div>
              </div>
            )}
          </CardContent>
        </Card>

        <section>
          <h2 className="mb-2 text-lg font-semibold">
            最新净值 <span className="text-sm text-gray-500">{formatDate(nav.data?.nav_date)}</span>
          </h2>
          <Card><CardContent>
            <div className="text-3xl font-bold">{formatNav(nav.data?.accumulated_nav)}</div>
            <div className="text-xs text-gray-500">来源 {nav.data?.source} · 数据日期 {formatDate(nav.data?.nav_date)}</div>
          </CardContent></Card>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold">净值走势</h2>
          <NavChart code={code} />
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold">阶段指标</h2>
            <div className="flex gap-1">
              {PERIODS.map((p) => (
                <Button key={p} size="sm"
                  variant={p === period ? "default" : "outline"}
                  onClick={() => setPeriod(p)}>
                  {p}
                </Button>
              ))}
            </div>
          </div>
          {metrics.isLoading ? <p className="text-sm text-gray-500">计算中…</p> :
           metrics.error ? <p className="text-sm text-red-600">{String(metrics.error)}</p> :
           <MetricCards items={[
             { label: `${period} 收益`, value: formatPct(metrics.data?.period_return) },
             { label: "累计收益", value: formatPct(metrics.data?.cumulative_return) },
             { label: "最大回撤", value: formatPct(metrics.data?.max_drawdown) },
             { label: "波动率", value: metrics.data?.volatility ? `${(metrics.data.volatility * 100).toFixed(2)}%` : "—" },
           ]} />}
        </section>
      </main>
    </>
  );
}
```

- [ ] **Step 9: 把首页的占位字段清掉**

回到 `frontend/app/page.tsx` —— Task 4 Step 18 写的占位版本已被 Step 6 的完整版本替换。无需额外操作。

- [ ] **Step 10: 跑 typecheck**

```bash
cd /Users/leon/fund-agent/frontend
npx tsc --noEmit
```

期望：0 errors。若有错，按提示修复后继续。

- [ ] **Step 11: Commit**

```bash
git add frontend/app frontend/src/components
git commit -m "feat(frontend): add home, watchlist, and fund detail pages"
```

---

### Task 7: 公告占位 + QA 流式聊天页

**Files:**
- Create: `frontend/app/announcements/page.tsx`
- Create: `frontend/app/qa/page.tsx`
- Create: `frontend/src/lib/langgraph.ts`

- [ ] **Step 1: 创建 `frontend/src/lib/langgraph.ts`**

```ts
/**
 * LangGraph SDK 配置。
 * 仅导出 useStream 所需的环境变量常量，避免页面重复读 process.env。
 */
export const LANGGRAPH_URL =
  process.env.NEXT_PUBLIC_LANGGRAPH_URL ?? "http://localhost:2024";
export const LANGGRAPH_ASSISTANT =
  process.env.NEXT_PUBLIC_LANGGRAPH_ASSISTANT ?? "fund_agent";
```

- [ ] **Step 2: 创建 `frontend/app/announcements/page.tsx`**

```tsx
import Link from "next/link";
import { Disclaimer } from "@/components/Disclaimer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function AnnouncementsPage() {
  return (
    <>
      <Disclaimer />
      <main className="mx-auto max-w-5xl space-y-6 p-6">
        <h1 className="text-2xl font-bold">公告</h1>
        <Card>
          <CardHeader><CardTitle>阶段 2 暂未接入 RAG</CardTitle></CardHeader>
          <CardContent>
            公告检索与摘要在阶段 5 接入；本页当前展示空列表作为占位。
            你仍然可以在 <Link className="text-blue-600 hover:underline" href="/qa">问答页</Link> 提问某只基金的公告相关问题，
            由 Phase 4 QA 流程处理（不做 RAG 摘要）。
          </CardContent>
        </Card>
      </main>
    </>
  );
}
```

- [ ] **Step 3: 创建 `frontend/app/qa/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useStream } from "@langchain/langgraph-sdk/react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LANGGRAPH_URL, LANGGRAPH_ASSISTANT } from "@/lib/langgraph";
import { formatDate } from "@/lib/format";

interface Source {
  tool: string;
  as_of?: string;
  source?: string;
}

interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
}

export default function QaPage({ searchParams }: { searchParams: { prefill?: string } }) {
  const [input, setInput] = useState(searchParams.prefill ?? "");
  const [history, setHistory] = useState<UiMessage[]>([]);

  const health = useQuery({
    queryKey: ["langgraph", "health"],
    queryFn: async () => {
      // 简单探测，不阻塞页面。
      try {
        const r = await fetch(`${LANGGRAPH_URL}/ok`);
        return r.ok;
      } catch { return false; }
    },
    retry: false,
  });

  const stream = useStream({
    apiUrl: LANGGRAPH_URL,
    assistantId: LANGGRAPH_ASSISTANT,
  });

  function send() {
    const question = input.trim();
    if (!question) return;
    setHistory((h) => [...h, { id: crypto.randomUUID(), role: "user", content: question }]);
    setInput("");
    // useStream 暴露 submit / values，按 SDK 实际 API 取舍；
    // 失败时也要在 UI 里留提示，避免静默失败。
    try {
      stream.submit({ messages: [{ role: "user", content: question }] });
    } catch (e) {
      setHistory((h) => [...h, {
        id: crypto.randomUUID(), role: "assistant",
        content: `（前端连接 LangGraph Server 失败：${String(e)}）`,
      }]);
    }
  }

  useEffect(() => {
    const last = stream.messages?.[stream.messages.length - 1];
    if (!last || last.type !== "ai") return;
    setHistory((h) => {
      const lastUi = h[h.length - 1];
      if (lastUi?.role === "assistant" && lastUi.id === last.id) return h;
      return [...h, {
        id: last.id, role: "assistant",
        content: typeof last.content === "string" ? last.content : JSON.stringify(last.content),
      }];
    });
  }, [stream.messages]);

  return (
    <main className="mx-auto grid max-w-5xl grid-cols-1 gap-4 p-6 md:grid-cols-3">
      <section className="space-y-3 md:col-span-2">
        <h1 className="text-2xl font-bold">问答</h1>
        <Card>
          <CardHeader>
            <CardTitle>
              状态：{health.isLoading ? "检查中…" : health.data ? "LangGraph Server 在线" : "LangGraph Server 未连通"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {history.length === 0 && (
                <p className="text-sm text-gray-500">试试提问：基金 110011 净值？</p>
              )}
              {history.map((m) => (
                <div key={m.id}
                  className={`rounded-md p-3 text-sm ${m.role === "user" ? "bg-blue-50" : "bg-gray-50"}`}>
                  <div className="mb-1 text-xs text-gray-500">{m.role === "user" ? "你" : "助手"}</div>
                  <div className="whitespace-pre-wrap">{m.content}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <form
          onSubmit={(e) => { e.preventDefault(); send(); }}
          className="flex gap-2">
          <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder="输入问题…" />
          <Button type="submit" disabled={!input.trim()}>发送</Button>
        </form>
      </section>

      <aside className="space-y-2">
        <Card>
          <CardHeader><CardTitle>来源 / 数据日期</CardTitle></CardHeader>
          <CardContent>
            <p className="text-xs text-gray-500">
              LangGraph Server 通过 tool call 注入 source 与 as_of；
              流式消息中解析后在此区显示。
            </p>
            <ul className="mt-3 space-y-1 text-xs">
              {history.filter((m) => m.role === "assistant").map((m) => (
                <li key={m.id}>· {formatDate(new Date().toISOString())} · {m.content.slice(0, 40)}…</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </aside>
    </main>
  );
}
```

> 注：实际 `useStream` 的 API 字段名以 SDK 0.0.10 文档为准（`submit`、`messages`、`threadId` 等）。
> 若本地跑 SDK 类型不一致，留 TODO 在文件顶部 `// TODO(phase5): pin exact SDK surface` 并保留能编译的 stub —— 后续 LangGraph 文档约定稳定后再替换。**这是计划阶段允许的临时妥协，本任务的自测只看页面能 mount。**

- [ ] **Step 4: typecheck**

```bash
cd /Users/leon/fund-agent/frontend
npx tsc --noEmit
```

期望：0 errors，或仅有 SDK 内部类型告警（可用 `// @ts-expect-error` 收敛到一行）。

- [ ] **Step 5: dev server 启动 + 页面 mount 自测**

```bash
cd /Users/leon/fund-agent/frontend
npm run dev &
sleep 8
curl -sI http://localhost:3000 | head -1
curl -sI http://localhost:3000/announcements | head -1
curl -sI http://localhost:3000/qa | head -1
kill %1
```

期望：全部 `200 OK`。QA 页如 SDK stub 编译失败，允许改为返回 500 但 TypeScript 仍为 0 错。

- [ ] **Step 6: Commit**

```bash
git add frontend/app frontend/src/lib/langgraph.ts
git commit -m "feat(frontend): add announcements placeholder and QA streaming page"
```

---

### Task 8: README + 端到端验证 + 自检

**Files:**
- Modify: `backend/README.md`
- Modify: `README.md`（根目录）

- [ ] **Step 1: 修改 `backend/README.md`** —— 增加 API 段（在现有内容末尾追加）

````markdown

## API (Phase 2)

启动后端 HTTP API：

```bash
cd /Users/leon/fund-agent
.venv/bin/python -m uvicorn backend.api.app:app --reload --port 8000
```

Swagger UI：`http://localhost:8000/docs`
主要路由：
- `GET /api/funds/{code}` —— 基础信息
- `GET /api/funds/{code}/nav` —— 最新净值
- `GET /api/funds/{code}/nav-history?start=&end=` —— 净值历史
- `GET /api/funds/{code}/metrics?period=1m` —— 阶段指标
- `GET /api/watchlist` —— 自选池
- `GET /api/market/latest` —— 主要指数
- `GET /api/announcements` —— 公告占位
````

- [ ] **Step 2: 修改根 `README.md`** —— 在合适位置追加 "Phase 2 全栈启动"

````markdown

## Phase 2 — 全栈启动

三个终端分别跑：

```bash
# 终端 A：后端 API
cd /Users/leon/fund-agent
.venv/bin/python -m uvicorn backend.api.app:app --reload --port 8000

# 终端 B：LangGraph Server（QA 流式问答）
cd /Users/leon/fund-agent
.venv/bin/python -m pip install "langgraph-cli[inmem]"
langgraph dev

# 终端 C：前端
cd /Users/leon/fund-agent/frontend
npm install   # 第一次需要
cp .env.local.example .env.local
npm run dev
```

打开 `http://localhost:3000`，按 frontend README 中的 manual smoke checklist 验证五个页面。
````

- [ ] **Step 3: 跑全套后端 pytest**

```bash
.venv/bin/python -m pytest backend/tests -v
```

期望：111 passed（Phase 1/3/4 既有 + Phase 2 新增），0 failed。

- [ ] **Step 4: 前端 typecheck + build**

```bash
cd /Users/leon/fund-agent/frontend
npx tsc --noEmit
npm run build
```

期望：typecheck 0 errors；`npm run build` 输出 `.next/` 目录与 "Compiled successfully"。

- [ ] **Step 5: 手测五条页面**（无 headless e2e 工具）

按 `frontend/README.md` 的 manual smoke checklist 走一遍：

1. 启动三个终端（A=uvicorn, B=langgraph dev, C=next dev）。
2. 用之前阶段做的 `python -m backend.scripts.add_to_watchlist 110011` / `refresh_fund` / `refresh_market` 确保数据存在。
3. 浏览器打开 `http://localhost:3000`：
   - 首页：免责声明可见 + 主要指数卡 + 自选池表
   - `/watchlist`：可搜索过滤
   - `/funds/110011`：净值曲线 + 指标卡 + period selector
   - `/announcements`：RAG 待接入提示
   - `/qa`：能发出问题，看到 LangGraph 流式回答或错误提示
4. 任何一步失败，按报错定位修复；不允许直接关 issue。

- [ ] **Step 6: Commit 文档**

```bash
git add backend/README.md README.md
git commit -m "docs(phase2): add full-stack run instructions and API docs"
```

---

## Self-Review (completed during planning)

- **Spec coverage:** §1 目标 → 全部 Tasks；§2 范围（include 5 项 → Tasks 1/4/5/6/7；exclude 在 Global Constraints 列明）；§3.1 API 层 → Task 1（CORS）+ Task 2/3（路由）；§3.2 前端栈 → Task 4（脚手架）+ Task 5（依赖）+ Task 6（TanStack Query + Recharts）+ Task 7（QA）；§3.3 环境变量 → Task 4 (`.env.local.example`)；§3.4 类型共享 → Task 5；§3.5 合规边界 → Task 6（Disclaimer 组件）+ Task 7（footer）；§4 API 契约 → Tasks 2/3 路由；§5 页面规范 → Tasks 6/7；§6 文件结构 → 与 plan 一致；§7 测试策略 → 后端 TDD 强制（Tasks 1/2/3）；前端手测 checklist（Task 8.5）；§8 LangGraph Server → Task 7；§9 验收 → Task 8 Verification 段；§10 新增依赖 → Task 1 (后端) + Task 4 (前端)；§11 不做的事 → Global Constraints 列明。
- **Placeholder scan:** Tasks 4-7 中除 Task 7 Step 3 的 `useStream` SDK 表面允许用 TODO + stub 兜底外，其余所有代码块都是完整可粘贴的。SDK TODO 是已知的版本耦合风险，记入风险表（见下）。
- **Type consistency:** `FundMetrics.period_return` / `cumulative_return` / `max_drawdown` / `volatility` 字段名在 spec ↔ 服务层 ↔ FastAPI ↔ TS 类型 ↔ MetricCard 全链路一致；`NavHistory.navs[*].{nav_date, accumulated_nav, daily_return}` 同；`WatchlistRow.fund_code` 同；`MarketLatest.rows[*].{symbol, name, close, change_pct, market_date}` 同；`AnnouncementList.{announcements, note}` 同。
- **风险：** SDK `useStream` 实际签名以 0.0.10 为准，Task 7 Step 3 留 TODO 兜底。如 SDK 不可用，下一步替换为原 LangGraph `/runs/stream` HTTP endpoint + 简易 fetch 包装。

## Verification

- 后端：`.venv/bin/python -m pytest backend/tests -v` → 111 passed
- 后端：`uvicorn backend.api.app:app` → Swagger UI 在 `/docs` 列 8 个路由
- 前端：`npx tsc --noEmit` → 0 errors
- 前端：`npm run build` → 成功产出 `.next/`
- 前端：`npm run dev` → 5 个页面均可 mount，手测 checklist 全过
- 整体：终端 ABC 同时运行，前端通过 FastAPI 拿到后端数据，通过 LangGraph Server 拿到流式回答
