# Scheduler Hard Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic imperative Scheduler module with typed specs, named task functions, a declarative registry, and an APScheduler-only runtime, then delete all legacy Scheduler module paths without changing scheduling behavior.

**Architecture:** `backend.scheduler.registry` produces an ordered immutable tuple of `JobSpec` values whose callables come from `task_functions`; `runtime` converts those specs into APScheduler triggers and owns the single process-local scheduler instance. The package root exposes only `start_scheduler`, `get_scheduler`, and `shutdown_scheduler`. The hard cut deletes `scheduler.py` and `jobs.py` and is delivered as one atomic implementation commit after all TDD checkpoints pass.

**Tech Stack:** Python 3.11, dataclasses, APScheduler 3.x, FastAPI lifecycle hooks, pytest, AST contract tests, PostgreSQL 16 + pgvector worker-schema fixtures.

## Global Constraints

- Preserve all nine job IDs, their order, enablement defaults, callable arguments, cron/interval values, timezone behavior, jitter, start delay, `max_instances`, `coalesce`, and `misfire_grace_time`.
- Preserve process singleflight, knowledge job-table behavior, warning/error handling, exception propagation, API health reporting, idempotent startup, and `shutdown(wait=False)`.
- Keep the existing `start_scheduler(*, enabled=None, hour=None, minute=None, timezone=None)` signature and return behavior.
- `backend/scheduler/runtime.py` must not import `backend.services` or `backend.graph`; domain dependencies belong only in `task_functions.py`.
- `backend/scheduler/specs.py` must not import APScheduler, Settings, graph, or service modules.
- Do not add advisory locks, multi-worker election, new retry behavior, task-frequency changes, a DI container, or executor-submit reliability fixes.
- Delete `backend/scheduler/scheduler.py` and `backend/scheduler/jobs.py`; do not retain re-exports, deprecated modules, aliases, or duplicate implementations.
- The package root must export only `start_scheduler`, `get_scheduler`, and `shutdown_scheduler`.
- Database-dependent regression tests must use `TEST_DATABASE_URL` pointing to a disposable PostgreSQL database whose name ends in `_test`.
- Tasks 1–5 are RED/GREEN review checkpoints, not commit boundaries. Create one atomic implementation commit only after Task 6 passes.

---

## File Map

### New production boundary

- `backend/scheduler/specs.py`: immutable `CronSpec`, `IntervalSpec`, and `JobSpec` values.
- `backend/scheduler/task_functions.py`: nine named zero-argument domain task callables and singleflight/error wrappers.
- `backend/scheduler/registry.py`: Settings-to-ordered-`JobSpec` translation.
- `backend/scheduler/runtime.py`: APScheduler trigger conversion, registration, and process lifecycle.

### Package and consumers

- `backend/scheduler/__init__.py`: narrow lifecycle-only public API.
- `backend/api/app.py`: already consumes the package API; keep behavior and verify no internal-module import is introduced.
- `backend/tests/test_api_app.py`: patch live state through `backend.scheduler.runtime` while exercising the package getter.
- `backend/tests/test_scheduler_briefing.py`: use the package lifecycle API and patch task-function dependencies.

### New focused tests

- `backend/tests/test_scheduler_specs.py`: dataclass validation and immutability.
- `backend/tests/test_scheduler_task_functions.py`: domain calls, singleflight, and knowledge job transitions.
- `backend/tests/test_scheduler_registry.py`: complete registration snapshot and enablement rules.
- `backend/tests/test_scheduler_runtime.py`: trigger conversion and lifecycle.
- `backend/tests/test_scheduler_contract.py`: legacy deletion, import direction, and package export guards.

### Deleted legacy files

- `backend/scheduler/scheduler.py`.
- `backend/scheduler/jobs.py`.
- `backend/tests/test_scheduler.py`, after its scheduler coverage is moved and its misplaced market-evidence singleflight case is dropped because `test_market_evidence_service.py::test_refresh_market_evidence_async_is_single_flight` already covers that behavior.
- `backend/tests/test_scheduler_jobs.py`, replaced by typed spec tests.

---

### Task 1: Establish the typed Scheduler spec boundary

**Files:**
- Create: `backend/tests/test_scheduler_specs.py`
- Create: `backend/scheduler/specs.py`

**Interfaces:**
- Produces: `CronSpec(hour: int, minute: int, timezone: str)`.
- Produces: `IntervalSpec(timezone: str, minutes: int | None = None, seconds: int | None = None, jitter: int = 0, start_delay_seconds: int = 0)`.
- Produces: `JobSpec(id: str, callable: Callable[[], object], trigger: CronSpec | IntervalSpec, max_instances: int = 1, coalesce: bool = True, misfire_grace_time: int | None = None)`.

- [ ] **Step 1: Record the pre-change Scheduler baseline**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_scheduler.py \
  backend/tests/test_scheduler_jobs.py \
  backend/tests/test_scheduler_briefing.py \
  backend/tests/test_api_app.py
```

Expected: all selected tests pass. Record the exact count in `.superpowers/sdd/progress.md`; do not commit the ignored ledger.

- [ ] **Step 2: Write failing typed-spec tests**

Create `backend/tests/test_scheduler_specs.py`:

```python
"""Typed Scheduler specification contracts."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest


pytestmark = pytest.mark.unit


def test_interval_spec_requires_exactly_one_interval_unit() -> None:
    from backend.scheduler.specs import IntervalSpec

    with pytest.raises(ValueError, match="exactly one"):
        IntervalSpec(timezone="Asia/Shanghai")
    with pytest.raises(ValueError, match="exactly one"):
        IntervalSpec(
            timezone="Asia/Shanghai",
            minutes=6,
            seconds=360,
        )


def test_scheduler_specs_are_immutable() -> None:
    from backend.scheduler.specs import CronSpec, JobSpec

    trigger = CronSpec(hour=20, minute=0, timezone="Asia/Shanghai")
    spec = JobSpec(id="daily_refresh", callable=lambda: None, trigger=trigger)

    with pytest.raises(FrozenInstanceError):
        trigger.hour = 21  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        spec.id = "changed"  # type: ignore[misc]


def test_job_spec_preserves_registration_defaults() -> None:
    from backend.scheduler.specs import CronSpec, JobSpec

    fn = lambda: None
    spec = JobSpec(
        id="daily_refresh",
        callable=fn,
        trigger=CronSpec(hour=20, minute=0, timezone="Asia/Shanghai"),
    )

    assert spec.callable is fn
    assert spec.max_instances == 1
    assert spec.coalesce is True
    assert spec.misfire_grace_time is None
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q backend/tests/test_scheduler_specs.py
```

Expected: collection or test failure because `backend.scheduler.specs` does not exist. The failure must not be caused by a typo in the test.

- [ ] **Step 4: Implement the immutable specs**

Create `backend/scheduler/specs.py`:

```python
"""Immutable, framework-independent Scheduler specifications."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CronSpec:
    hour: int
    minute: int
    timezone: str


@dataclass(frozen=True, slots=True)
class IntervalSpec:
    timezone: str
    minutes: int | None = None
    seconds: int | None = None
    jitter: int = 0
    start_delay_seconds: int = 0

    def __post_init__(self) -> None:
        if (self.minutes is None) == (self.seconds is None):
            raise ValueError("IntervalSpec requires exactly one interval unit")


@dataclass(frozen=True, slots=True)
class JobSpec:
    id: str
    callable: Callable[[], object]
    trigger: CronSpec | IntervalSpec
    max_instances: int = 1
    coalesce: bool = True
    misfire_grace_time: int | None = None
```

Do not add conversion methods or APScheduler imports; conversion belongs in `runtime.py`.

- [ ] **Step 5: Run the typed-spec tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q backend/tests/test_scheduler_specs.py
```

Expected: `3 passed`.

---

### Task 2: Extract named domain task functions

**Files:**
- Create: `backend/tests/test_scheduler_task_functions.py`
- Create: `backend/scheduler/task_functions.py`

**Interfaces:**
- Consumes: existing fund/market/briefing/knowledge services and `process_singleflight`.
- Produces: nine stable zero-argument functions named in the approved design.
- Produces: no APScheduler objects and no Settings reads.

- [ ] **Step 1: Write failing thin-callable mapping tests**

Create `backend/tests/test_scheduler_task_functions.py` with a parameterized call map:

```python
"""Scheduler domain task-function behavior."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.unit


def test_thin_market_tasks_preserve_domain_arguments(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks

    calls: list[tuple] = []
    monkeypatch.setattr(
        tasks.scheduled_refresh,
        "refresh_all_watchlist",
        lambda *, trigger: calls.append(("refresh", trigger)),
    )
    monkeypatch.setattr(
        tasks.market_intel_service,
        "collect_market_intel",
        lambda session, brief_type: calls.append(
            ("intel", session, brief_type)
        ),
    )
    monkeypatch.setattr(
        tasks.market_evidence_service,
        "refresh_market_evidence_async",
        lambda **kwargs: calls.append(("evidence", kwargs)),
    )

    tasks.run_daily_refresh()
    tasks.run_morning_market_intel()
    tasks.run_post_market_intel()
    tasks.run_pre_market_evidence()
    tasks.run_post_market_evidence()
    tasks.run_post_market_evidence_hourly()

    assert calls == [
        ("refresh", "scheduled"),
        ("intel", None, "morning"),
        ("intel", None, "post_market"),
        ("evidence", {"brief_type": "pre_market", "trigger": "scheduled"}),
        ("evidence", {"brief_type": "post_market", "trigger": "scheduled"}),
        (
            "evidence",
            {"brief_type": "post_market", "trigger": "scheduled_hourly"},
        ),
    ]


def test_daily_briefing_builds_and_injects_model(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks

    model = object()
    calls: list[tuple] = []
    monkeypatch.setattr(tasks, "_build_briefing_model", lambda: model)
    monkeypatch.setattr(
        tasks.briefing_workflow,
        "run_daily_briefing",
        lambda **kwargs: calls.append(("briefing", kwargs)),
    )

    tasks.run_daily_briefing()

    assert calls == [
        ("briefing", {"trigger": "scheduled", "model": model}),
    ]


def test_daily_briefing_skips_only_model_configuration_error(
    monkeypatch,
    caplog,
) -> None:
    from backend.scheduler import task_functions as tasks

    monkeypatch.setattr(
        tasks,
        "_build_briefing_model",
        lambda: (_ for _ in ()).throw(RuntimeError("missing key")),
    )
    monkeypatch.setattr(
        tasks.briefing_workflow,
        "run_daily_briefing",
        lambda **_kwargs: pytest.fail("workflow must be skipped"),
    )

    tasks.run_daily_briefing()

    assert "daily_briefing skipped" in caplog.text
```

- [ ] **Step 2: Add failing singleflight and knowledge transition tests**

Append to the same file:

```python
def test_cls_sync_uses_stable_scheduler_singleflight_key(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks

    calls: list[tuple] = []

    @contextmanager
    def fake_singleflight(key, **kwargs):
        calls.append(("lock", key, kwargs))
        yield

    monkeypatch.setattr(tasks, "process_singleflight", fake_singleflight)
    monkeypatch.setattr(
        tasks.cls_telegraph_sync_service,
        "run_scheduled_cls_telegraph_sync",
        lambda: calls.append(("run",)),
    )

    tasks.run_cls_telegraph_sync()

    assert calls == [
        ("lock", "scheduler.cls_telegraph_sync", {}),
        ("run",),
    ]


def test_cls_sync_skips_when_singleflight_is_busy(monkeypatch, caplog) -> None:
    from backend.scheduler import task_functions as tasks
    from backend.services.shared.process_singleflight import SingleflightBusy

    @contextmanager
    def busy_singleflight(_key, **_kwargs):
        raise SingleflightBusy("busy")
        yield

    monkeypatch.setattr(tasks, "process_singleflight", busy_singleflight)

    tasks.run_cls_telegraph_sync()

    assert "cls_telegraph_sync" in caplog.text
    assert "skipped" in caplog.text


def test_knowledge_task_creates_and_starts_scheduled_job(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks

    calls: list[tuple] = []

    @contextmanager
    def fake_singleflight(key, **kwargs):
        calls.append(("lock", key, kwargs))
        yield

    monkeypatch.setattr(tasks, "process_singleflight", fake_singleflight)
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "create_job",
        lambda *, trigger: calls.append(("create", trigger))
        or SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "run_job_in_background",
        lambda job_id, *, pipeline_kwargs: calls.append(
            ("run", job_id, pipeline_kwargs)
        ),
    )

    tasks.run_knowledge_ingest_index()

    assert calls == [
        (
            "lock",
            "scheduler.knowledge_ingest_index",
            {"timeout_seconds": 2.0},
        ),
        ("create", "scheduled"),
        ("run", 42, {"trigger": "scheduled"}),
    ]


def test_knowledge_task_marks_job_failed_when_background_start_fails(
    monkeypatch,
) -> None:
    from backend.scheduler import task_functions as tasks

    @contextmanager
    def fake_singleflight(_key, **_kwargs):
        yield

    monkeypatch.setattr(tasks, "process_singleflight", fake_singleflight)
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "create_job",
        lambda *, trigger: SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "run_job_in_background",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("submit")),
    )
    failures: list[tuple] = []
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "mark_failed",
        lambda job_id, *, error: failures.append((job_id, error)),
    )

    tasks.run_knowledge_ingest_index()

    assert failures == [(42, "RuntimeError: submit")]
```

- [ ] **Step 3: Run the task-function tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q backend/tests/test_scheduler_task_functions.py
```

Expected: failure because `backend.scheduler.task_functions` does not exist.

- [ ] **Step 4: Implement named task functions by moving existing behavior**

Create `backend/scheduler/task_functions.py`. Import the existing service modules at module scope so tests can patch the composition boundary; keep graph-model construction behind the private function to avoid eager model initialization:

```python
"""Named Scheduler callables at the domain composition boundary."""
from __future__ import annotations

import logging

from backend.services.briefing import workflow as briefing_workflow
from backend.services.knowledge import (
    cls_telegraph_sync_service,
    knowledge_reindex_jobs,
)
from backend.services.market import (
    market_evidence_service,
    market_intel_service,
    scheduled_refresh,
)
from backend.services.shared.process_singleflight import (
    SingleflightBusy,
    process_singleflight,
)


logger = logging.getLogger(__name__)


def _build_briefing_model():
    from backend.graph.model import build_model

    return build_model()


def run_daily_refresh() -> object:
    return scheduled_refresh.refresh_all_watchlist(trigger="scheduled")


def run_daily_briefing() -> object | None:
    try:
        model = _build_briefing_model()
    except RuntimeError as exc:
        logger.warning("[scheduler] daily_briefing skipped: %s", exc)
        return None
    return briefing_workflow.run_daily_briefing(
        trigger="scheduled",
        model=model,
    )


def run_morning_market_intel() -> object:
    return market_intel_service.collect_market_intel(None, "morning")


def run_post_market_intel() -> object:
    return market_intel_service.collect_market_intel(None, "post_market")


def run_pre_market_evidence() -> object:
    return market_evidence_service.refresh_market_evidence_async(
        brief_type="pre_market",
        trigger="scheduled",
    )


def run_post_market_evidence() -> object:
    return market_evidence_service.refresh_market_evidence_async(
        brief_type="post_market",
        trigger="scheduled",
    )


def run_post_market_evidence_hourly() -> object:
    return market_evidence_service.refresh_market_evidence_async(
        brief_type="post_market",
        trigger="scheduled_hourly",
    )


def run_cls_telegraph_sync() -> object | None:
    try:
        with process_singleflight("scheduler.cls_telegraph_sync"):
            return cls_telegraph_sync_service.run_scheduled_cls_telegraph_sync()
    except SingleflightBusy as exc:
        logger.warning(
            "[scheduler] job=cls_telegraph_sync skipped: %s",
            exc,
        )
        return None


def run_knowledge_ingest_index() -> None:
    try:
        with process_singleflight(
            "scheduler.knowledge_ingest_index",
            timeout_seconds=2.0,
        ):
            job = knowledge_reindex_jobs.create_job(trigger="scheduled")
            job_id = int(job.id)
    except SingleflightBusy:
        logger.warning(
            "[scheduler] knowledge_ingest_index skipped: "
            "previous pipeline still finalizing"
        )
        return
    except Exception:
        logger.exception(
            "[scheduler] knowledge pipeline failed to create job record"
        )
        return

    try:
        knowledge_reindex_jobs.run_job_in_background(
            job_id,
            pipeline_kwargs={"trigger": "scheduled"},
        )
    except Exception as exc:
        logger.exception(
            "[scheduler] knowledge pipeline failed to start background job"
        )
        knowledge_reindex_jobs.mark_failed(
            job_id,
            error=f"{type(exc).__name__}: {exc}",
        )
```

Do not introduce a generic retry or advisory lock.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_scheduler_task_functions.py \
  backend/tests/test_briefing_jobs.py \
  backend/tests/test_knowledge_reindex_jobs.py
```

Expected: all selected tests pass.

---

### Task 3: Build the declarative registry and lock the complete snapshot

**Files:**
- Create: `backend/tests/test_scheduler_registry.py`
- Create: `backend/scheduler/registry.py`

**Interfaces:**
- Consumes: `Settings`, `CronSpec`, `IntervalSpec`, `JobSpec`, and the nine named task functions.
- Produces: `build_job_specs(settings: Settings, *, timezone: str, refresh_hour: int, refresh_minute: int) -> tuple[JobSpec, ...]`.

- [ ] **Step 1: Write the full registration snapshot test**

Create `backend/tests/test_scheduler_registry.py`. Use a local `_settings(**overrides)` helper returning `SimpleNamespace` with these defaults:

```python
DEFAULTS = {
    "scheduler_briefing_enabled": True,
    "scheduler_briefing_cron_hour": 17,
    "scheduler_briefing_cron_minute": 0,
    "scheduler_evidence_enabled": True,
    "scheduler_evidence_hourly_enabled": True,
    "scheduler_evidence_hourly_minutes": 60,
    "cls_telegraph_sync_enabled": True,
    "cls_telegraph_sync_interval_seconds": 360,
    "scheduler_knowledge_enabled": True,
    "scheduler_knowledge_interval_minutes": 6,
}
```

The snapshot test must assert the complete ordered tuple, not only membership:

```python
def test_build_job_specs_preserves_complete_registration_snapshot() -> None:
    from backend.scheduler import task_functions as tasks
    from backend.scheduler.registry import build_job_specs
    from backend.scheduler.specs import CronSpec, IntervalSpec

    specs = build_job_specs(
        _settings(),
        timezone="Asia/Shanghai",
        refresh_hour=20,
        refresh_minute=0,
    )

    assert [spec.id for spec in specs] == [
        "daily_refresh",
        "daily_briefing",
        "morning_market_intel",
        "post_market_market_intel",
        "pre_market_evidence",
        "post_market_evidence",
        "post_market_evidence_hourly",
        "cls_telegraph_sync",
        "knowledge_ingest_index",
    ]
    assert [spec.callable for spec in specs] == [
        tasks.run_daily_refresh,
        tasks.run_daily_briefing,
        tasks.run_morning_market_intel,
        tasks.run_post_market_intel,
        tasks.run_pre_market_evidence,
        tasks.run_post_market_evidence,
        tasks.run_post_market_evidence_hourly,
        tasks.run_cls_telegraph_sync,
        tasks.run_knowledge_ingest_index,
    ]
    assert [spec.trigger for spec in specs] == [
        CronSpec(20, 0, "Asia/Shanghai"),
        CronSpec(17, 0, "Asia/Shanghai"),
        CronSpec(9, 35, "Asia/Shanghai"),
        CronSpec(15, 35, "Asia/Shanghai"),
        CronSpec(8, 30, "Asia/Shanghai"),
        CronSpec(16, 0, "Asia/Shanghai"),
        IntervalSpec(
            timezone="Asia/Shanghai",
            minutes=60,
            jitter=60,
        ),
        IntervalSpec(
            timezone="Asia/Shanghai",
            seconds=360,
            jitter=10,
        ),
        IntervalSpec(
            timezone="Asia/Shanghai",
            minutes=6,
            jitter=60,
            start_delay_seconds=30,
        ),
    ]
    assert [spec.misfire_grace_time for spec in specs] == [
        None,
        None,
        3600,
        3600,
        3600,
        3600,
        300,
        120,
        300,
    ]
    assert all(spec.max_instances == 1 for spec in specs)
    assert all(spec.coalesce is True for spec in specs)
```

- [ ] **Step 2: Add enablement and interval-boundary tests**

Add parameterized tests asserting:

```python
@pytest.mark.parametrize(
    ("overrides", "missing_ids"),
    [
        ({"scheduler_briefing_enabled": False}, {"daily_briefing"}),
        (
            {"scheduler_evidence_enabled": False},
            {"pre_market_evidence", "post_market_evidence"},
        ),
        (
            {"scheduler_evidence_hourly_enabled": False},
            {"post_market_evidence_hourly"},
        ),
        ({"cls_telegraph_sync_enabled": False}, {"cls_telegraph_sync"}),
        ({"scheduler_knowledge_enabled": False}, {"knowledge_ingest_index"}),
    ],
)
def test_build_job_specs_preserves_independent_enablement(
    overrides,
    missing_ids,
) -> None:
    ids = _ids(_settings(**overrides))

    assert ids.isdisjoint(missing_ids)
    assert "daily_refresh" in ids


@pytest.mark.parametrize(
    ("field", "job_id"),
    [
        ("scheduler_evidence_hourly_minutes", "post_market_evidence_hourly"),
        ("cls_telegraph_sync_interval_seconds", "cls_telegraph_sync"),
        ("scheduler_knowledge_interval_minutes", "knowledge_ingest_index"),
    ],
)
def test_non_positive_intervals_disable_only_their_job(field, job_id) -> None:
    assert job_id not in _ids(_settings(**{field: 0}))
    assert "daily_refresh" in _ids(_settings(**{field: 0}))
```

Add the explicit override regression:

```python
def test_refresh_overrides_do_not_replace_briefing_schedule() -> None:
    from backend.scheduler.registry import build_job_specs
    from backend.scheduler.specs import CronSpec

    specs = build_job_specs(
        _settings(),
        timezone="UTC",
        refresh_hour=21,
        refresh_minute=5,
    )

    by_id = {spec.id: spec for spec in specs}
    assert by_id["daily_refresh"].trigger == CronSpec(21, 5, "UTC")
    assert by_id["daily_briefing"].trigger == CronSpec(17, 0, "UTC")
    assert all(spec.trigger.timezone == "UTC" for spec in specs)
```

- [ ] **Step 3: Run registry tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q backend/tests/test_scheduler_registry.py
```

Expected: failure because `backend.scheduler.registry` does not exist.

- [ ] **Step 4: Implement `build_job_specs`**

Create `backend/scheduler/registry.py` with the complete registry:

```python
"""Declarative Scheduler job registry."""
from __future__ import annotations

from backend.config.settings import Settings
from backend.scheduler import task_functions as tasks
from backend.scheduler.specs import CronSpec, IntervalSpec, JobSpec


def build_job_specs(
    settings: Settings,
    *,
    timezone: str,
    refresh_hour: int,
    refresh_minute: int,
) -> tuple[JobSpec, ...]:
    specs = [
        JobSpec(
            id="daily_refresh",
            callable=tasks.run_daily_refresh,
            trigger=CronSpec(refresh_hour, refresh_minute, timezone),
        ),
    ]

    if bool(getattr(settings, "scheduler_briefing_enabled", True)):
        specs.append(JobSpec(
            id="daily_briefing",
            callable=tasks.run_daily_briefing,
            trigger=CronSpec(
                int(getattr(settings, "scheduler_briefing_cron_hour", 17)),
                int(getattr(settings, "scheduler_briefing_cron_minute", 0)),
                timezone,
            ),
        ))

    specs.extend((
        JobSpec(
            id="morning_market_intel",
            callable=tasks.run_morning_market_intel,
            trigger=CronSpec(9, 35, timezone),
            misfire_grace_time=3600,
        ),
        JobSpec(
            id="post_market_market_intel",
            callable=tasks.run_post_market_intel,
            trigger=CronSpec(15, 35, timezone),
            misfire_grace_time=3600,
        ),
    ))

    if bool(getattr(settings, "scheduler_evidence_enabled", True)):
        specs.extend((
            JobSpec(
                id="pre_market_evidence",
                callable=tasks.run_pre_market_evidence,
                trigger=CronSpec(8, 30, timezone),
                misfire_grace_time=3600,
            ),
            JobSpec(
                id="post_market_evidence",
                callable=tasks.run_post_market_evidence,
                trigger=CronSpec(16, 0, timezone),
                misfire_grace_time=3600,
            ),
        ))

    if bool(getattr(settings, "scheduler_evidence_hourly_enabled", True)):
        hourly_minutes = int(
            getattr(settings, "scheduler_evidence_hourly_minutes", 60)
        )
        if hourly_minutes > 0:
            specs.append(JobSpec(
                id="post_market_evidence_hourly",
                callable=tasks.run_post_market_evidence_hourly,
                trigger=IntervalSpec(
                    timezone=timezone,
                    minutes=hourly_minutes,
                    jitter=60,
                ),
                misfire_grace_time=300,
            ))

    if bool(getattr(settings, "cls_telegraph_sync_enabled", True)):
        interval_seconds = int(
            getattr(settings, "cls_telegraph_sync_interval_seconds", 60)
        )
        if interval_seconds > 0:
            specs.append(JobSpec(
                id="cls_telegraph_sync",
                callable=tasks.run_cls_telegraph_sync,
                trigger=IntervalSpec(
                    timezone=timezone,
                    seconds=interval_seconds,
                    jitter=min(10, max(0, interval_seconds // 5)),
                ),
                misfire_grace_time=120,
            ))

    if bool(getattr(settings, "scheduler_knowledge_enabled", True)):
        knowledge_minutes = int(
            getattr(settings, "scheduler_knowledge_interval_minutes", 6)
        )
        if knowledge_minutes > 0:
            specs.append(JobSpec(
                id="knowledge_ingest_index",
                callable=tasks.run_knowledge_ingest_index,
                trigger=IntervalSpec(
                    timezone=timezone,
                    minutes=knowledge_minutes,
                    jitter=min(60, max(0, knowledge_minutes * 10)),
                    start_delay_seconds=30,
                ),
                misfire_grace_time=300,
            ))

    return tuple(specs)
```

Do not instantiate APScheduler triggers, read the clock, create models, call services, or wrap callables in lambdas.

- [ ] **Step 5: Run registry and spec tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_scheduler_specs.py \
  backend/tests/test_scheduler_registry.py
```

Expected: all selected tests pass and the complete nine-job snapshot matches.

---

### Task 4: Implement the APScheduler-only runtime

**Files:**
- Create: `backend/tests/test_scheduler_runtime.py`
- Create: `backend/scheduler/runtime.py`

**Interfaces:**
- Consumes: `get_settings`, `build_job_specs`, `CronSpec`, `IntervalSpec`, and `JobSpec`.
- Produces: `start_scheduler`, `get_scheduler`, and `shutdown_scheduler` with the existing signature and behavior.
- Produces: private `_build_trigger(spec)` and `_register_job(scheduler, spec)` seams for focused tests.

- [ ] **Step 1: Write failing trigger conversion tests**

Create `backend/tests/test_scheduler_runtime.py` with tests that freeze `runtime.datetime.now` through a small fake datetime class and assert:

```python
cron = runtime._build_trigger(
    CronSpec(hour=8, minute=30, timezone="Asia/Shanghai")
)
assert isinstance(cron, CronTrigger)

interval = runtime._build_trigger(
    IntervalSpec(
        timezone="Asia/Shanghai",
        minutes=6,
        jitter=60,
        start_delay_seconds=30,
    )
)
assert isinstance(interval, IntervalTrigger)
assert interval.interval.total_seconds() == 360
assert interval.jitter == 60
assert (interval.start_date - fixed_now).total_seconds() == 30
```

Add a seconds case asserting 360 seconds and jitter 10. Assert interval jitter is stored on `IntervalTrigger`, not passed as an `add_job` keyword.

- [ ] **Step 2: Write failing lifecycle tests with a fake scheduler**

Use this fake scheduler to record `add_job`, `start`, and `shutdown` events:

```python
class FakeScheduler:
    def __init__(self, events):
        self.events = events

    def add_job(self, fn, **kwargs):
        self.events.append(("add_job", fn, kwargs))

    def start(self):
        self.events.append(("start",))

    def shutdown(self, wait=True):
        self.events.append(("shutdown", wait))


@pytest.fixture(autouse=True)
def reset_runtime_state():
    from backend.scheduler import runtime

    runtime._scheduler = None
    yield
    runtime._scheduler = None


def test_disabled_scheduler_does_not_build_or_register(monkeypatch):
    from backend.scheduler import runtime

    monkeypatch.setattr(
        runtime,
        "_build_scheduler",
        lambda: pytest.fail("disabled Scheduler must not be built"),
    )

    assert runtime.start_scheduler(enabled=False) is None


def test_start_registers_specs_before_start_and_is_idempotent(monkeypatch):
    from backend.scheduler import runtime
    from backend.scheduler.specs import CronSpec, JobSpec

    events = []
    scheduler = FakeScheduler(events)
    fn = lambda: None
    specs = (JobSpec("daily_refresh", fn, CronSpec(20, 0, "Asia/Shanghai")),)
    monkeypatch.setattr(runtime, "_build_scheduler", lambda: scheduler)
    monkeypatch.setattr(runtime, "build_job_specs", lambda *_args, **_kwargs: specs)

    first = runtime.start_scheduler(
        enabled=True,
        hour=20,
        minute=0,
        timezone="Asia/Shanghai",
    )
    second = runtime.start_scheduler(enabled=True)

    assert first is scheduler
    assert second is scheduler
    assert [event[0] for event in events] == ["add_job", "start"]
    assert events[0][1] is fn


def test_start_failure_does_not_publish_scheduler_state(monkeypatch):
    from backend.scheduler import runtime

    class FailingScheduler(FakeScheduler):
        def start(self):
            raise RuntimeError("start failed")

    scheduler = FailingScheduler([])
    monkeypatch.setattr(runtime, "_build_scheduler", lambda: scheduler)
    monkeypatch.setattr(runtime, "build_job_specs", lambda *_args, **_kwargs: ())

    with pytest.raises(RuntimeError, match="start failed"):
        runtime.start_scheduler(enabled=True)

    assert runtime.get_scheduler() is None


def test_shutdown_uses_wait_false_and_clears_state(monkeypatch):
    from backend.scheduler import runtime

    events = []
    scheduler = FakeScheduler(events)
    runtime._scheduler = scheduler

    runtime.shutdown_scheduler()

    assert events == [("shutdown", False)]
    assert runtime.get_scheduler() is None


def test_get_scheduler_returns_live_runtime_state():
    from backend.scheduler import runtime

    scheduler = object()
    runtime._scheduler = scheduler

    assert runtime.get_scheduler() is scheduler
```

The registration assertion must verify that `_register_job` passes:

```python
{
    "id": spec.id,
    "max_instances": spec.max_instances,
    "coalesce": spec.coalesce,
    "misfire_grace_time": spec.misfire_grace_time,  # only when non-None
}
```

and that the first positional argument is `spec.callable` itself.

- [ ] **Step 3: Run runtime tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q backend/tests/test_scheduler_runtime.py
```

Expected: failure because `backend.scheduler.runtime` does not exist.

- [ ] **Step 4: Implement trigger conversion and lifecycle**

Create `backend/scheduler/runtime.py`:

```python
"""APScheduler registration and process-local lifecycle."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.config.settings import get_settings
from backend.scheduler.registry import build_job_specs
from backend.scheduler.specs import CronSpec, IntervalSpec, JobSpec


_scheduler: BackgroundScheduler | None = None


def _build_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(timezone="Asia/Shanghai")


def _build_trigger(spec: CronSpec | IntervalSpec):
    if isinstance(spec, CronSpec):
        return CronTrigger(
            hour=spec.hour,
            minute=spec.minute,
            timezone=spec.timezone,
        )

    start_date = datetime.now(ZoneInfo(spec.timezone)) + timedelta(
        seconds=max(0, int(spec.start_delay_seconds)),
    )
    kwargs = {
        "timezone": spec.timezone,
        "jitter": max(0, int(spec.jitter)),
        "start_date": start_date,
    }
    if spec.minutes is not None:
        kwargs["minutes"] = max(1, int(spec.minutes))
    else:
        kwargs["seconds"] = max(1, int(spec.seconds))
    return IntervalTrigger(**kwargs)


def _register_job(scheduler: BackgroundScheduler, spec: JobSpec) -> None:
    kwargs = {
        "trigger": _build_trigger(spec.trigger),
        "id": spec.id,
        "max_instances": spec.max_instances,
        "coalesce": spec.coalesce,
    }
    if spec.misfire_grace_time is not None:
        kwargs["misfire_grace_time"] = spec.misfire_grace_time
    scheduler.add_job(spec.callable, **kwargs)


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def start_scheduler(
    *,
    enabled: bool | None = None,
    hour: int | None = None,
    minute: int | None = None,
    timezone: str | None = None,
) -> BackgroundScheduler | None:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    if enabled is None:
        enabled = bool(settings.scheduler_enabled)
    if not enabled:
        return None

    resolved_timezone = timezone or settings.scheduler_timezone
    resolved_hour = (
        int(settings.scheduler_refresh_cron_hour)
        if hour is None
        else int(hour)
    )
    resolved_minute = (
        int(settings.scheduler_refresh_cron_minute)
        if minute is None
        else int(minute)
    )
    scheduler = _build_scheduler()
    specs = build_job_specs(
        settings,
        timezone=resolved_timezone,
        refresh_hour=resolved_hour,
        refresh_minute=resolved_minute,
    )
    for spec in specs:
        _register_job(scheduler, spec)
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
```

Do not import task functions, services, or graph directly from runtime.

- [ ] **Step 5: Run runtime, registry, and existing API lifecycle tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_scheduler_runtime.py \
  backend/tests/test_scheduler_registry.py \
  backend/tests/test_api_app.py
```

Expected: new runtime tests pass. Existing API tests may still fail only where they import the old internal module; those consumers are hard-switched in Task 5.

---

### Task 5: Hard-switch consumers and delete legacy Scheduler modules

**Files:**
- Create: `backend/tests/test_scheduler_contract.py`
- Modify: `backend/scheduler/__init__.py`
- Modify: `backend/tests/test_api_app.py`
- Modify: `backend/tests/test_scheduler_briefing.py`
- Delete: `backend/scheduler/scheduler.py`
- Delete: `backend/scheduler/jobs.py`
- Delete: `backend/tests/test_scheduler.py`
- Delete: `backend/tests/test_scheduler_jobs.py`

**Interfaces:**
- Produces: package API `start_scheduler`, `get_scheduler`, `shutdown_scheduler` only.
- Enforces: no old path, no reverse runtime dependency, no broad package facade.

- [ ] **Step 1: Write the RED hard-cut contract**

Create `backend/tests/test_scheduler_contract.py` with AST/path checks:

```python
"""Scheduler hard-cut structure and dependency contracts."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

ROOT = Path("backend")
LEGACY_MODULES = {
    "backend.scheduler.scheduler",
    "backend.scheduler.jobs",
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_legacy_scheduler_modules_are_deleted() -> None:
    assert not Path("backend/scheduler/scheduler.py").exists()
    assert not Path("backend/scheduler/jobs.py").exists()


@pytest.mark.parametrize("path", sorted(ROOT.rglob("*.py")), ids=str)
def test_python_sources_do_not_import_legacy_scheduler_modules(path: Path) -> None:
    assert LEGACY_MODULES.isdisjoint(_imports(path)), path


def test_runtime_does_not_import_domain_or_graph_modules() -> None:
    imports = _imports(Path("backend/scheduler/runtime.py"))
    assert not any(
        module.startswith(("backend.services", "backend.graph"))
        for module in imports
    )


def test_scheduler_package_exports_only_lifecycle_api() -> None:
    import backend.scheduler as scheduler

    assert scheduler.__all__ == [
        "start_scheduler",
        "get_scheduler",
        "shutdown_scheduler",
    ]
```

- [ ] **Step 2: Run the contract and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q backend/tests/test_scheduler_contract.py
```

Expected: failure because the two legacy production modules still exist and the package still exports `JobSpec`, `cron_job`, and `interval_job`.

- [ ] **Step 3: Narrow the package API**

Replace `backend/scheduler/__init__.py` with:

```python
"""Process-local Scheduler lifecycle API."""
from __future__ import annotations

from backend.scheduler.runtime import (
    get_scheduler,
    shutdown_scheduler,
    start_scheduler,
)


__all__ = [
    "start_scheduler",
    "get_scheduler",
    "shutdown_scheduler",
]
```

Do not expose `runtime`, task functions, registry, or spec classes from the facade.

- [ ] **Step 4: Migrate tests to the new seams**

Update `backend/tests/test_api_app.py::test_health_reads_live_scheduler_state` to patch `backend.scheduler.runtime._scheduler`; continue calling the health route through the package getter.

Update `backend/tests/test_scheduler_briefing.py`:

- use `backend.scheduler.runtime` only for test state reset;
- call lifecycle methods through `backend.scheduler`;
- obtain the scheduler through `get_scheduler()` rather than reading a package global;
- patch `backend.scheduler.task_functions._build_briefing_model` and `task_functions.briefing_workflow.run_daily_briefing` before invoking the registered job;
- keep the configured hour/minute and disabled-setting assertions unchanged.

Delete `backend/tests/test_scheduler.py` after its runtime, registry, task-function, and knowledge tests are represented in the new focused files. Do not copy its misplaced market-evidence singleflight test; retain the existing equivalent test in `backend/tests/test_market_evidence_service.py`.

Delete `backend/tests/test_scheduler_jobs.py`; `test_scheduler_specs.py` supersedes it.

- [ ] **Step 5: Delete legacy production modules**

Delete:

```text
backend/scheduler/scheduler.py
backend/scheduler/jobs.py
```

Do not create same-name shims. Search all Python files and update any remaining old imports to the package lifecycle API or the appropriate new internal module.

- [ ] **Step 6: Run hard-cut and focused regression tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_scheduler_contract.py \
  backend/tests/test_scheduler_specs.py \
  backend/tests/test_scheduler_task_functions.py \
  backend/tests/test_scheduler_registry.py \
  backend/tests/test_scheduler_runtime.py \
  backend/tests/test_scheduler_briefing.py \
  backend/tests/test_api_app.py \
  backend/tests/test_briefing_jobs.py \
  backend/tests/test_knowledge_reindex_jobs.py \
  backend/tests/test_market_evidence_service.py
```

Expected: all selected tests pass with no collection errors or old import paths.

---

### Task 6: Verify the whole hard cut and create one atomic implementation commit

**Files:**
- Modify: `.superpowers/sdd/progress.md` (ignored working ledger only; do not stage)
- Verify: all production and test files changed in Tasks 1–5

**Interfaces:**
- Produces: one reviewable implementation commit with no compatibility layer or partial migration.

- [ ] **Step 1: Run static hard-cut gates**

Run:

```bash
.venv/bin/python -m compileall -q backend
git diff --check
test ! -e backend/scheduler/scheduler.py
test ! -e backend/scheduler/jobs.py
! rg -n 'backend\.scheduler\.(scheduler|jobs)' backend -g '*.py'
! rg -n 'from backend\.scheduler import (scheduler|jobs)' backend -g '*.py'
! rg -n 'backend\.(services|graph)' backend/scheduler/runtime.py
```

Expected: every command exits zero and both legacy files and all old imports are absent.

- [ ] **Step 2: Run the complete PostgreSQL backend regression**

Run with the established disposable local test database:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@127.0.0.1:55432/fund_agent_test \
  .venv/bin/python -m pytest -q backend/tests
```

Expected: the complete backend suite passes. Compare the count with the recorded baseline; explain only intentional test-file consolidation differences.

- [ ] **Step 3: Review the complete diff against the approved spec**

Inspect:

```bash
git status --short
git diff --stat
git diff -- backend/scheduler backend/tests/test_scheduler_contract.py \
  backend/tests/test_scheduler_specs.py \
  backend/tests/test_scheduler_task_functions.py \
  backend/tests/test_scheduler_registry.py \
  backend/tests/test_scheduler_runtime.py \
  backend/tests/test_scheduler_briefing.py \
  backend/tests/test_api_app.py
```

Review checklist:

- no job ID, order, trigger, callable argument, enablement, or error-path drift;
- no service/graph imports in runtime and no APScheduler imports in specs;
- no anonymous job lambdas or duplicate registration implementations;
- no old modules, aliases, re-exports, temporary files, or unrelated edits;
- package exports exactly the three lifecycle functions;
- executor-submit active-claim reliability behavior remains outside this change.

Resolve every Critical, Important, and Minor review finding, then rerun the focused tests, static gates, and full PostgreSQL suite.

- [ ] **Step 4: Update the ignored progress ledger**

Record each task's RED/GREEN evidence, focused counts, final review outcome, and complete PostgreSQL result in `.superpowers/sdd/progress.md`. Confirm the ledger is ignored and absent from `git status --short`.

- [ ] **Step 5: Stage exactly the Scheduler hard-cut implementation**

Run:

```bash
git add \
  backend/scheduler/__init__.py \
  backend/scheduler/specs.py \
  backend/scheduler/task_functions.py \
  backend/scheduler/registry.py \
  backend/scheduler/runtime.py \
  backend/scheduler/scheduler.py \
  backend/scheduler/jobs.py \
  backend/tests/test_scheduler_contract.py \
  backend/tests/test_scheduler_specs.py \
  backend/tests/test_scheduler_task_functions.py \
  backend/tests/test_scheduler_registry.py \
  backend/tests/test_scheduler_runtime.py \
  backend/tests/test_scheduler_briefing.py \
  backend/tests/test_api_app.py \
  backend/tests/test_scheduler.py \
  backend/tests/test_scheduler_jobs.py
git diff --cached --check
git diff --cached --stat
```

Expected: only the approved Scheduler production boundary and its tests are staged; deletions appear in the staged diff; the ignored ledger is not staged.

- [ ] **Step 6: Create the single atomic implementation commit**

Run:

```bash
git commit -m "refactor: hard cut scheduler modules"
```

Expected: one implementation commit containing Tasks 1–5, with the design and plan remaining in their earlier independent commits.

- [ ] **Step 7: Verify post-commit state**

Run:

```bash
git status --short --branch
git log -3 --oneline --decorate
```

Expected: clean worktree on `refactore`; the latest three commits are implementation, plan, and design in that order. Do not push, merge, or create a PR unless the user requests it.
