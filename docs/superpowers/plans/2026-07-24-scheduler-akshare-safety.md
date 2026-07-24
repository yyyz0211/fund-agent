# Scheduler and AkShare Safety Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 恢复 Scheduler 的同步公开契约，移除两处绕过 AkShare 全局串行保护的线程 fan-out，并删除无法在线程中可靠工作的 signal 假超时。

**Architecture:** APScheduler 继续使用 `BackgroundScheduler` 的同步生命周期；所有 AkShare 入口继续由一个进程级锁串行化；基金刷新与画像采集在调用线程按确定顺序执行；`with_retry(timeout=...)` 只保留兼容参数并明确不提供硬取消。

**Tech Stack:** Python 3.11、FastAPI、APScheduler BackgroundScheduler、AkShare、pytest、同步 SQLAlchemy。

## Global Constraints

- 这是第一阶段的前置单元，必须先于原子 Watchlist 切片和共享 Fund Refresh 切片完成。
- 当前索引中已经有用户暂存修改，且与 `backend/api/app.py`、`backend/scheduler/runtime.py`、`backend/services/fund/fund_service.py`、`backend/services/market/data_collector.py` 重叠。开始实现前必须先由工作区所有者把这些修改提交到独立 checkpoint、移到安全的独立工作区，或明确归入本单元；仅把它们从 index 退回 worktree 仍然不安全。四个目标文件的 staged/unstaged diff 都归零前不得开始实现，也不得用整文件 `git add` 混入无关修改。
- 只修改下列目标 hunk；保留 `backend/api/app.py` 中现有异常处理和启动流程的其他变化，保留 `fund_service.py`、`data_collector.py` 中与本计划无关的用户修改。
- `start_scheduler()` 与 `shutdown_scheduler()` 必须保持同步函数；不得使用 `asyncio.to_thread()` 包装。
- `shutdown(wait=False)` 只表示 shutdown 调用不等待，不宣称能够终止已经运行的 job。
- AkShare 单并发是安全约束。不得在外层持有 `AKSHARE_LOCK` 时创建调用 AkShare 的子线程，也不得给 profile 内部五个 raw AkShare 调用再次套同一个非重入锁。
- 不引入 `multiprocessing`、`ProcessPoolExecutor`、subprocess、`asyncio.wait_for(to_thread(...))` 或新的线程池。
- 不删除 `market_index_history_timeout_seconds` 配置键；本单元只把其说明改为兼容保留，待未来存在可注入 HTTP transport 时再赋予真实 I/O timeout 语义。
- 五个 profile 数据源恢复串行后，总耗时可能变为各源耗时之和。这是恢复可信安全基线的有意代价。
- 每个任务按 RED → GREEN 执行；逻辑提交只有在重叠的用户暂存修改已被安全分离后才能创建。

---

## File Map

**Modify**

- `backend/scheduler/runtime.py` — 恢复同步 Scheduler 生命周期。
- `backend/api/app.py` — startup/shutdown hook 直接同步调用 lifecycle API。
- `backend/services/fund/fund_service.py` — NAV 与基础信息按调用线程串行收集。
- `backend/services/market/data_collector.py` — profile 串行采集、锁边界指标、诚实的 timeout 兼容语义。
- `backend/config/settings.py` — 把旧 timeout 字段注释改为兼容保留。
- `backend/tests/test_scheduler_contract.py` — 同步签名和 FastAPI 接线契约。
- `backend/tests/test_fund_service.py` — 删除已失效的并行行为测试及 `Event` import。
- `backend/tests/test_service_transaction_boundaries.py` — 无数据库的 Fund 收集顺序与异常兼容测试。
- `backend/tests/test_data_collector.py` — profile 串行、部分失败和锁指标测试。
- `backend/tests/test_with_retry_timeout.py` — signal 不可用与 worker 安全行为测试。
- `backend/tests/test_data_collector_index_history.py` — index caller 不再传伪 deadline。
- `backend/tests/test_data_collector_sector_history.py` — sector caller 不再传伪 deadline。

**Verify without modifying**

- `backend/scheduler/__init__.py` — 包级 lifecycle re-export 仍指向 runtime。
- `backend/tests/test_scheduler_runtime.py` — 现有六个同步生命周期测试。
- `backend/tests/test_scheduler_briefing.py` — 现有 Scheduler/Briefing 生产接线测试。

**Do not modify**

- Watchlist Application/Route/Feature。
- Fund Refresh Application。
- SQLAlchemy engine/session 模式。
- Scheduler job registry、cron 配置或 job 行为。

---

### Task 1: Record the failing baseline and reconcile the dirty index

**Files:**

- Inspect: `backend/api/app.py`
- Inspect: `backend/scheduler/runtime.py`
- Inspect: `backend/services/fund/fund_service.py`
- Inspect: `backend/services/market/data_collector.py`

- [ ] **Step 1: Capture the current staged and unstaged overlap**

Run:

```bash
git status --short
git diff --cached -- backend/api/app.py backend/scheduler/runtime.py \
  backend/services/fund/fund_service.py \
  backend/services/market/data_collector.py
git diff -- backend/api/app.py backend/scheduler/runtime.py \
  backend/services/fund/fund_service.py \
  backend/services/market/data_collector.py
```

Expected: the four target files are reported as overlapping current work. Save this output with the implementation notes. Do not change the index until the owner has chosen how to preserve those hunks.

After owner reconciliation, rerun the three commands. Required precondition:

```text
git diff --cached                         → empty for the entire index
git diff -- <four target files>           → empty
```

Enforce the index condition:

```bash
if ! git diff --cached --quiet; then
  echo "index still contains user changes; stop before implementation"
  exit 1
fi
```

If either condition is non-empty, stop; do not stage, restore, stash, or commit
those user changes on the worker's behalf.

- [ ] **Step 2: Record the unit baseline**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q backend/tests -m unit
```

Expected before implementation: the six known Scheduler lifecycle tests fail because they receive coroutine objects; the remaining unit tests pass.

- [ ] **Step 3: Record the targeted Scheduler baseline**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  backend/tests/test_scheduler_runtime.py \
  backend/tests/test_scheduler_contract.py \
  backend/tests/test_scheduler_briefing.py
```

Expected before implementation: lifecycle/Briefing tests fail and pytest reports unawaited-coroutine warnings.

---

### Task 2: Restore the synchronous Scheduler lifecycle

**Files:**

- Modify: `backend/tests/test_scheduler_contract.py`
- Modify: `backend/scheduler/runtime.py`
- Modify: `backend/api/app.py`
- Verify: `backend/scheduler/__init__.py`
- Test: `backend/tests/test_scheduler_runtime.py`
- Test: `backend/tests/test_scheduler_briefing.py`

**Interfaces:**

- `start_scheduler` keeps keyword-only `enabled`, `hour`, `minute`, and
  `timezone` parameters and returns `BackgroundScheduler | None`.
- `shutdown_scheduler` accepts no parameters and returns `None`.
- Both are ordinary synchronous functions; the exact implementations are in
  Steps 2–3 below.

- [ ] **Step 1: Add the RED synchronization and production-wiring tests**

Append to `backend/tests/test_scheduler_contract.py`:

```python
def test_scheduler_lifecycle_exports_are_synchronous() -> None:
    import inspect
    import backend.scheduler as scheduler
    from backend.scheduler import runtime

    assert not inspect.iscoroutinefunction(runtime.start_scheduler)
    assert not inspect.iscoroutinefunction(runtime.shutdown_scheduler)
    assert scheduler.start_scheduler is runtime.start_scheduler
    assert scheduler.shutdown_scheduler is runtime.shutdown_scheduler


def test_api_scheduler_hooks_are_registered_synchronously() -> None:
    import importlib
    import inspect

    app_module = importlib.import_module("backend.api.app")
    startup_handlers = [
        handler
        for handler in app_module.app.router.on_startup
        if "start_scheduler" in inspect.getsource(handler)
    ]
    shutdown_handlers = [
        handler
        for handler in app_module.app.router.on_shutdown
        if "shutdown_scheduler" in inspect.getsource(handler)
    ]

    assert len(startup_handlers) == 1
    assert len(shutdown_handlers) == 1
    assert not inspect.iscoroutinefunction(
        startup_handlers[0],
    )
    assert not inspect.iscoroutinefunction(
        shutdown_handlers[0],
    )
```

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  backend/tests/test_scheduler_contract.py::test_scheduler_lifecycle_exports_are_synchronous \
  backend/tests/test_scheduler_contract.py::test_api_scheduler_hooks_are_registered_synchronously
```

Expected when the staged async regression is retained as the implementation
baseline: both tests fail because runtime and FastAPI hooks are coroutine
functions. If the owner instead separated that regression and restored clean
`HEAD`, these tests are already GREEN; keep them as regression coverage and do
not manufacture a production-code change.

- [ ] **Step 2: Restore direct synchronous calls in runtime**

In `backend/scheduler/runtime.py`:

1. Delete `import asyncio`.
2. Change `async def start_scheduler` to `def start_scheduler`.
3. Replace the call and return tail with:

```python
    scheduler.start()
    _scheduler = scheduler
    return scheduler
```

4. Replace the shutdown function with:

```python
def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
```

Do not change trigger construction, setting resolution, registration order, idempotency, or `_scheduler` publication timing.

- [ ] **Step 3: Restore synchronous FastAPI hooks without touching unrelated app changes**

Inspect the registered startup handler that contains `start_scheduler()` and
the shutdown handler that contains `shutdown_scheduler()`.

- If the implementation baseline has the async `_start_scheduler` /
  `_stop_scheduler` regression, replace only those two lifecycle functions:

```python
@app.on_event("startup")
def _start_scheduler() -> None:
    """启动 APScheduler 定时任务调度器。"""
    from backend.scheduler import runtime as app_scheduler

    app_scheduler.start_scheduler()


@app.on_event("shutdown")
def _stop_scheduler() -> None:
    """进程退出时停止调度器,避免后台线程泄漏。"""
    from backend.scheduler import runtime as app_scheduler

    app_scheduler.shutdown_scheduler()
```

- If the implementation baseline is clean `HEAD`, keep the existing synchronous
  `_ensure_schema()` startup handler and `_stop_scheduler()` shutdown handler
  unchanged. `_ensure_schema()` also initializes schema and recovers jobs; do
  not rename it or replace it with a scheduler-only hook.
- In either branch, the registered handlers must be ordinary `def` functions
  and must call the synchronous scheduler API directly, with no `await` or
  `asyncio.to_thread()`.

- [ ] **Step 4: Run the GREEN lifecycle suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -W error::RuntimeWarning -q \
  backend/tests/test_scheduler_runtime.py \
  backend/tests/test_scheduler_contract.py \
  backend/tests/test_scheduler_briefing.py
```

Expected GREEN: all tests pass and no unawaited-coroutine warning is emitted.

- [ ] **Step 5: Create the logical checkpoint**

After the owner has separated pre-existing staged hunks, commit only the Scheduler lifecycle and its tests:

```bash
git add backend/scheduler/runtime.py backend/api/app.py \
  backend/tests/test_scheduler_contract.py
git diff --cached --name-status
git diff --cached --check
git diff --check
git commit --only -m "fix: restore synchronous scheduler lifecycle" -- \
  backend/scheduler/runtime.py backend/api/app.py \
  backend/tests/test_scheduler_contract.py
```

Expected: the staged name list contains exactly the three listed paths and the
commit contains only the lifecycle hunk and contract tests. If the current
branch already has the desired runtime/app code in `HEAD`, stage and commit only
the new contract test; record the reconciliation instead of manufacturing a
no-op production change.

---

### Task 3: Serialize basic/NAV and profile AkShare collection

**Files:**

- Modify: `backend/tests/test_service_transaction_boundaries.py`
- Modify: `backend/tests/test_fund_service.py`
- Modify: `backend/tests/test_data_collector.py`
- Modify: `backend/services/fund/fund_service.py`
- Modify: `backend/services/market/data_collector.py`

- [ ] **Step 1: Add the RED basic/NAV call-order tests**

Add `import pytest` if absent, then append to `backend/tests/test_service_transaction_boundaries.py`:

```python
@pytest.mark.unit
def test_collect_refresh_data_fetches_nav_then_info_on_caller_thread(
    monkeypatch,
) -> None:
    import threading
    from backend.services.fund import fund_service as service

    caller_thread = threading.get_ident()
    calls: list[tuple[str, str, int]] = []
    navs = [{"nav_date": "2026-07-24", "accumulated_nav": 1.23}]
    info = {"fund_code": "110011", "fund_name": "Test"}

    def fetch_nav(code: str):
        calls.append(("nav", code, threading.get_ident()))
        return navs

    def fetch_info(code: str):
        calls.append(("info", code, threading.get_ident()))
        return info

    monkeypatch.setattr(service.dc, "fetch_fund_nav_history", fetch_nav)
    monkeypatch.setattr(service.dc, "fetch_fund_info", fetch_info)

    assert service._collect_refresh_data("110011") == (navs, info)
    assert calls == [
        ("nav", "110011", caller_thread),
        ("info", "110011", caller_thread),
    ]


@pytest.mark.unit
def test_collect_refresh_data_preserves_independent_error_payloads(
    monkeypatch,
) -> None:
    from backend.services.fund import fund_service as service

    calls: list[str] = []

    def fail_nav(_code: str):
        calls.append("nav")
        raise RuntimeError("nav boom")

    def fail_info(_code: str):
        calls.append("info")
        raise ValueError("info boom")

    monkeypatch.setattr(service.dc, "fetch_fund_nav_history", fail_nav)
    monkeypatch.setattr(service.dc, "fetch_fund_info", fail_info)

    navs, info = service._collect_refresh_data("110011")

    assert calls == ["nav", "info"]
    assert navs == {
        "error": "fetch_fund_nav_history failed for 110011: nav boom",
        "source": service.dc.SOURCE,
    }
    assert info == {
        "error": "fetch_fund_info failed for 110011: info boom",
        "source": service.dc.SOURCE,
    }
```

Delete `test_refresh_collector_starts_nav_and_info_in_parallel` and its unused `Event` import from `backend/tests/test_fund_service.py`.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  backend/tests/test_service_transaction_boundaries.py::test_collect_refresh_data_fetches_nav_then_info_on_caller_thread \
  backend/tests/test_service_transaction_boundaries.py::test_collect_refresh_data_preserves_independent_error_payloads
```

Expected RED: the caller-thread assertion fails while the executor implementation is present.

- [ ] **Step 2: Replace the basic/NAV executor with deterministic serial collection**

Delete from `backend/services/fund/fund_service.py`:

```python
from concurrent.futures import ThreadPoolExecutor
```

Delete:

```python
_REFRESH_FETCH_WORKERS = 2
```

Replace `_collect_refresh_data` with:

```python
def _collect_refresh_data(
    fund_code: str,
) -> tuple[list[dict] | dict, dict]:
    """按 NAV、基础信息顺序读取；写库仍由 refresh_fund 完成。"""
    try:
        navs = dc.fetch_fund_nav_history(fund_code)
    except Exception as exc:  # noqa: BLE001
        navs = _collector_error(
            "fetch_fund_nav_history",
            fund_code,
            exc,
        )

    try:
        info = dc.fetch_fund_info(fund_code)
    except Exception as exc:  # noqa: BLE001
        info = _collector_error(
            "fetch_fund_info",
            fund_code,
            exc,
        )

    return navs, info
```

- [ ] **Step 3: Add the RED five-source profile tests**

Append to `backend/tests/test_data_collector.py`:

```python
@pytest.mark.unit
def test_collect_profile_frames_runs_all_five_sources_on_caller_thread(
    monkeypatch,
) -> None:
    import threading

    caller_thread = threading.get_ident()
    calls: list[tuple[str, int]] = []

    class FakeAk:
        def record(self, name: str):
            calls.append((name, threading.get_ident()))
            return name

        def fund_scale_change_em(self):
            return self.record("scale")

        def fund_open_fund_rank_em(self, symbol="全部"):
            assert symbol == "全部"
            return self.record("rank")

        def fund_portfolio_hold_em(self, symbol, date):
            assert (symbol, date) == ("110011", "2025")
            return self.record("holdings")

        def fund_portfolio_industry_allocation_em(self, symbol, date):
            assert (symbol, date) == ("110011", "2025")
            return self.record("industry")

        def fund_manager_em(self):
            return self.record("manager")

    monkeypatch.setattr(dc, "ak", FakeAk())
    monkeypatch.setattr(dc, "_profile_year", lambda: "2025")

    frames, missing, errors = dc._collect_profile_frames("110011")

    names = ("scale", "rank", "holdings", "industry", "manager")
    assert frames == {name: name for name in names}
    assert calls == [(name, caller_thread) for name in names]
    assert missing == []
    assert errors == []


@pytest.mark.unit
def test_collect_profile_frames_preserves_partial_failure_contract(
    monkeypatch,
) -> None:
    class FakeAk:
        def fund_scale_change_em(self):
            return "scale"

        def fund_open_fund_rank_em(self, symbol="全部"):
            raise TimeoutError("upstream slow")

        def fund_portfolio_hold_em(self, symbol, date):
            return "holdings"

        def fund_portfolio_industry_allocation_em(self, symbol, date):
            raise RuntimeError("industry boom")

        def fund_manager_em(self):
            return "manager"

    monkeypatch.setattr(dc, "ak", FakeAk())
    monkeypatch.setattr(
        dc,
        "with_retry",
        lambda fn, *args, **kwargs: fn(*args, **kwargs),
    )

    frames, missing, errors = dc._collect_profile_frames("110011")

    assert frames == {
        "scale": "scale",
        "holdings": "holdings",
        "manager": "manager",
    }
    assert missing == ["rank", "industry"]
    assert errors == [
        "rank timeout",
        "industry failed: industry boom",
    ]
```

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  backend/tests/test_data_collector.py::test_collect_profile_frames_runs_all_five_sources_on_caller_thread \
  backend/tests/test_data_collector.py::test_collect_profile_frames_preserves_partial_failure_contract
```

Expected RED: the first test observes executor worker thread IDs.

- [ ] **Step 4: Replace profile fan-out with a serial partial-failure loop**

In `backend/services/market/data_collector.py`, delete the profile executor constants and executor imports:

```python
_PROFILE_FETCH_WORKERS = 3
_PROFILE_SOURCE_TIMEOUT_SECONDS = 5.0
```

Replace the executor/futures block at the end of `_collect_profile_frames` with:

```python
    frames: dict[str, object] = {}
    missing: list[str] = []
    errors: list[str] = []

    for key, call in calls.items():
        try:
            frames[key] = call()
        except TimeoutError:
            missing.append(key)
            errors.append(f"{key} timeout")
        except Exception as exc:  # noqa: BLE001
            missing.append(key)
            errors.append(f"{key} failed: {exc}")

    return frames, missing, errors
```

Keep the `calls` insertion order exactly `scale`, `rank`, `holdings`, `industry`, `manager`. Update any test/docstring that still describes these sources as parallel.

- [ ] **Step 5: Add lock wait/call duration and real thread-gauge observability**

Append this test to `backend/tests/test_data_collector.py`:

```python
@pytest.mark.unit
def test_akshare_serial_records_wait_duration_and_thread_gauges(
    monkeypatch,
    caplog,
) -> None:
    ticks = iter((10.0, 10.25, 10.75))
    thread_counts = iter((4, 5))
    monkeypatch.setattr(dc.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        dc.threading,
        "active_count",
        lambda: next(thread_counts),
    )

    @dc._akshare_serial
    def sample_call():
        return "ok"

    with caplog.at_level("INFO", logger=dc.__name__):
        assert sample_call() == "ok"

    record = next(
        item for item in caplog.records
        if getattr(item, "akshare_call", None) == "sample_call"
    )
    assert record.akshare_lock_wait_seconds == pytest.approx(0.25)
    assert record.akshare_call_seconds == pytest.approx(0.50)
    assert record.akshare_threads_before == 4
    assert record.akshare_threads_after == 5
    assert record.akshare_thread_delta == 1
```

Replace `_akshare_serial` with:

```python
def _akshare_serial(fn):
    """串行调用 AkShare 并记录等待、耗时与进程线程变化。"""
    def wrapper(*args, **kwargs):
        wait_started = time.monotonic()
        threads_before = threading.active_count()
        with AKSHARE_LOCK:
            call_started = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                finished = time.monotonic()
                threads_after = threading.active_count()
                _logger.info(
                    "akshare call completed",
                    extra={
                        "akshare_call": fn.__name__,
                        "akshare_lock_wait_seconds": (
                            call_started - wait_started
                        ),
                        "akshare_call_seconds": finished - call_started,
                        "akshare_threads_before": threads_before,
                        "akshare_threads_after": threads_after,
                        "akshare_thread_delta": (
                            threads_after - threads_before
                        ),
                    },
                )
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper
```

The thread fields are observed process gauges, not a claim that the module can
identify every unrelated executor thread. Zero AkShare executor ownership is
enforced separately by the structural gate in Task 5; do not hard-code a
`worker_fanout=0` runtime metric.

Add `@pytest.mark.unit` to the existing
`test_fetch_announcements_serializes_concurrent_calls` test. It is the true
contended regression that proves four concurrent callers still enter the raw
AkShare API serially.

- [ ] **Step 6: Run the serial-safety GREEN suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  backend/tests/test_service_transaction_boundaries.py::test_collect_refresh_data_fetches_nav_then_info_on_caller_thread \
  backend/tests/test_service_transaction_boundaries.py::test_collect_refresh_data_preserves_independent_error_payloads \
  backend/tests/test_data_collector.py::test_collect_profile_frames_runs_all_five_sources_on_caller_thread \
  backend/tests/test_data_collector.py::test_collect_profile_frames_preserves_partial_failure_contract \
  backend/tests/test_data_collector.py::test_akshare_serial_records_wait_duration_and_thread_gauges \
  backend/tests/test_data_collector.py::test_fetch_announcements_serializes_concurrent_calls \
  backend/tests/test_data_collector.py::test_fetch_fund_profile_parses_profile_sources \
  backend/tests/test_data_collector.py::test_fetch_fund_profile_degrades_when_source_fails
```

Expected GREEN: all tests pass; partial failures retain ordered `missing/errors`.

- [ ] **Step 7: Create the logical checkpoint**

After separating pre-existing staged hunks:

```bash
git add backend/services/fund/fund_service.py \
  backend/services/market/data_collector.py \
  backend/tests/test_fund_service.py \
  backend/tests/test_service_transaction_boundaries.py \
  backend/tests/test_data_collector.py
git diff --cached --name-status
git diff --cached --check
git diff --check
git commit --only -m "fix: serialize AkShare fund collection" -- \
  backend/services/fund/fund_service.py \
  backend/services/market/data_collector.py \
  backend/tests/test_fund_service.py \
  backend/tests/test_service_transaction_boundaries.py \
  backend/tests/test_data_collector.py
```

Expected: only serial collection, lock metrics, and their tests are included.

---

### Task 4: Remove signal-based fake timeout and retain a safe compatibility parameter

**Files:**

- Modify: `backend/tests/test_with_retry_timeout.py`
- Modify: `backend/tests/test_data_collector_index_history.py`
- Modify: `backend/tests/test_data_collector_sector_history.py`
- Modify: `backend/services/market/data_collector.py`
- Modify: `backend/config/settings.py`

- [ ] **Step 1: Replace the old SIGALRM test with RED compatibility tests**

Replace `backend/tests/test_with_retry_timeout.py` with:

```python
"""with_retry timeout 兼容参数的线程安全行为。"""
from concurrent.futures import ThreadPoolExecutor
import logging
import signal

import pytest

from backend.services.market import data_collector as dc


pytestmark = pytest.mark.unit


def test_timeout_argument_does_not_install_signal_handlers(
    monkeypatch,
    caplog,
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("with_retry must not install process signal handlers")

    monkeypatch.setattr(signal, "signal", forbidden)
    monkeypatch.setattr(signal, "setitimer", forbidden)

    with caplog.at_level(logging.WARNING, logger=dc.__name__):
        result = dc.with_retry(lambda: "ok", timeout=0.05)

    assert result == "ok"
    assert "not enforced" in caplog.text
    assert "HTTP transport" in caplog.text


def test_timeout_argument_is_safe_in_worker_thread():
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            dc.with_retry,
            lambda: "ok",
            timeout=0.05,
        )

    assert future.result() == "ok"


def test_without_timeout_preserves_retry_behavior():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = dc.with_retry(
        fn,
        retries=3,
        base_delay=0,
        sleep=lambda _: None,
        timeout=None,
    )

    assert result == "ok"
    assert calls["count"] == 3
```

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q backend/tests/test_with_retry_timeout.py
```

Expected RED: current code calls `signal.signal` and the worker test raises `ValueError`.

- [ ] **Step 2: Add caller tests proving no fake whole-call deadline is passed**

Append to `backend/tests/test_data_collector_index_history.py`:

```python
def test_fetch_index_history_does_not_pass_whole_call_timeout(
    monkeypatch,
):
    captured: dict = {}

    def fake_with_retry(fn, *args, **kwargs):
        captured.update(kwargs)
        return _fake_daily_df()

    monkeypatch.setattr(dc, "with_retry", fake_with_retry)

    result = dc.fetch_index_history("000300", days=5)

    assert isinstance(result, list)
    assert "timeout" not in captured
```

Append to `backend/tests/test_data_collector_sector_history.py`:

```python
def test_fetch_sector_history_does_not_pass_whole_call_timeout(
    monkeypatch,
):
    captured: dict = {}

    def fake_with_retry(fn, *args, **kwargs):
        captured.update(kwargs)
        return _fake_sector_df()

    monkeypatch.setattr(dc, "with_retry", fake_with_retry)

    result = dc.fetch_sector_history("电子", kind="industry", days=5)

    assert isinstance(result, list)
    assert "timeout" not in captured
```

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  backend/tests/test_data_collector_index_history.py::test_fetch_index_history_does_not_pass_whole_call_timeout \
  backend/tests/test_data_collector_sector_history.py::test_fetch_sector_history_does_not_pass_whole_call_timeout
```

Expected RED: both callers currently pass `timeout=market_index_history_timeout_seconds`.

- [ ] **Step 3: Replace signal timeout with warning-only compatibility semantics**

Delete `import signal`, `_with_retry_and_timeout`, and all `SIGALRM`/`setitimer` logic from `backend/services/market/data_collector.py`.

Replace `with_retry` with:

```python
def with_retry(
    fn,
    *args,
    retries: int = 3,
    base_delay: float = 0.5,
    sleep=time.sleep,
    timeout: float | None = None,
    **kwargs,
):
    """重试同步调用。

    timeout 仅为兼容旧调用保留，不是可终止的整段调用截止时间。
    HTTP connect/read timeout 必须在可注入 transport 边界设置。
    """
    if timeout is not None and timeout > 0:
        _logger.warning(
            "with_retry timeout=%s is compatibility-only and not enforced; "
            "configure timeout at the HTTP transport boundary",
            timeout,
        )

    last: Exception | None = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                sleep(base_delay * (2 ** attempt))

    assert last is not None
    raise last
```

In `fetch_index_history` and `fetch_sector_history`, remove only:

```python
timeout=get_settings().market_index_history_timeout_seconds
```

Then remove the now-unused `get_settings` import from `data_collector.py`.

- [ ] **Step 4: Clarify the compatibility-only setting**

In `backend/config/settings.py`, replace the existing comment above the field with:

```python
    # 兼容保留：当前 AkShare API 不暴露可注入 HTTP transport，
    # 因此不能把该值当作可终止的整段同步调用 deadline。
    market_index_history_timeout_seconds: float = 5.0
```

Do not rename or delete the setting.

- [ ] **Step 5: Run the GREEN timeout suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  backend/tests/test_with_retry_timeout.py \
  backend/tests/test_data_collector_index_history.py \
  backend/tests/test_data_collector_sector_history.py
```

Expected GREEN: no signal handler is installed, worker invocation succeeds, retries remain unchanged, and production callers do not pass the compatibility timeout.

- [ ] **Step 6: Create the logical checkpoint**

After separating pre-existing staged hunks:

```bash
git add backend/services/market/data_collector.py \
  backend/config/settings.py \
  backend/tests/test_with_retry_timeout.py \
  backend/tests/test_data_collector_index_history.py \
  backend/tests/test_data_collector_sector_history.py
git diff --cached --name-status
git diff --cached --check
git diff --check
git commit --only -m "fix: make AkShare timeout semantics honest" -- \
  backend/services/market/data_collector.py \
  backend/config/settings.py \
  backend/tests/test_with_retry_timeout.py \
  backend/tests/test_data_collector_index_history.py \
  backend/tests/test_data_collector_sector_history.py
```

---

### Task 5: Verify the complete safety baseline

**Files:**

- Verify: all files in this plan.

- [ ] **Step 1: Run structural gates**

Run:

```bash
if rg -n \
  'async def (start_scheduler|shutdown_scheduler)|await .*start_scheduler|await .*shutdown_scheduler|asyncio\.to_thread' \
  backend/scheduler backend/api/app.py; then
  echo "unexpected async Scheduler lifecycle"
  exit 1
fi
```

Expected: the guard exits 0 without printing a match.

Run:

```bash
if rg -n \
  'ThreadPoolExecutor|future\.result|cancel_futures|_PROFILE_FETCH_WORKERS|_PROFILE_SOURCE_TIMEOUT_SECONDS|_REFRESH_FETCH_WORKERS' \
  backend/services/fund/fund_service.py \
  backend/services/market/data_collector.py; then
  echo "unexpected AkShare worker fan-out"
  exit 1
fi
```

Expected: the guard exits 0 without printing a match.

Run:

```bash
if rg -n \
  'SIGALRM|setitimer|_with_retry_and_timeout|multiprocessing|ProcessPoolExecutor' \
  backend/services/market/data_collector.py; then
  echo "unexpected fake cancellation or process isolation"
  exit 1
fi
```

Expected: the guard exits 0 without printing a match.

- [ ] **Step 2: Run the complete unit partition**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q backend/tests -m unit
```

Expected: the six documented Scheduler failures are gone and no Scheduler `RuntimeWarning` remains.

- [ ] **Step 3: Run static verification**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q backend
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 4: Run the PostgreSQL regression when the disposable test DB is available**

Run:

```bash
DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q backend/tests -n 2 \
  -m "not unit and not db_multiconnection and not db_ddl and not db_pgvector"
```

Expected: all selected tests pass. The database name must end with `_test`; never substitute a development or production database.

- [ ] **Step 5: Review the final diff against scope**

Run:

```bash
git status --short
git log --oneline --stat HEAD~3..HEAD
git diff --stat HEAD~3..HEAD
git diff --check HEAD~3..HEAD
git diff HEAD~3..HEAD
```

Expected: the three checkpoint commits contain only files named by Tasks 2–4;
the full range introduces no Watchlist Feature, Fund Refresh Application,
generic async wrapper, process isolation, or unrelated user file. The final
worktree/index status contains no uncommitted change owned by this plan; any
separately preserved user change remains outside the reviewed commit range.
