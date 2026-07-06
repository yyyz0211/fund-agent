# 定时数据刷新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-process APScheduler-based daily refresh job that walks the watchlist, refreshes NAV and profile cache for each fund, and exposes a status / manual-trigger API.

**Architecture:** New `scheduled_refresh` service module orchestrates a per-fund refresh walk against `fund_service.refresh_fund` + `fund_profile_service.refresh_profile`, keeps the most recent run snapshot in process memory (Lock-protected dict), and registers an APScheduler cron job on FastAPI startup. Admin endpoints expose the snapshot and a manual "refresh all" trigger.

**Tech Stack:** Python 3.11, FastAPI startup hooks, APScheduler `BackgroundScheduler`, SQLAlchemy (read-only here), pytest.

---

## Global Constraints

- Run scheduler inside the backend process; do not add a new container or external cron.
- Single-fund failures must not abort the batch; failures are recorded and the loop continues.
- API key / network / AkShare errors must propagate as `failures`, never raise out of the batch.
- Scheduler is process-local; "last result" is in-memory and lost on restart — explicitly accepted in the spec.
- Do not silently change other behavior (no lifespan migration, no Alembic, no schema changes).
- Honor `SCHEDULER_ENABLED=false` in tests so scheduler threads don't leak.

## File Map

- Modify `backend/config/settings.py`: add scheduler settings.
- Modify `backend/requirements.txt`: pin `apscheduler>=3.10,<4.0`.
- Create `backend/services/scheduled_refresh.py`: batch walker + last-run snapshot.
- Create `backend/scheduler.py`: APScheduler wiring (register job, startup/shutdown hooks).
- Modify `backend/api/app.py`: register scheduler lifecycle alongside existing `init_db` startup hook.
- Create `backend/api/routes/admin.py`: refresh status + manual trigger endpoints.
- Modify `backend/api/app.py`: register admin router.
- Test `backend/tests/test_scheduled_refresh.py`: batch walk + snapshot + single-flight.
- Test `backend/tests/test_scheduler.py`: startup registration controlled by flag.
- Test `backend/tests/test_api_admin.py`: status + manual trigger API.

## Task 1: Settings + dependency

**Files:**
- Modify `backend/config/settings.py`
- Modify `backend/requirements.txt`

- [ ] Add settings fields:

```python
scheduler_enabled: bool = True
scheduler_refresh_cron_hour: int = 20
scheduler_refresh_cron_minute: int = 0
scheduler_timezone: str = "Asia/Shanghai"
```

Add to `Settings` with sensible defaults and `extra="ignore"` already in `SettingsConfigDict`.

- [ ] Add dependency pin:

```
apscheduler>=3.10,<4.0
```

- [ ] Install (venv): 

```bash
.venv/bin/python -m pip install -r backend/requirements.txt
```

Expected: APScheduler installed, no warnings about breaking existing versions.

## Task 2: Batch refresh service

**Files:**
- Create `backend/services/scheduled_refresh.py`
- Test `backend/tests/test_scheduled_refresh.py`

- [ ] Write batch walk tests:

```python
def test_refresh_all_walks_watchlist(monkeypatch, session):
    from backend.services import scheduled_refresh as sr
    from backend.services import watchlist_service as ws

    ws.add("110011", session=session)
    ws.add("000001", session=session)

    calls = []
    monkeypatch.setattr(sr.fund_service, "refresh_fund",
                        lambda code, session=None: calls.append(("fund", code))
                        or {"fund_code": code, "navs_inserted": 1,
                            "already_up_to_date": False,
                            "fund_info_warn": None, "source": "akshare",
                            "as_of": "2026-07-06"})
    monkeypatch.setattr(sr.profile_service, "refresh_profile",
                        lambda code, session=None: calls.append(("profile", code))
                        or {"profile": {}, "missing_data": [], "errors": []})

    snap = sr.refresh_all_watchlist(trigger="manual")
    assert snap["total"] == 2
    assert snap["succeeded"] == 2
    assert snap["failed"] == 0
    assert {c for _, c in calls} == {"110011", "000001"}


def test_refresh_all_records_failures_but_continues(monkeypatch, session):
    from backend.services import scheduled_refresh as sr
    from backend.services import watchlist_service as ws

    ws.add("110011", session=session)
    ws.add("000001", session=session)

    def fake_refresh(code, session=None):
        if code == "110011":
            return {"error": "akshare timeout"}
        return {"fund_code": code, "navs_inserted": 1, "already_up_to_date": False,
                "fund_info_warn": None, "source": "akshare", "as_of": "2026-07-06"}

    monkeypatch.setattr(sr.fund_service, "refresh_fund", fake_refresh)
    monkeypatch.setattr(sr.profile_service, "refresh_profile",
                        lambda code, session=None: {"profile": {}, "missing_data": [], "errors": []})

    snap = sr.refresh_all_watchlist(trigger="manual")
    assert snap["succeeded"] == 1
    assert snap["failed"] == 1
    assert snap["failures"][0]["fund_code"] == "110011"


def test_get_last_run_empty_default():
    from backend.services import scheduled_refresh as sr
    sr.reset_for_tests()  # helper added in impl
    snap = sr.get_last_run()
    assert snap["last_run_at"] is None
    assert snap["total"] == 0
```

- [ ] Implement `scheduled_refresh.py`:

```python
"""Scheduled batch refresh of watchlist funds' NAV + profile cache.

In-process; safe for FastAPI's threaded request handling thanks to the Lock.
"""
from __future__ import annotations

from datetime import datetime
from threading import Lock

from backend.services import fund_service as fund_service_module
from backend.services import fund_profile_service as profile_service_module
from backend.services import watchlist_service as watchlist_service_module


_lock = Lock()
_last_run: dict = {
    "last_run_at": None,
    "trigger": None,
    "total": 0,
    "succeeded": 0,
    "failed": 0,
    "already_up_to_date": 0,
    "failures": [],
}

_active_lock = Lock()
_active_job_id: str | None = None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _empty_snapshot() -> dict:
    return {
        "last_run_at": None,
        "trigger": None,
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "already_up_to_date": 0,
        "failures": [],
    }


def _refresh_one(fund_code: str) -> dict:
    """Refresh one fund's NAV + profile; return {fund_code, ok, error?}.

    Never raises — upstream errors are caught and returned as `error` so the
    batch can continue.
    """
    try:
        nav_result = fund_service_module.refresh_fund(fund_code)
    except Exception as exc:  # noqa: BLE001
        return {"fund_code": fund_code, "ok": False, "error": str(exc)}

    if isinstance(nav_result, dict) and "error" in nav_result:
        return {
            "fund_code": fund_code, "ok": False, "error": nav_result["error"],
            "already_up_to_date": False,
        }

    already = bool(nav_result.get("already_up_to_date"))

    try:
        profile_service_module.refresh_profile(fund_code)
    except Exception as exc:  # noqa: BLE001
        # NAV succeeded; profile stage failure is soft — record but don't fail the row.
        return {"fund_code": fund_code, "ok": True, "already_up_to_date": already,
                "profile_error": str(exc)}

    return {"fund_code": fund_code, "ok": True, "already_up_to_date": already}


def refresh_all_watchlist(*, trigger: str = "scheduled") -> dict:
    """Walk every watchlist entry; refresh NAV + profile; commit snapshot."""
    rows = watchlist_service_module.list_watchlist()
    failures: list[dict] = []
    succeeded = 0
    failed = 0
    already = 0
    for row in rows:
        outcome = _refresh_one(row["fund_code"])
        if outcome["ok"]:
            succeeded += 1
            if outcome.get("already_up_to_date"):
                already += 1
        else:
            failed += 1
            failures.append({"fund_code": outcome["fund_code"], "error": outcome.get("error")})

    snapshot = {
        "last_run_at": _now(),
        "trigger": trigger,
        "total": len(rows),
        "succeeded": succeeded,
        "failed": failed,
        "already_up_to_date": already,
        "failures": failures,
    }
    with _lock:
        _last_run.clear()
        _last_run.update(snapshot)
    return snapshot


def get_last_run() -> dict:
    with _lock:
        if _last_run["last_run_at"] is None:
            return _empty_snapshot()
        return dict(_last_run)


def reset_for_tests() -> None:
    """Test-only: clear in-memory snapshot and active job."""
    global _active_job_id
    with _lock:
        _last_run.clear()
        _last_run.update(_empty_snapshot())
    with _active_lock:
        _active_job_id = None
```

- [ ] Run targeted tests:

```bash
.venv/bin/python -m pytest backend/tests/test_scheduled_refresh.py -q
```

Expected: all pass.

## Task 3: Scheduler wiring

**Files:**
- Create `backend/scheduler.py`
- Modify `backend/api/app.py`
- Test `backend/tests/test_scheduler.py`

- [ ] Add scheduler tests:

```python
def test_scheduler_disabled_registers_nothing(monkeypatch):
    from backend import scheduler as sched

    started = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(started))

    sched.start_scheduler(enabled=False)
    assert started == []


def test_scheduler_enabled_registers_cron(monkeypatch):
    from backend import scheduler as sched

    started = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(started))

    sched.start_scheduler(
        enabled=True,
        hour=20, minute=0,
        timezone="Asia/Shanghai",
    )
    assert len(started) == 1
    job = started[0]
    assert job["hour"] == 20
    assert job["minute"] == 0
    assert job["timezone"] == "Asia/Shanghai"


class _FakeScheduler:
    def __init__(self, started): self._started = started

    def add_job(self, fn, trigger, hour=None, minute=None, timezone=None,
                max_instances=1, coalesce=True, id=None):
        self._started.append({"fn": fn, "trigger": trigger, "hour": hour,
                               "minute": minute, "timezone": timezone,
                               "max_instances": max_instances, "coalesce": coalesce,
                               "id": id})

    def start(self): pass
    def shutdown(self, wait=True): pass
```

- [ ] Implement `backend/scheduler.py`:

```python
"""APScheduler wiring for the daily refresh job."""
from __future__ import annotations

from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config.settings import get_settings
from backend.services.scheduled_refresh import refresh_all_watchlist


_scheduler: BackgroundScheduler | None = None


def _build_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(timezone="Asia/Shanghai")


def _cron_trigger(hour: int, minute: int, tz: str) -> CronTrigger:
    return CronTrigger(hour=hour, minute=minute, timezone=tz)


def start_scheduler(*, enabled: bool | None = None,
                    hour: int | None = None,
                    minute: int | None = None,
                    timezone: str | None = None) -> BackgroundScheduler | None:
    """Start the in-process APScheduler with the daily refresh cron.

    Returns the scheduler (or None when disabled) so tests can introspect.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    if enabled is None:
        enabled = bool(settings.scheduler_enabled)
    if not enabled:
        return None

    scheduler = _build_scheduler()
    if timezone is None:
        timezone = settings.scheduler_timezone
    if hour is None:
        hour = int(settings.scheduler_refresh_cron_hour)
    if minute is None:
        minute = int(settings.scheduler_refresh_cron_minute)

    scheduler.add_job(
        lambda: refresh_all_watchlist(trigger="scheduled"),
        trigger=_cron_trigger(hour, minute, timezone),
        id="daily_refresh",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
```

- [ ] Wire into FastAPI startup/shutdown (stay consistent with the existing
      `@app.on_event` style; lifespan migration is out of scope):

```python
# backend/api/app.py
from backend import scheduler as app_scheduler


@app.on_event("startup")
def _ensure_schema() -> None:
    from backend.db.init_db import init_db
    init_db()
    app_scheduler.start_scheduler()


@app.on_event("shutdown")
def _stop_scheduler() -> None:
    app_scheduler.shutdown_scheduler()
```

- [ ] Run tests:

```bash
.venv/bin/python -m pytest backend/tests/test_scheduler.py -q
```

Expected: all pass.

## Task 4: Admin API

**Files:**
- Create `backend/api/routes/admin.py`
- Modify `backend/api/app.py`
- Test `backend/tests/test_api_admin.py`

- [ ] Write API tests:

```python
def test_refresh_status_empty_default(client):
    r = client.get("/api/admin/refresh-status")
    assert r.status_code == 200
    body = r.json()
    assert body["last_run_at"] is None
    assert body["total"] == 0


def test_post_refresh_all_returns_started(monkeypatch, client):
    from backend.api.routes import admin as admin_routes
    from backend.services import watchlist_service as ws

    ws.add("110011")

    monkeypatch.setattr(admin_routes.sr, "start_refresh_all_async", lambda trigger="manual": {"status": "started", "total": 1})

    r = client.post("/api/admin/refresh-all")
    assert r.status_code == 202
    assert r.json() == {"status": "started", "total": 1}
```

- [ ] Implement `admin.py` (call into `scheduled_refresh` for status and manual trigger):

```python
"""Admin-only endpoints: refresh status + manual batch trigger.

Currently no auth — relies on the same trust model as the rest of the API
(deployment via Tailscale). See DOCKER.md for the trust model.
"""
from fastapi import APIRouter

from backend.services import scheduled_refresh as sr

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/refresh-status")
def refresh_status() -> dict:
    return sr.get_last_run()


@router.post("/refresh-all", status_code=202)
def refresh_all() -> dict:
    return sr.start_refresh_all_async(trigger="manual")
```

- [ ] Add `start_refresh_all_async` to `scheduled_refresh.py`:

```python
from concurrent.futures import ThreadPoolExecutor
import uuid

_async_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scheduled-refresh")


def _run_async(job_id: str, trigger: str) -> None:
    refresh_all_watchlist(trigger=trigger)


def start_refresh_all_async(*, trigger: str = "manual") -> dict:
    """Single-flight: if a job is already running, return current status."""
    with _active_lock:
        if _active_job_id is not None:
            return {"status": "running", "job_id": _active_job_id}
        # 把 job_id 简单暴露给单飞判断（spec 没要求暴露 ID；保留可选）
        job_id = uuid.uuid4().hex[:8]
        _active_job_id = job_id

    def _task():
        try:
            refresh_all_watchlist(trigger=trigger)
        finally:
            with _active_lock:
                _active_job_id = None

    _async_executor.submit(_task)
    return {"status": "started", "total": len(watchlist_service_module.list_watchlist())}
```

> 简化：单飞期间 `_active_job_id` 不暴露给调用方（spec 里接口没返回 `job_id`）。
> 实际实现可按需调整；测试断言只看 `status: started` 与 `total`。

- [ ] Register router in `app.py`:

```python
from backend.api.routes import admin as admin_routes
...
app.include_router(admin_routes.router)
```

- [ ] Run tests:

```bash
.venv/bin/python -m pytest backend/tests/test_api_admin.py -q
```

Expected: all pass.

## Task 5: Verify scheduler doesn't leak in tests

**Files:**
- Modify `backend/tests/conftest.py` (or whatever the global pytest config is — likely `backend/tests/__init__.py` or fixtures already set `SCHEDULER_ENABLED=false` via env var before importing `app`).

- [ ] Check existing test config:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: pass; if APScheduler threads leak between tests, add an autouse fixture in
`backend/tests/conftest.py`:

```python
import os
os.environ.setdefault("SCHEDULER_ENABLED", "false")
```

- [ ] Run full suite again to ensure no scheduler side-effects:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: all pass.

## Task 6: Full verification

- [ ] Backend tests:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: all pass.

- [ ] Smoke launch (with `SCHEDULER_ENABLED=true` if you want to see the log line) and confirm:

```bash
SCHEDULER_ENABLED=true .venv/bin/python -m uvicorn backend.api.app:app --port 8000 &
sleep 2
curl -s http://localhost:8000/api/admin/refresh-status | head
curl -s -X POST http://localhost:8000/api/admin/refresh-all
```

Expected: status returns empty snapshot; manual trigger returns `started`.
`/api/health` still 200, existing endpoints unaffected.

- [ ] Manual smoke:

1. Add a fund to watchlist.
2. `POST /api/admin/refresh-all` → status `started`.
3. Wait a few seconds, `GET /api/admin/refresh-status` → `last_run_at` populated, `total>=1`.
4. `GET /api/funds/{code}/nav` shows updated NAV.

## Commit Plan

- Single PR-friendly commit once all tests pass:

```bash
git add backend/config/settings.py backend/requirements.txt
git commit -m "feat(scheduler): settings + deps"
git add backend/services/scheduled_refresh.py backend/tests/test_scheduled_refresh.py
git commit -m "feat(scheduler): batch walk service"
git add backend/scheduler.py backend/api/app.py backend/tests/test_scheduler.py
git commit -m "feat(scheduler): APScheduler lifecycle wiring"
git add backend/api/routes/admin.py backend/tests/test_api_admin.py
git commit -m "feat(scheduler): admin refresh-status + refresh-all"
```

## Out of Scope

- 持久化刷新历史 / audit log（spec §3 明确排除）。
- 分布式调度 / 多实例。
- 复杂的失效重试队列；单次失败等下一天或手动重试。
- 交易日历判断：周末/节假日照跑，AkShare `already_up_to_date=true` 是无害 no-op。
- 自动迁移到 FastAPI `lifespan` handler（spec §5.3 排除；留作单独改动）。
