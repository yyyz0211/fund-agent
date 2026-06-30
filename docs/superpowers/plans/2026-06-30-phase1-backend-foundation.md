# Phase 1: Backend Foundation + Thin Agent Slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic fund-data backend (SQLAlchemy + AKShare + metrics) plus one thin LangChain agent slice proving "agent calls tool, gets deterministic result".

**Architecture:** Pure-Python backend, no web layer. SQLAlchemy ORM over SQLite. Service functions are written "tool-ready" (structured, serializable output, `source`/`as_of` stamps, LLM-readable errors). A minimal `deepseek-chat` tool-calling agent wraps two services as LangChain tools. Numbers are computed by deterministic Python; the LLM only orchestrates and explains.

**Tech Stack:** Python, SQLAlchemy, AKShare, pandas, pydantic-settings, langchain, langchain-openai (DeepSeek), pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-phase1-backend-foundation-design.md`
- DeepSeek via OpenAI-compatible API: `base_url=https://api.deepseek.com`, `model=deepseek-chat` (NEVER `deepseek-reasoner` — no tool support).
- API key from env `DEEPSEEK_API_KEY` only. Never hardcode. Repo ships `.env.example` (key names only); `.env` is gitignored.
- All service return functions: JSON-serializable output, each datum carries `source` and `as_of`; failures return LLM-readable `{"error": "..."}` dicts — never raw exceptions or None.
- Metrics computed by deterministic Python only, never by the LLM. Metrics use accumulated NAV.
- Agent must never emit buy/sell advice; system prompt encodes compliance boundary.
- DB connection string lives only in `db/session.py` (SQLite now, PG later).
- TDD: failing test first, minimal impl, frequent commits.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `backend/requirements.txt` | Pinned dependencies |
| `backend/.env.example` | Key-name placeholders only |
| `backend/config/settings.py` | pydantic-settings; reads env |
| `backend/db/session.py` | engine + SessionLocal; connection string (only place) |
| `backend/db/models.py` | 4 SQLAlchemy ORM models |
| `backend/db/init_db.py` | `create_all` |
| `backend/db/repository.py` | Session-based reads/writes incl. watchlist CRUD |
| `backend/services/metric_service.py` | Deterministic metrics (pure, offline-testable) |
| `backend/services/data_collector.py` | AKShare fetch + retry + source stamping |
| `backend/services/fund_service.py` | Tool-ready fund info/nav facade |
| `backend/services/market_service.py` | Tool-ready market index facade |
| `backend/tools/fund_tools.py` | 2 LangChain `@tool` wrappers |
| `backend/agent/thin_agent.py` | Minimal langchain tool-calling agent |
| `backend/scripts/smoke_fetch.py` | Manual real-fetch verification |
| `backend/tests/test_metrics.py` | Metric unit tests (constructed data) |
| `backend/tests/test_repository.py` | Watchlist CRUD tests (in-memory SQLite) |

---

### Task 1: Project scaffolding, dependencies, settings

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/.env.example`
- Create: `backend/config/__init__.py`
- Create: `backend/config/settings.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_settings.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `Settings` class with attrs `deepseek_api_key: str | None`, `deepseek_base_url: str` (default `https://api.deepseek.com`), `deepseek_model: str` (default `deepseek-chat`), `database_url: str` (default `sqlite:///backend/data/fund_agent.db`); module-level `get_settings() -> Settings` (cached).

- [ ] **Step 1: Create `backend/requirements.txt`**

```
langchain>=0.3,<0.4
langchain-openai>=0.2,<0.3
akshare>=1.14
pandas>=2.0
pydantic-settings>=2.0
SQLAlchemy>=2.0,<3.0
pytest>=8.0
```

- [ ] **Step 2: Create `backend/.env.example`** (key names only, no real values)

```
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite:///backend/data/fund_agent.db
```

- [ ] **Step 3: Create empty `backend/config/__init__.py` and `backend/tests/__init__.py`**

Both files empty.

- [ ] **Step 4: Write the failing test** in `backend/tests/test_settings.py`

```python
from backend.config.settings import get_settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.deepseek_base_url == "https://api.deepseek.com"
    assert s.deepseek_model == "deepseek-chat"
    assert s.deepseek_api_key is None


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    get_settings.cache_clear()
    assert get_settings().deepseek_api_key == "sk-test"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` for `backend.config.settings`.

- [ ] **Step 6: Write minimal implementation** in `backend/config/settings.py`

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    database_url: str = "sqlite:///backend/data/fund_agent.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_settings.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/requirements.txt backend/.env.example backend/config backend/tests/__init__.py backend/tests/test_settings.py
git commit -m "feat: scaffold backend with settings and deps"
```

### Task 2: SQLAlchemy models, session, init_db

**Files:**
- Create: `backend/db/__init__.py`
- Create: `backend/db/session.py`
- Create: `backend/db/models.py`
- Create: `backend/db/init_db.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: `get_settings()` from Task 1.
- Produces:
  - `db/session.py`: `Base` (DeclarativeBase), `make_engine(url: str | None = None)`, `SessionLocal` (sessionmaker bound to default engine), `get_session() -> Session`.
  - `db/models.py`: ORM classes `Fund`, `Watchlist`, `FundNav`, `MarketData` with columns per spec §5.
  - `db/init_db.py`: `init_db(engine=None) -> None` calling `Base.metadata.create_all`.

- [ ] **Step 1: Create empty `backend/db/__init__.py`**

- [ ] **Step 2: Create `backend/db/session.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config.settings import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Session:
    return SessionLocal()
```

- [ ] **Step 3: Write the failing test** in `backend/tests/test_models.py`

```python
from sqlalchemy import inspect

from backend.db.session import Base, make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401  (register models on Base)


def test_tables_created():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    names = set(inspect(engine).get_table_names())
    assert {"funds", "watchlist", "fund_nav", "market_data"} <= names


def test_fund_nav_unique_constraint():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("fund_nav")}
    assert {"fund_code", "nav_date", "unit_nav", "accumulated_nav",
            "daily_return", "source", "source_updated_at"} <= cols
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError` for `backend.db.models` / `backend.db.init_db`.

- [ ] **Step 5: Create `backend/db/models.py`**

```python
from datetime import datetime

from sqlalchemy import (DateTime, Float, Integer, String, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base


class Fund(Base):
    __tablename__ = "funds"
    fund_code: Mapped[str] = mapped_column(String, primary_key=True)
    fund_name: Mapped[str | None] = mapped_column(String)
    fund_type: Mapped[str | None] = mapped_column(String)
    manager: Mapped[str | None] = mapped_column(String)
    company: Mapped[str | None] = mapped_column(String)
    inception_date: Mapped[str | None] = mapped_column(String)
    risk_level: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Watchlist(Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("fund_code", name="uq_watchlist_fund"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String, index=True)
    is_holding: Mapped[bool] = mapped_column(default=False)
    is_focus: Mapped[bool] = mapped_column(default=False)
    holding_amount: Mapped[float | None] = mapped_column(Float)
    holding_share: Mapped[float | None] = mapped_column(Float)
    cost_nav: Mapped[float | None] = mapped_column(Float)
    buy_date: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FundNav(Base):
    __tablename__ = "fund_nav"
    __table_args__ = (UniqueConstraint("fund_code", "nav_date", name="uq_nav_fund_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String, index=True)
    nav_date: Mapped[str] = mapped_column(String, index=True)
    unit_nav: Mapped[float | None] = mapped_column(Float)
    accumulated_nav: Mapped[float | None] = mapped_column(Float)
    daily_return: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String)
    source_updated_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MarketData(Base):
    __tablename__ = "market_data"
    __table_args__ = (UniqueConstraint("symbol", "market_date", name="uq_market_symbol_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_date: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    close: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 6: Create `backend/db/init_db.py`**

```python
from backend.db.session import Base, engine as default_engine
import backend.db.models  # noqa: F401  (register models)


def init_db(engine=None) -> None:
    Base.metadata.create_all(engine or default_engine)


if __name__ == "__main__":
    import os
    os.makedirs("backend/data", exist_ok=True)
    init_db()
    print("Tables created.")
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/db backend/tests/test_models.py
git commit -m "feat: add SQLAlchemy models, session, init_db"
```

### Task 3: Deterministic metric service

**Files:**
- Create: `backend/services/__init__.py`
- Create: `backend/services/metric_service.py`
- Create: `backend/tests/test_metrics.py`

**Interfaces:**
- Consumes: nothing (pure functions over plain lists).
- Produces (all take `navs: list[float]` of accumulated NAV ordered oldest→newest; trading-day based):
  - `daily_returns(navs) -> list[float]` — period-over-period returns, length `len(navs)-1`.
  - `cumulative_return(navs) -> float | None` — `navs[-1]/navs[0]-1`; `None` if `<2` points.
  - `max_drawdown(navs) -> float | None` — most negative peak-to-trough, `<=0`; `None` if `<2`.
  - `volatility(navs, annualize=True, periods_per_year=252) -> float | None` — stdev of daily returns (sample, ddof=1), annualized by `*sqrt(periods_per_year)`; `None` if `<3` navs.
  - `period_return(navs, period) -> float | None` — `period in {"1w","1m","3m","6m","1y"}`; uses last N trading rows where N = {1w:5, 1m:21, 3m:63, 6m:126, 1y:252}; `None` if insufficient.
- Naming is FINAL — later tasks import exactly these.

- [ ] **Step 1: Create empty `backend/services/__init__.py`**

- [ ] **Step 2: Write the failing test** in `backend/tests/test_metrics.py`

```python
import math
import pytest
from backend.services import metric_service as m


def test_cumulative_return():
    assert m.cumulative_return([1.0, 1.1, 1.21]) == pytest.approx(0.21)
    assert m.cumulative_return([2.0]) is None


def test_daily_returns():
    r = m.daily_returns([1.0, 1.1, 1.21])
    assert r == pytest.approx([0.1, 0.1])


def test_max_drawdown():
    # peak 1.2 then trough 0.9 => -0.25
    assert m.max_drawdown([1.0, 1.2, 0.9, 1.0]) == pytest.approx(-0.25)
    assert m.max_drawdown([1.0, 1.1, 1.2]) == pytest.approx(0.0)
    assert m.max_drawdown([1.0]) is None


def test_volatility():
    navs = [1.0, 1.1, 1.21, 1.331]  # constant 10% daily return -> 0 stdev
    assert m.volatility(navs) == pytest.approx(0.0, abs=1e-9)
    assert m.volatility([1.0, 1.1]) is None  # <3 navs -> <2 returns


def test_volatility_known_value():
    navs = [1.0, 1.1, 0.99]
    dr = m.daily_returns(navs)
    mean = sum(dr) / len(dr)
    expected_std = (sum((x - mean) ** 2 for x in dr) / (len(dr) - 1)) ** 0.5
    assert m.volatility(navs, annualize=False) == pytest.approx(expected_std)
    assert m.volatility(navs) == pytest.approx(expected_std * math.sqrt(252))


def test_period_return():
    navs = [1.0 + i * 0.01 for i in range(0, 30)]  # 30 ascending points
    assert m.period_return(navs, "1w") == pytest.approx(navs[-1] / navs[-6] - 1)
    assert m.period_return(navs, "1y") is None  # needs 252+1
    with pytest.raises(ValueError):
        m.period_return(navs, "2y")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError` for metric functions.

- [ ] **Step 4: Write minimal implementation** in `backend/services/metric_service.py`

```python
import math

_PERIOD_ROWS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126, "1y": 252}


def daily_returns(navs: list[float]) -> list[float]:
    return [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]


def cumulative_return(navs: list[float]) -> float | None:
    if len(navs) < 2:
        return None
    return navs[-1] / navs[0] - 1


def max_drawdown(navs: list[float]) -> float | None:
    if len(navs) < 2:
        return None
    peak = navs[0]
    worst = 0.0
    for v in navs:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def volatility(navs: list[float], annualize: bool = True,
               periods_per_year: int = 252) -> float | None:
    dr = daily_returns(navs)
    if len(dr) < 2:
        return None
    mean = sum(dr) / len(dr)
    var = sum((x - mean) ** 2 for x in dr) / (len(dr) - 1)
    std = math.sqrt(var)
    return std * math.sqrt(periods_per_year) if annualize else std


def period_return(navs: list[float], period: str) -> float | None:
    if period not in _PERIOD_ROWS:
        raise ValueError(f"unsupported period: {period}")
    n = _PERIOD_ROWS[period]
    if len(navs) < n + 1:
        return None
    window = navs[-(n + 1):]
    return window[-1] / window[0] - 1
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_metrics.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/services/__init__.py backend/services/metric_service.py backend/tests/test_metrics.py
git commit -m "feat: add deterministic metric service with unit tests"
```

### Task 4: Repository (watchlist CRUD + fund/nav persistence)

**Files:**
- Create: `backend/db/repository.py`
- Create: `backend/tests/test_repository.py`

**Interfaces:**
- Consumes: `Session` from Task 2; models `Fund`, `Watchlist`, `FundNav`, `MarketData`.
- Produces (all take `session: Session` as first arg):
  - `add_to_watchlist(session, fund_code, note=None) -> dict` — idempotent; returns row as dict.
  - `remove_from_watchlist(session, fund_code) -> bool` — True if a row was deleted.
  - `update_watchlist_note(session, fund_code, note) -> dict | None`.
  - `get_watchlist(session) -> list[dict]`.
  - `upsert_fund(session, fund: dict) -> None` — insert or update by `fund_code`.
  - `upsert_navs(session, fund_code, rows: list[dict]) -> int` — rows have keys `nav_date, unit_nav, accumulated_nav, daily_return, source, source_updated_at`; skip existing `(fund_code, nav_date)`; return inserted count.
  - `get_accumulated_navs(session, fund_code) -> list[float]` — ordered oldest→newest, accumulated_nav only.

- [ ] **Step 1: Write the failing test** in `backend/tests/test_repository.py`

```python
import pytest
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker
from backend.db import repository as repo


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    s = Local()
    yield s
    s.close()


def test_watchlist_crud(session):
    row = repo.add_to_watchlist(session, "110011", note="hold")
    assert row["fund_code"] == "110011"
    assert repo.add_to_watchlist(session, "110011")["fund_code"] == "110011"  # idempotent
    assert len(repo.get_watchlist(session)) == 1
    repo.update_watchlist_note(session, "110011", "watch")
    assert repo.get_watchlist(session)[0]["note"] == "watch"
    assert repo.remove_from_watchlist(session, "110011") is True
    assert repo.remove_from_watchlist(session, "110011") is False
    assert repo.get_watchlist(session) == []


def test_upsert_navs_dedup_and_read(session):
    rows = [
        {"nav_date": "2026-06-01", "unit_nav": 1.0, "accumulated_nav": 2.0,
         "daily_return": 0.0, "source": "akshare", "source_updated_at": "2026-06-30"},
        {"nav_date": "2026-06-02", "unit_nav": 1.1, "accumulated_nav": 2.1,
         "daily_return": 0.05, "source": "akshare", "source_updated_at": "2026-06-30"},
    ]
    assert repo.upsert_navs(session, "110011", rows) == 2
    assert repo.upsert_navs(session, "110011", rows) == 0  # dedup
    assert repo.get_accumulated_navs(session, "110011") == [2.0, 2.1]


def test_upsert_fund(session):
    repo.upsert_fund(session, {"fund_code": "110011", "fund_name": "FundA"})
    repo.upsert_fund(session, {"fund_code": "110011", "fund_name": "FundA v2"})
    from backend.db.models import Fund
    assert session.get(Fund, "110011").fund_name == "FundA v2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_repository.py -v`
Expected: FAIL — `ModuleNotFoundError` for `backend.db.repository`.

- [ ] **Step 3: Write implementation** in `backend/db/repository.py`

```python
from sqlalchemy import select

from backend.db.models import Fund, Watchlist, FundNav


def _watchlist_to_dict(w: Watchlist) -> dict:
    return {"id": w.id, "fund_code": w.fund_code, "is_holding": w.is_holding,
            "is_focus": w.is_focus, "holding_amount": w.holding_amount,
            "holding_share": w.holding_share, "cost_nav": w.cost_nav,
            "buy_date": w.buy_date, "note": w.note}


def add_to_watchlist(session, fund_code: str, note: str | None = None) -> dict:
    existing = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if existing:
        return _watchlist_to_dict(existing)
    w = Watchlist(fund_code=fund_code, note=note)
    session.add(w)
    session.commit()
    return _watchlist_to_dict(w)


def remove_from_watchlist(session, fund_code: str) -> bool:
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return False
    session.delete(w)
    session.commit()
    return True


def update_watchlist_note(session, fund_code: str, note: str) -> dict | None:
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return None
    w.note = note
    session.commit()
    return _watchlist_to_dict(w)


def get_watchlist(session) -> list[dict]:
    rows = session.scalars(select(Watchlist).order_by(Watchlist.id)).all()
    return [_watchlist_to_dict(w) for w in rows]


def upsert_fund(session, fund: dict) -> None:
    obj = session.get(Fund, fund["fund_code"])
    if obj is None:
        session.add(Fund(**fund))
    else:
        for k, v in fund.items():
            if k != "fund_code":
                setattr(obj, k, v)
    session.commit()


def upsert_navs(session, fund_code: str, rows: list[dict]) -> int:
    existing = set(session.scalars(
        select(FundNav.nav_date).where(FundNav.fund_code == fund_code)).all())
    inserted = 0
    for r in rows:
        if r["nav_date"] in existing:
            continue
        session.add(FundNav(fund_code=fund_code, **r))
        inserted += 1
    session.commit()
    return inserted


def get_accumulated_navs(session, fund_code: str) -> list[float]:
    rows = session.scalars(
        select(FundNav.accumulated_nav)
        .where(FundNav.fund_code == fund_code)
        .order_by(FundNav.nav_date)).all()
    return [float(x) for x in rows if x is not None]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_repository.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/db/repository.py backend/tests/test_repository.py
git commit -m "feat: add repository with watchlist CRUD and nav persistence"
```

### Task 5: AKShare data collector with retry

**Files:**
- Create: `backend/services/data_collector.py`
- Create: `backend/tests/test_data_collector.py`

**Interfaces:**
- Consumes: nothing from other tasks (wraps AKShare + pandas).
- Produces:
  - `with_retry(fn, *args, retries=3, base_delay=0.5, sleep=time.sleep, **kwargs)` — calls `fn`, retries on exception with exponential backoff, re-raises last exception after `retries` attempts. `sleep` injectable for tests.
  - `today_str() -> str` — `YYYY-MM-DD` for stamping `as_of`.
  - `fetch_fund_info(fund_code) -> dict` — `{fund_code, fund_name, fund_type, manager, company, source, as_of}`. On failure returns `{"error": "...", "source": "akshare"}`.
  - `fetch_fund_nav_history(fund_code) -> list[dict] | dict` — rows `{nav_date, unit_nav, accumulated_nav, daily_return, source, source_updated_at}` ascending by date. On failure returns `{"error": "...", "source": "akshare"}`.
  - `fetch_market_indices() -> list[dict] | dict` — rows `{symbol, name, category, close, change_pct, market_date, source}`. On failure returns `{"error": "...", "source": "akshare"}`.
- NOTE for implementer: AKShare column names are Chinese and occasionally shift. Wrap each parse in try/except; on any parse error return the error dict. The retry wrapper is unit-tested; live AKShare parsing is validated by `scripts/smoke_fetch.py` (Task 8), not by networked unit tests.

- [ ] **Step 1: Write the failing test** in `backend/tests/test_data_collector.py` (retry logic only — no network)

```python
import pytest
from backend.services import data_collector as dc


def test_with_retry_succeeds_first_try():
    calls = []
    def ok():
        calls.append(1)
        return "ok"
    assert dc.with_retry(ok, sleep=lambda _: None) == "ok"
    assert len(calls) == 1


def test_with_retry_retries_then_succeeds():
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("transient")
        return "ok"
    assert dc.with_retry(flaky, retries=3, sleep=lambda _: None) == "ok"
    assert len(calls) == 3


def test_with_retry_exhausts_and_raises():
    def always_fail():
        raise RuntimeError("nope")
    with pytest.raises(RuntimeError):
        dc.with_retry(always_fail, retries=3, sleep=lambda _: None)


def test_today_str_format():
    s = dc.today_str()
    assert len(s) == 10 and s[4] == "-" and s[7] == "-"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_data_collector.py -v`
Expected: FAIL — `ModuleNotFoundError` for `backend.services.data_collector`.

- [ ] **Step 3: Write implementation** in `backend/services/data_collector.py`

```python
import time
from datetime import date

SOURCE = "akshare"


def today_str() -> str:
    return date.today().isoformat()


def with_retry(fn, *args, retries: int = 3, base_delay: float = 0.5,
               sleep=time.sleep, **kwargs):
    last = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — collector boundary, re-raised below
            last = e
            if attempt < retries - 1:
                sleep(base_delay * (2 ** attempt))
    raise last


def fetch_fund_info(fund_code: str) -> dict:
    try:
        import akshare as ak
        df = with_retry(ak.fund_individual_info_em, fund_code)
        kv = dict(zip(df["item"], df["value"])) if "item" in df.columns \
            else dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
        return {
            "fund_code": fund_code,
            "fund_name": kv.get("基金简称") or kv.get("基金名称"),
            "fund_type": kv.get("基金类型"),
            "manager": kv.get("基金经理"),
            "company": kv.get("基金管理人") or kv.get("基金公司"),
            "source": SOURCE,
            "as_of": today_str(),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_fund_info failed for {fund_code}: {e}", "source": SOURCE}


def fetch_fund_nav_history(fund_code: str) -> list[dict] | dict:
    try:
        import akshare as ak
        df = with_retry(ak.fund_open_fund_info_em, fund_code, indicator="累计净值走势")
        out = []
        prev = None
        for _, r in df.iterrows():
            acc = float(r["累计净值"])
            dr = (acc / prev - 1) if prev not in (None, 0) else 0.0
            out.append({
                "nav_date": str(r["净值日期"]),
                "unit_nav": None,
                "accumulated_nav": acc,
                "daily_return": dr,
                "source": SOURCE,
                "source_updated_at": today_str(),
            })
            prev = acc
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_fund_nav_history failed for {fund_code}: {e}", "source": SOURCE}


_INDEX_SYMBOLS = {"000300": ("沪深300", "index"),
                  "000001": ("上证指数", "index"),
                  "399001": ("深证成指", "index")}


def fetch_market_indices() -> list[dict] | dict:
    try:
        import akshare as ak
        df = with_retry(ak.stock_zh_index_spot_em)
        out = []
        for _, r in df.iterrows():
            code = str(r.get("代码", ""))
            if code in _INDEX_SYMBOLS:
                name, cat = _INDEX_SYMBOLS[code]
                out.append({
                    "symbol": code, "name": name, "category": cat,
                    "close": float(r["最新价"]),
                    "change_pct": float(r["涨跌幅"]),
                    "market_date": today_str(), "source": SOURCE,
                })
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_market_indices failed: {e}", "source": SOURCE}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_data_collector.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/services/data_collector.py backend/tests/test_data_collector.py
git commit -m "feat: add AKShare data collector with retry"
```

### Task 6: Tool-ready fund & market services

**Files:**
- Create: `backend/services/fund_service.py`
- Create: `backend/services/market_service.py`
- Create: `backend/tests/test_fund_service.py`

**Interfaces:**
- Consumes: `repository` (Task 4), `data_collector` (Task 5), `metric_service` (Task 3), `get_session` (Task 2).
- Produces:
  - `fund_service.refresh_fund(fund_code, session=None) -> dict` — fetch info + nav history via collector, upsert to DB; returns `{"fund_code", "navs_inserted", "source", "as_of"}` or `{"error": ...}`.
  - `fund_service.get_latest_nav(fund_code, session=None) -> dict` — from DB; `{"fund_code", "nav_date", "accumulated_nav", "source", "as_of"}` or `{"error": "no nav data for <code>; call refresh_fund first"}`.
  - `fund_service.get_metrics(fund_code, period="1m", session=None) -> dict` — reads accumulated navs from DB, computes via metric_service; `{"fund_code", "period", "cumulative_return"|"period_return", "max_drawdown", "volatility", "source", "as_of"}` or error dict if no data.
  - `market_service.refresh_market(session=None) -> dict` — fetch indices, upsert; `{"inserted", "source", "as_of"}` or error.
- All accept optional `session`; when None, open one via `get_session()` and close it. Tests pass an in-memory session.

- [ ] **Step 1: Write the failing test** in `backend/tests/test_fund_service.py` (collector monkeypatched — no network)

```python
import pytest
from backend.db.session import make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401
from sqlalchemy.orm import sessionmaker
from backend.services import fund_service as fs
from backend.services import data_collector as dc


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


def test_get_latest_nav_no_data(session):
    out = fs.get_latest_nav("110011", session=session)
    assert "error" in out


def test_refresh_then_latest_and_metrics(session, monkeypatch):
    monkeypatch.setattr(dc, "fetch_fund_info", lambda c: {
        "fund_code": c, "fund_name": "FundA", "fund_type": "混合型",
        "manager": "X", "company": "Y", "source": "akshare", "as_of": "2026-06-30"})
    navs = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 11)]
    monkeypatch.setattr(dc, "fetch_fund_nav_history", lambda c: navs)

    r = fs.refresh_fund("110011", session=session)
    assert r["navs_inserted"] == 10

    latest = fs.get_latest_nav("110011", session=session)
    assert latest["accumulated_nav"] == pytest.approx(1.10)
    assert latest["source"] == "akshare"

    m = fs.get_metrics("110011", period="1w", session=session)
    assert m["max_drawdown"] is not None
    assert m["source"] == "akshare"


def test_refresh_propagates_collector_error(session, monkeypatch):
    monkeypatch.setattr(dc, "fetch_fund_info", lambda c: {
        "fund_code": c, "source": "akshare", "as_of": "2026-06-30"})
    monkeypatch.setattr(dc, "fetch_fund_nav_history",
                        lambda c: {"error": "boom", "source": "akshare"})
    out = fs.refresh_fund("110011", session=session)
    assert "error" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_fund_service.py -v`
Expected: FAIL — `ModuleNotFoundError` for `backend.services.fund_service`.

- [ ] **Step 3: Write `backend/services/fund_service.py`**

```python
from backend.db.session import get_session
from backend.db import repository as repo
from backend.services import data_collector as dc
from backend.services import metric_service as metrics


def _with_session(session):
    return session or get_session()


def refresh_fund(fund_code: str, session=None) -> dict:
    s = _with_session(session)
    owns = session is None
    try:
        info = dc.fetch_fund_info(fund_code)
        if isinstance(info, dict) and "error" in info:
            return info
        repo.upsert_fund(s, {k: info.get(k) for k in
                             ("fund_code", "fund_name", "fund_type", "manager", "company")})
        navs = dc.fetch_fund_nav_history(fund_code)
        if isinstance(navs, dict) and "error" in navs:
            return navs
        inserted = repo.upsert_navs(s, fund_code, navs)
        return {"fund_code": fund_code, "navs_inserted": inserted,
                "source": dc.SOURCE, "as_of": dc.today_str()}
    finally:
        if owns:
            s.close()


def get_latest_nav(fund_code: str, session=None) -> dict:
    s = _with_session(session)
    owns = session is None
    try:
        from sqlalchemy import select
        from backend.db.models import FundNav
        row = s.scalars(select(FundNav).where(FundNav.fund_code == fund_code)
                        .order_by(FundNav.nav_date.desc())).first()
        if row is None:
            return {"error": f"no nav data for {fund_code}; call refresh_fund first",
                    "source": dc.SOURCE}
        return {"fund_code": fund_code, "nav_date": row.nav_date,
                "accumulated_nav": row.accumulated_nav,
                "source": row.source or dc.SOURCE, "as_of": row.source_updated_at}
    finally:
        if owns:
            s.close()


def get_metrics(fund_code: str, period: str = "1m", session=None) -> dict:
    s = _with_session(session)
    owns = session is None
    try:
        navs = repo.get_accumulated_navs(s, fund_code)
        if len(navs) < 2:
            return {"error": f"insufficient nav data for {fund_code}; call refresh_fund first",
                    "source": dc.SOURCE}
        return {
            "fund_code": fund_code,
            "period": period,
            "period_return": metrics.period_return(navs, period),
            "cumulative_return": metrics.cumulative_return(navs),
            "max_drawdown": metrics.max_drawdown(navs),
            "volatility": metrics.volatility(navs),
            "source": dc.SOURCE,
            "as_of": dc.today_str(),
        }
    finally:
        if owns:
            s.close()
```

- [ ] **Step 4: Write `backend/services/market_service.py`**

```python
from backend.db.session import get_session
from backend.db.models import MarketData
from backend.services import data_collector as dc
from sqlalchemy import select


def refresh_market(session=None) -> dict:
    s = session or get_session()
    owns = session is None
    try:
        rows = dc.fetch_market_indices()
        if isinstance(rows, dict) and "error" in rows:
            return rows
        existing = {(r.symbol, r.market_date) for r in
                    s.scalars(select(MarketData)).all()}
        inserted = 0
        for r in rows:
            if (r["symbol"], r["market_date"]) in existing:
                continue
            s.add(MarketData(**r))
            inserted += 1
        s.commit()
        return {"inserted": inserted, "source": dc.SOURCE, "as_of": dc.today_str()}
    finally:
        if owns:
            s.close()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_fund_service.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/services/fund_service.py backend/services/market_service.py backend/tests/test_fund_service.py
git commit -m "feat: add tool-ready fund and market services"
```

### Task 7: LangChain tools + thin DeepSeek agent

**Files:**
- Create: `backend/tools/__init__.py`
- Create: `backend/tools/fund_tools.py`
- Create: `backend/agent/__init__.py`
- Create: `backend/agent/thin_agent.py`
- Create: `backend/tests/test_tools.py`

**Interfaces:**
- Consumes: `fund_service` (Task 6); `get_settings` (Task 1).
- Produces:
  - `fund_tools.get_latest_fund_nav` — LangChain tool (via `@tool`), arg `fund_code: str`, returns the `fund_service.get_latest_nav` dict.
  - `fund_tools.calculate_fund_metrics` — LangChain tool, args `fund_code: str, period: str = "1m"`, returns `fund_service.get_metrics` dict.
  - `fund_tools.TOOLS: list` — `[get_latest_fund_nav, calculate_fund_metrics]`.
  - `agent/thin_agent.py`: `SYSTEM_PROMPT: str` (compliance boundary); `build_agent()` — returns a LangChain tool-calling agent executor using `ChatOpenAI(model=settings.deepseek_model, base_url=settings.deepseek_base_url, api_key=settings.deepseek_api_key)`; raises `RuntimeError` with a clear message if `deepseek_api_key` is None; `ask(question: str) -> str`.
- Tool unit tests invoke the tools' underlying functions directly with a monkeypatched `fund_service` — NO LLM, NO network.

- [ ] **Step 1: Write the failing test** in `backend/tests/test_tools.py`

```python
from backend.tools import fund_tools
from backend.services import fund_service as fs


def test_latest_nav_tool_invokes_service(monkeypatch):
    monkeypatch.setattr(fs, "get_latest_nav",
                        lambda code, session=None: {"fund_code": code,
                                                    "accumulated_nav": 1.23,
                                                    "source": "akshare"})
    out = fund_tools.get_latest_fund_nav.invoke({"fund_code": "110011"})
    assert out["accumulated_nav"] == 1.23
    assert out["source"] == "akshare"


def test_metrics_tool_invokes_service(monkeypatch):
    monkeypatch.setattr(fs, "get_metrics",
                        lambda code, period="1m", session=None: {
                            "fund_code": code, "period": period,
                            "max_drawdown": -0.08, "source": "akshare"})
    out = fund_tools.calculate_fund_metrics.invoke(
        {"fund_code": "110011", "period": "1m"})
    assert out["max_drawdown"] == -0.08


def test_tools_list_exposes_both():
    names = {t.name for t in fund_tools.TOOLS}
    assert names == {"get_latest_fund_nav", "calculate_fund_metrics"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError` for `backend.tools.fund_tools`.

- [ ] **Step 3: Create empty `backend/tools/__init__.py` and `backend/agent/__init__.py`**

- [ ] **Step 4: Write `backend/tools/fund_tools.py`**

```python
from langchain_core.tools import tool

from backend.services import fund_service as fs


@tool
def get_latest_fund_nav(fund_code: str) -> dict:
    """获取指定基金的最新净值（来自本地库，需先 refresh）。返回含 source 与 as_of。"""
    return fs.get_latest_nav(fund_code)


@tool
def calculate_fund_metrics(fund_code: str, period: str = "1m") -> dict:
    """计算基金区间指标：阶段收益、最大回撤、波动率。period ∈ {1w,1m,3m,6m,1y}。"""
    return fs.get_metrics(fund_code, period=period)


TOOLS = [get_latest_fund_nav, calculate_fund_metrics]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_tools.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Write `backend/agent/thin_agent.py`**

```python
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.config.settings import get_settings
from backend.tools.fund_tools import TOOLS

SYSTEM_PROMPT = (
    "你是个人基金市场信息助手，不是投资顾问。"
    "你只能提供公开信息整理、历史数据分析和风险提示。"
    "你不能给出买入、卖出、持有、加仓、减仓、申购、赎回等建议，不预测或承诺收益。"
    "所有数字必须来自工具返回结果，不得自行编造或心算。"
    "回答时附上数据来源(source)与日期(as_of)。"
    "若工具返回 error，请如实说明数据缺失，不要编造数据。"
)


def build_agent() -> AgentExecutor:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 未配置。请在 backend/.env 中设置后重试。")
    llm = ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=0,
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    agent = create_tool_calling_agent(llm, TOOLS, prompt)
    return AgentExecutor(agent=agent, tools=TOOLS, verbose=True)


def ask(question: str) -> str:
    executor = build_agent()
    result = executor.invoke({"input": question})
    return result["output"]
```

- [ ] **Step 7: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/tools backend/agent backend/tests/test_tools.py
git commit -m "feat: add LangChain tools and thin DeepSeek agent"
```

### Task 8: Smoke script, README, full-suite verification

**Files:**
- Create: `backend/scripts/__init__.py`
- Create: `backend/scripts/smoke_fetch.py`
- Create: `backend/README.md`

**Interfaces:**
- Consumes: `init_db` (Task 2), `fund_service` (Task 6), `market_service` (Task 6), `thin_agent.ask` (Task 7).
- Produces: a runnable manual-verification script and developer docs. No new unit tests; this task validates the live AKShare path and the whole suite.

- [ ] **Step 1: Create empty `backend/scripts/__init__.py`**

- [ ] **Step 2: Write `backend/scripts/smoke_fetch.py`** (manual, real network — run by hand)

```python
"""Manual smoke test: real AKShare fetch + DB + thin agent.

Usage:
    cd /Users/leon/fund-agent
    python -m backend.scripts.smoke_fetch 110011
Requires backend/.env with DEEPSEEK_API_KEY for the agent step (optional).
"""
import os
import sys

from backend.db.init_db import init_db
from backend.services import fund_service as fs
from backend.services import market_service as ms


def main(fund_code: str) -> None:
    os.makedirs("backend/data", exist_ok=True)
    init_db()

    print(f"[1] refresh_fund({fund_code}) ...")
    print("   ", fs.refresh_fund(fund_code))

    print("[2] get_latest_nav ...")
    print("   ", fs.get_latest_nav(fund_code))

    print("[3] get_metrics(period=1m) ...")
    print("   ", fs.get_metrics(fund_code, period="1m"))

    print("[4] refresh_market ...")
    print("   ", ms.refresh_market())

    print("[5] thin agent (skipped if no DEEPSEEK_API_KEY) ...")
    try:
        from backend.agent.thin_agent import ask
        print("   ", ask(f"基金 {fund_code} 最新净值是多少？近一个月最大回撤呢？"))
    except RuntimeError as e:
        print("    skipped:", e)


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "110011"
    main(code)
```

- [ ] **Step 3: Write `backend/README.md`**

````markdown
# Fund Agent — Backend (Phase 1)

Deterministic fund-data backend + thin LangChain/DeepSeek agent slice.

## Setup

```bash
cd /Users/leon/fund-agent
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then put your DEEPSEEK_API_KEY in backend/.env
```

## Initialize the database

```bash
python -m backend.db.init_db
```

## Run tests (offline)

```bash
python -m pytest backend/tests -v
```

## Manual smoke test (live AKShare + agent)

```bash
python -m backend.scripts.smoke_fetch 110011
```

## Boundaries

Information assistant only — no buy/sell advice, no return predictions, no trading.
Numbers come from deterministic Python tools; the LLM only orchestrates and explains.
````

- [ ] **Step 4: Run the FULL offline test suite**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests -v`
Expected: PASS — all tests from Tasks 1–7 green (settings, models, metrics, repository, data_collector, fund_service, tools).

- [ ] **Step 5: Initialize DB and run the live smoke test by hand**

Run: `cd /Users/leon/fund-agent && python -m backend.db.init_db && python -m backend.scripts.smoke_fetch 110011`
Expected: steps [1]–[4] print dicts with real `accumulated_nav` and metric values (no `error` keys); step [5] either prints an agent answer citing source/date, or "skipped" if no API key. If AKShare column parsing fails, fix the column names in `data_collector.py` per the real DataFrame and re-run.

- [ ] **Step 6: Commit**

```bash
cd /Users/leon/fund-agent
git add backend/scripts backend/README.md
git commit -m "feat: add smoke script and backend README"
```

## Self-Review (completed during planning)

- **Spec coverage:** §2 scope → Tasks 1–7; §3 module structure → file table + all tasks; §4 tool-ready convention → Tasks 5/6 error dicts + Task 6 source/as_of; §5 four tables → Task 2; §6 data flow → Tasks 6/7; §7 error handling → Task 5 retry + service error dicts + Task 7 missing-key guard; §8 LLM (deepseek-chat, env key) → Tasks 1/7; §9 testing → Tasks 3/4/5/6/7 offline + Task 8 smoke; §10 acceptance → Task 8 full suite + smoke; §11 deps → Task 1. All covered.
- **Placeholder scan:** no TBD/TODO/"handle edge cases"; every code step has full code.
- **Type consistency:** metric fn names (`daily_returns`, `cumulative_return`, `max_drawdown`, `volatility`, `period_return`) consistent across Tasks 3/6; repo fn names consistent across Tasks 4/6; tool names (`get_latest_fund_nav`, `calculate_fund_metrics`) consistent across Tasks 7. `accumulated_nav` field name consistent across Tasks 2/4/5/6.








