# Phase 3: LangChain Tools (Data-Ready Domain) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the backend's data-ready capabilities into 11 standard LangChain tools (fund + market + watchlist domain), exposing a single `ALL_TOOLS` aggregate for the phase-4 QA graph.

**Architecture:** Each tool is a thin wrapper over a service function — no business logic in tools. Query tools are read-only (local DB, return LLM-readable error dicts when empty); refresh tools do the networked writes. Tools are split by domain into three files (fund / watchlist / market). Tests are fully offline: service methods use in-memory SQLite; tools monkeypatch their backing service.

**Tech Stack:** Python 3.11 (venv at `.venv`), langchain / langchain-core, SQLAlchemy, pytest. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-phase3-tools-design.md`
- Run everything with the venv interpreter: `.venv/bin/python -m pytest ...` from `/Users/leon/fund-agent`.
- Every tool is a thin wrapper over exactly one service function. No DB/network access inside tools.
- Query tools are READ-ONLY: never network, never write. Empty local data → `{"error": "...请先 refresh_..."}` dict, never raw exception or None.
- Refresh tools are the only ones that go to network (they wrap existing `fund_service.refresh_fund` / `market_service.refresh_market`).
- Data tools return `source` + `as_of`; watchlist tools (user-local data) do not.
- Optional params (`note` / `start_date` / `end_date`) use empty-string `""` defaults, NOT `None`, for clean DeepSeek function-calling JSON Schema.
- `nav_date` / `market_date` are `YYYY-MM-DD` strings — date-range filtering uses direct string comparison.
- TDD: failing test first, minimal impl, commit per task.
- Phase-1 `fund_tools.TOOLS` (2 tools) stays intact for the existing thin agent; phase-3 adds a new `ALL_TOOLS` aggregate (11 tools).

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `backend/services/fund_service.py` | + `get_basic_info`, `get_nav_history` | Modify |
| `backend/services/market_service.py` | + `get_indices` | Modify |
| `backend/services/watchlist_service.py` | 4 session-managing wrappers over repository | Create |
| `backend/tools/fund_tools.py` | + fund query/refresh tools + `ALL_TOOLS` aggregate | Modify |
| `backend/tools/watchlist_tools.py` | 4 watchlist tools | Create |
| `backend/tools/market_tools.py` | `get_market_indices` + `refresh_market` tools | Create |
| `backend/tests/test_fund_service.py` | + `get_basic_info` / `get_nav_history` tests | Modify |
| `backend/tests/test_market_service.py` | `get_indices` tests | Create |
| `backend/tests/test_watchlist_service.py` | watchlist service tests | Create |
| `backend/tests/test_tools.py` | + coverage for all new tools + `ALL_TOOLS` | Modify |

**Why `watchlist_service.py` (not in spec §6):** spec §3 requires every tool to wrap a service function, but `repository` functions take `session` as their first arg. To keep watchlist tools thin and offline-testable (mirroring the existing `fund_service` session-managing pattern), the 4 watchlist tools wrap session-managing service functions rather than calling repository directly.

---

### Task 1: fund_service — get_basic_info + get_nav_history

**Files:**
- Modify: `backend/services/fund_service.py`
- Modify: `backend/tests/test_fund_service.py`

**Interfaces:**
- Consumes: `Fund`, `FundNav` models; `get_session`; `dc.SOURCE`, `dc.today_str()` (all existing).
- Produces:
  - `get_basic_info(fund_code, session=None) -> dict` — reads `Fund` table; returns `{fund_code, fund_name, fund_type, manager, company, source, as_of}` or `{"error": "本地无 <code> 基础信息，请先 refresh_fund", "source": dc.SOURCE}`.
  - `get_nav_history(fund_code, start_date="", end_date="", session=None) -> dict` — reads `FundNav` ordered by `nav_date` asc; empty-string date = unbounded; returns `{fund_code, navs: [{nav_date, accumulated_nav, daily_return}], count, source, as_of}` or `{"error": "本地无 <code> 净值数据，请先 refresh_fund", "source": dc.SOURCE}`.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_fund_service.py`

```python
def test_get_basic_info_no_data(session):
    assert "error" in fs.get_basic_info("110011", session=session)


def test_get_basic_info_returns_row(session):
    from backend.db import repository as repo
    repo.upsert_fund(session, {"fund_code": "110011", "fund_name": "FundA",
                               "fund_type": "混合型", "manager": "X", "company": "Y"})
    out = fs.get_basic_info("110011", session=session)
    assert out["fund_name"] == "FundA"
    assert out["source"] == "akshare"
    assert "as_of" in out


def test_get_nav_history_no_data(session):
    assert "error" in fs.get_nav_history("110011", session=session)


def test_get_nav_history_full_and_range(session):
    from backend.db import repository as repo
    rows = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 11)]
    repo.upsert_navs(session, "110011", rows)

    full = fs.get_nav_history("110011", session=session)
    assert full["count"] == 10
    assert full["navs"][0]["nav_date"] == "2026-06-01"
    assert "accumulated_nav" in full["navs"][0]
    assert full["source"] == "akshare"

    ranged = fs.get_nav_history("110011", start_date="2026-06-03",
                                end_date="2026-06-05", session=session)
    assert [r["nav_date"] for r in ranged["navs"]] == \
        ["2026-06-03", "2026-06-04", "2026-06-05"]
    assert ranged["count"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_fund_service.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'get_basic_info'`.

- [ ] **Step 3: Add `get_basic_info` to `backend/services/fund_service.py`**

```python
def get_basic_info(fund_code: str, session=None) -> dict:
    """从本地库读基金基础信息。无数据返回可读 error dict（提示先 refresh_fund）。"""
    s = _with_session(session)
    owns = session is None
    try:
        from backend.db.models import Fund
        row = s.get(Fund, fund_code)
        if row is None:
            return {"error": f"本地无 {fund_code} 基础信息，请先 refresh_fund",
                    "source": dc.SOURCE}
        return {"fund_code": row.fund_code, "fund_name": row.fund_name,
                "fund_type": row.fund_type, "manager": row.manager,
                "company": row.company, "source": dc.SOURCE, "as_of": dc.today_str()}
    finally:
        if owns:
            s.close()
```

- [ ] **Step 4: Add `get_nav_history` to `backend/services/fund_service.py`**

```python
def get_nav_history(fund_code: str, start_date: str = "", end_date: str = "",
                    session=None) -> dict:
    """从本地库读带日期的净值序列，支持可选区间过滤（空字符串=不限）。

    nav_date 为 YYYY-MM-DD 字符串，区间过滤用字符串比较。无数据返回 error dict。
    """
    s = _with_session(session)
    owns = session is None
    try:
        from sqlalchemy import select
        from backend.db.models import FundNav
        stmt = select(FundNav).where(FundNav.fund_code == fund_code)
        if start_date:
            stmt = stmt.where(FundNav.nav_date >= start_date)
        if end_date:
            stmt = stmt.where(FundNav.nav_date <= end_date)
        rows = s.scalars(stmt.order_by(FundNav.nav_date)).all()
        if not rows:
            return {"error": f"本地无 {fund_code} 净值数据，请先 refresh_fund",
                    "source": dc.SOURCE}
        navs = [{"nav_date": r.nav_date, "accumulated_nav": r.accumulated_nav,
                 "daily_return": r.daily_return} for r in rows]
        return {"fund_code": fund_code, "navs": navs, "count": len(navs),
                "source": dc.SOURCE, "as_of": dc.today_str()}
    finally:
        if owns:
            s.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_fund_service.py -v`
Expected: PASS — original 3 + new 4 = 7 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/services/fund_service.py backend/tests/test_fund_service.py
git commit -m "feat: add get_basic_info and get_nav_history to fund_service"
```

### Task 2: market_service — get_indices

**Files:**
- Modify: `backend/services/market_service.py`
- Create: `backend/tests/test_market_service.py`

**Interfaces:**
- Consumes: `MarketData` model; `get_session`; `dc.SOURCE`, `dc.today_str()` (existing).
- Produces:
  - `get_indices(session=None) -> dict` — reads `market_data` rows for the latest `market_date` only; returns `{indices: [{symbol, name, close, change_pct, market_date}], source, as_of}` or `{"error": "本地无市场数据，请先 refresh_market", "source": dc.SOURCE}`.

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_market_service.py`

```python
import pytest
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker
from backend.services import market_service as ms
from backend.db.models import MarketData


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


def test_get_indices_no_data(session):
    assert "error" in ms.get_indices(session=session)


def test_get_indices_returns_latest_date_only(session):
    session.add(MarketData(symbol="000300", name="沪深300", category="index",
                           close=3800.0, change_pct=0.5, market_date="2026-06-29",
                           source="akshare"))
    session.add(MarketData(symbol="000300", name="沪深300", category="index",
                           close=3820.0, change_pct=0.6, market_date="2026-06-30",
                           source="akshare"))
    session.add(MarketData(symbol="000001", name="上证指数", category="index",
                           close=3100.0, change_pct=0.3, market_date="2026-06-30",
                           source="akshare"))
    session.commit()

    out = ms.get_indices(session=session)
    dates = {i["market_date"] for i in out["indices"]}
    assert dates == {"2026-06-30"}  # latest date only
    assert len(out["indices"]) == 2
    assert out["source"] == "akshare"
    assert "as_of" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_market_service.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'get_indices'`.

- [ ] **Step 3: Add `get_indices` to `backend/services/market_service.py`**

```python
def get_indices(session=None) -> dict:
    """从本地库读最新一个交易日的全部指数行。无数据返回可读 error dict。"""
    s = session or get_session()
    owns = session is None
    try:
        latest = s.scalar(select(MarketData.market_date)
                          .order_by(MarketData.market_date.desc()))
        if latest is None:
            return {"error": "本地无市场数据，请先 refresh_market", "source": dc.SOURCE}
        rows = s.scalars(select(MarketData)
                         .where(MarketData.market_date == latest)
                         .order_by(MarketData.symbol)).all()
        indices = [{"symbol": r.symbol, "name": r.name, "close": r.close,
                    "change_pct": r.change_pct, "market_date": r.market_date}
                   for r in rows]
        return {"indices": indices, "source": dc.SOURCE, "as_of": dc.today_str()}
    finally:
        if owns:
            s.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_market_service.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/services/market_service.py backend/tests/test_market_service.py
git commit -m "feat: add get_indices to market_service"
```

### Task 3: watchlist_service — 4 session-managing wrappers

**Files:**
- Create: `backend/services/watchlist_service.py`
- Create: `backend/tests/test_watchlist_service.py`

**Interfaces:**
- Consumes: `repository` functions `add_to_watchlist(session, fund_code, note=None) -> dict`, `remove_from_watchlist(session, fund_code) -> bool`, `update_watchlist_note(session, fund_code, note) -> dict | None`, `get_watchlist(session) -> list[dict]`; `get_session`.
- Produces (each opens/closes its own session when `session=None`):
  - `list_watchlist(session=None) -> list[dict]`
  - `add(fund_code, note="", session=None) -> dict`
  - `remove(fund_code, session=None) -> dict` — `{"fund_code", "removed": bool}`
  - `update_note(fund_code, note, session=None) -> dict` — updated row, or `{"error": "<code> 不在自选池中"}` when absent.

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_watchlist_service.py`

```python
import pytest
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker
from backend.services import watchlist_service as ws


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


def test_list_empty(session):
    assert ws.list_watchlist(session=session) == []


def test_add_and_list(session):
    row = ws.add("110011", note="hold", session=session)
    assert row["fund_code"] == "110011"
    assert len(ws.list_watchlist(session=session)) == 1


def test_remove(session):
    ws.add("110011", session=session)
    assert ws.remove("110011", session=session) == {"fund_code": "110011", "removed": True}
    assert ws.remove("110011", session=session) == {"fund_code": "110011", "removed": False}


def test_update_note_present_and_absent(session):
    ws.add("110011", session=session)
    out = ws.update_note("110011", "watch", session=session)
    assert out["note"] == "watch"
    missing = ws.update_note("999999", "x", session=session)
    assert "error" in missing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_watchlist_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.watchlist_service'`.

- [ ] **Step 3: Create `backend/services/watchlist_service.py`**

```python
"""自选池领域服务。

对 repository 的自选池 CRUD 做一层 session 管理封装，使 watchlist 工具
保持薄包装。自选池是本地用户数据，返回不带 source/as_of。
"""
from backend.db.session import get_session
from backend.db import repository as repo


def _with_session(session):
    return session or get_session()


def list_watchlist(session=None) -> list[dict]:
    """返回自选池全部行，空时返回 []。"""
    s = _with_session(session)
    owns = session is None
    try:
        return repo.get_watchlist(s)
    finally:
        if owns:
            s.close()


def add(fund_code: str, note: str = "", session=None) -> dict:
    """加入自选池（幂等），返回该行 dict。"""
    s = _with_session(session)
    owns = session is None
    try:
        return repo.add_to_watchlist(s, fund_code, note=note or None)
    finally:
        if owns:
            s.close()


def remove(fund_code: str, session=None) -> dict:
    """从自选池移除，返回 {fund_code, removed: bool}。"""
    s = _with_session(session)
    owns = session is None
    try:
        removed = repo.remove_from_watchlist(s, fund_code)
        return {"fund_code": fund_code, "removed": removed}
    finally:
        if owns:
            s.close()


def update_note(fund_code: str, note: str, session=None) -> dict:
    """更新备注，返回更新后的行；不在池中返回可读 error dict。"""
    s = _with_session(session)
    owns = session is None
    try:
        row = repo.update_watchlist_note(s, fund_code, note)
        if row is None:
            return {"error": f"{fund_code} 不在自选池中"}
        return row
    finally:
        if owns:
            s.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_watchlist_service.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/services/watchlist_service.py backend/tests/test_watchlist_service.py
git commit -m "feat: add watchlist_service wrapping repository CRUD"
```

### Task 4: watchlist_tools + market_tools (new tool files)

**Files:**
- Create: `backend/tools/watchlist_tools.py`
- Create: `backend/tools/market_tools.py`
- Modify: `backend/tests/test_tools.py`

**Interfaces:**
- Consumes: `watchlist_service` (Task 3); `market_service` (Task 2 `get_indices`, existing `refresh_market`).
- Produces:
  - `watchlist_tools`: tools `get_watchlist`, `add_fund_to_watchlist`, `remove_fund_from_watchlist`, `update_fund_note`; module list `WATCHLIST_TOOLS`.
  - `market_tools`: tools `get_market_indices`, `refresh_market`; module list `MARKET_TOOLS`.
- Tool names (`.name`) equal the function names above. Tests monkeypatch the backing service — no DB, no network.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_tools.py`

```python
from backend.tools import watchlist_tools as wt
from backend.tools import market_tools as mt
from backend.services import watchlist_service as wsvc
from backend.services import market_service as msvc


def test_watchlist_tools_forward(monkeypatch):
    monkeypatch.setattr(wsvc, "list_watchlist", lambda session=None: [{"fund_code": "1"}])
    monkeypatch.setattr(wsvc, "add", lambda code, note="", session=None: {"fund_code": code, "note": note})
    monkeypatch.setattr(wsvc, "remove", lambda code, session=None: {"fund_code": code, "removed": True})
    monkeypatch.setattr(wsvc, "update_note", lambda code, note, session=None: {"fund_code": code, "note": note})

    assert wt.get_watchlist.invoke({}) == [{"fund_code": "1"}]
    assert wt.add_fund_to_watchlist.invoke({"fund_code": "110011", "note": "x"})["note"] == "x"
    assert wt.remove_fund_from_watchlist.invoke({"fund_code": "110011"})["removed"] is True
    assert wt.update_fund_note.invoke({"fund_code": "110011", "note": "y"})["note"] == "y"


def test_market_tools_forward(monkeypatch):
    monkeypatch.setattr(msvc, "get_indices", lambda session=None: {"indices": [], "source": "akshare"})
    monkeypatch.setattr(msvc, "refresh_market", lambda session=None: {"inserted": 3, "source": "akshare"})
    assert mt.get_market_indices.invoke({})["source"] == "akshare"
    assert mt.refresh_market.invoke({})["inserted"] == 3


def test_tool_lists_exposed():
    assert {t.name for t in wt.WATCHLIST_TOOLS} == {
        "get_watchlist", "add_fund_to_watchlist",
        "remove_fund_from_watchlist", "update_fund_note"}
    assert {t.name for t in mt.MARKET_TOOLS} == {"get_market_indices", "refresh_market"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError` for `backend.tools.watchlist_tools`.

- [ ] **Step 3: Create `backend/tools/watchlist_tools.py`**

```python
"""自选池 LangChain 工具。薄包装 watchlist_service。"""
from langchain_core.tools import tool

from backend.services import watchlist_service as wsvc


@tool
def get_watchlist() -> list:
    """获取用户自选基金池的全部条目（含备注、持仓标记）。"""
    return wsvc.list_watchlist()


@tool
def add_fund_to_watchlist(fund_code: str, note: str = "") -> dict:
    """把一只基金加入自选池（幂等）。note 为可选备注。"""
    return wsvc.add(fund_code, note=note)


@tool
def remove_fund_from_watchlist(fund_code: str) -> dict:
    """从自选池移除一只基金。返回 {fund_code, removed}。"""
    return wsvc.remove(fund_code)


@tool
def update_fund_note(fund_code: str, note: str) -> dict:
    """更新自选池中某只基金的备注。基金不在池中时返回 error。"""
    return wsvc.update_note(fund_code, note)


WATCHLIST_TOOLS = [get_watchlist, add_fund_to_watchlist,
                   remove_fund_from_watchlist, update_fund_note]
```

- [ ] **Step 4: Create `backend/tools/market_tools.py`**

```python
"""市场数据 LangChain 工具。薄包装 market_service。"""
from langchain_core.tools import tool

from backend.services import market_service as msvc


@tool
def get_market_indices() -> dict:
    """获取最新一个交易日的主要市场指数（来自本地库，需先 refresh_market）。"""
    return msvc.get_indices()


@tool
def refresh_market() -> dict:
    """联网拉取主要市场指数当日行情并入本地库。返回 {inserted, source, as_of}。"""
    return msvc.refresh_market()


MARKET_TOOLS = [get_market_indices, refresh_market]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_tools.py -v`
Expected: PASS — original 3 + new 3 = 6 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/tools/watchlist_tools.py backend/tools/market_tools.py backend/tests/test_tools.py
git commit -m "feat: add watchlist and market LangChain tools"
```

### Task 5: fund_tools — query/refresh tools + ALL_TOOLS aggregate

**Files:**
- Modify: `backend/tools/fund_tools.py`
- Modify: `backend/tests/test_tools.py`

**Interfaces:**
- Consumes: `fund_service` `get_basic_info` (Task 1), `get_nav_history` (Task 1), existing `refresh_fund`; `WATCHLIST_TOOLS` (Task 4), `MARKET_TOOLS` (Task 4); existing `get_latest_fund_nav`, `calculate_fund_metrics`.
- Produces:
  - New tools in `fund_tools`: `get_fund_basic_info`, `get_fund_nav_history`, `refresh_fund`.
  - `FUND_TOOLS = [get_latest_fund_nav, calculate_fund_metrics, get_fund_basic_info, get_fund_nav_history, refresh_fund]` (5).
  - `ALL_TOOLS = FUND_TOOLS + WATCHLIST_TOOLS + MARKET_TOOLS` (11 total).
  - Existing `TOOLS = [get_latest_fund_nav, calculate_fund_metrics]` stays unchanged (phase-1 thin agent compat).

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_tools.py`

```python
def test_fund_basic_info_tool(monkeypatch):
    monkeypatch.setattr(fs, "get_basic_info",
                        lambda code, session=None: {"fund_code": code, "fund_name": "FundA",
                                                    "source": "akshare"})
    out = fund_tools.get_fund_basic_info.invoke({"fund_code": "110011"})
    assert out["fund_name"] == "FundA"


def test_fund_nav_history_tool(monkeypatch):
    monkeypatch.setattr(fs, "get_nav_history",
                        lambda code, start_date="", end_date="", session=None: {
                            "fund_code": code, "navs": [], "count": 0,
                            "start": start_date, "end": end_date, "source": "akshare"})
    out = fund_tools.get_fund_nav_history.invoke(
        {"fund_code": "110011", "start_date": "2026-06-01", "end_date": "2026-06-30"})
    assert out["start"] == "2026-06-01" and out["end"] == "2026-06-30"


def test_refresh_fund_tool(monkeypatch):
    monkeypatch.setattr(fs, "refresh_fund",
                        lambda code, session=None: {"fund_code": code, "navs_inserted": 5,
                                                    "source": "akshare"})
    assert fund_tools.refresh_fund.invoke({"fund_code": "110011"})["navs_inserted"] == 5


def test_all_tools_aggregate_has_11_unique():
    names = [t.name for t in fund_tools.ALL_TOOLS]
    assert len(names) == 11
    assert len(set(names)) == 11  # no name collisions
    assert set(names) == {
        "get_latest_fund_nav", "calculate_fund_metrics", "get_fund_basic_info",
        "get_fund_nav_history", "refresh_fund", "get_watchlist",
        "add_fund_to_watchlist", "remove_fund_from_watchlist", "update_fund_note",
        "get_market_indices", "refresh_market"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_tools.py -v`
Expected: FAIL — `AttributeError`/`module has no attribute 'get_fund_basic_info'` and `ALL_TOOLS`.

- [ ] **Step 3: Append new tools + aggregates to `backend/tools/fund_tools.py`**

Add after the existing `TOOLS = [...]` line (keep that line as-is):

```python
from backend.tools.watchlist_tools import WATCHLIST_TOOLS
from backend.tools.market_tools import MARKET_TOOLS


@tool
def get_fund_basic_info(fund_code: str) -> dict:
    """获取基金基础信息：名称、类型、经理、公司（来自本地库，需先 refresh_fund）。"""
    return fs.get_basic_info(fund_code)


@tool
def get_fund_nav_history(fund_code: str, start_date: str = "", end_date: str = "") -> dict:
    """获取基金带日期的历史净值序列，支持可选区间（YYYY-MM-DD，空=不限）。

    返回 {fund_code, navs:[{nav_date, accumulated_nav, daily_return}], count, source, as_of}。
    """
    return fs.get_nav_history(fund_code, start_date=start_date, end_date=end_date)


@tool
def refresh_fund(fund_code: str) -> dict:
    """联网拉取一只基金的最新基础信息与净值并入本地库。返回 {fund_code, navs_inserted, source, as_of}。"""
    return fs.refresh_fund(fund_code)


FUND_TOOLS = [get_latest_fund_nav, calculate_fund_metrics,
              get_fund_basic_info, get_fund_nav_history, refresh_fund]

ALL_TOOLS = FUND_TOOLS + WATCHLIST_TOOLS + MARKET_TOOLS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_tools.py -v`
Expected: PASS — all tool tests green (phase-1 + Task 4 + Task 5).

- [ ] **Step 5: Run the FULL offline suite (regression gate)**

Run: `.venv/bin/python -m pytest backend/tests -v`
Expected: PASS — phase-1's 26 + phase-3 new tests, 0 failures.

- [ ] **Step 6: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/tools/fund_tools.py backend/tests/test_tools.py
git commit -m "feat: add fund query/refresh tools and ALL_TOOLS aggregate"
```

## Self-Review (completed during planning)

- **Spec coverage:** §2 11-tool list → Tasks 4 (6 tools) + 5 (3 new fund tools + 2 existing aggregated); §4 contracts → Tasks 1/2/3 service returns match field-for-field; §5 three new service methods → Tasks 1 (2) + 2 (1); §6 file structure → file table + Tasks 3/4/5 (watchlist_service added & justified); §7 testing → every task offline (in-memory SQLite for services, monkeypatch for tools); §8 acceptance → Task 5 Step 3 (`ALL_TOOLS` 11 unique) + Step 5 (full suite). All covered.
- **Placeholder scan:** no TBD/TODO/vague steps; every code step has full code.
- **Type consistency:** service names (`get_basic_info`, `get_nav_history`, `get_indices`, `list_watchlist`/`add`/`remove`/`update_note`) consistent between definition (Tasks 1/2/3) and tool wrappers (Tasks 4/5). Tool `.name` values consistent between creation and the `ALL_TOOLS` assertion set in Task 5. `note or None` bridges tool empty-string default to repository's `note=None` default.





