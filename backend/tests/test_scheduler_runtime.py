"""APScheduler trigger conversion and lifecycle contracts."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


pytestmark = pytest.mark.unit


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
    try:
        from backend.scheduler import runtime
    except ImportError:
        yield
        return

    runtime._scheduler = None
    yield
    runtime._scheduler = None


def test_build_trigger_converts_cron_spec() -> None:
    from backend.scheduler import runtime
    from backend.scheduler.specs import CronSpec

    trigger = runtime._build_trigger(
        CronSpec(hour=8, minute=30, timezone="Asia/Shanghai")
    )

    assert isinstance(trigger, CronTrigger)
    fields = {field.name: str(field) for field in trigger.fields}
    assert fields["hour"] == "8"
    assert fields["minute"] == "30"
    assert str(trigger.timezone) == "Asia/Shanghai"


def test_build_trigger_converts_minutes_with_jitter_and_start_delay(
    monkeypatch,
) -> None:
    from backend.scheduler import runtime
    from backend.scheduler.specs import IntervalSpec

    fixed_now = datetime(2026, 7, 16, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(runtime, "datetime", FixedDateTime)

    trigger = runtime._build_trigger(
        IntervalSpec(
            timezone="Asia/Shanghai",
            minutes=6,
            jitter=60,
            start_delay_seconds=30,
        )
    )

    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 360
    assert trigger.jitter == 60
    assert (trigger.start_date - fixed_now).total_seconds() == 30


def test_build_trigger_converts_seconds_interval(monkeypatch) -> None:
    from backend.scheduler import runtime
    from backend.scheduler.specs import IntervalSpec

    fixed_now = datetime(2026, 7, 16, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(runtime, "datetime", FixedDateTime)

    trigger = runtime._build_trigger(
        IntervalSpec(
            timezone="Asia/Shanghai",
            seconds=360,
            jitter=10,
        )
    )

    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 360
    assert trigger.jitter == 10
    assert trigger.start_date == fixed_now


def test_register_job_preserves_callable_and_job_kwargs(monkeypatch) -> None:
    from backend.scheduler import runtime
    from backend.scheduler.specs import CronSpec, JobSpec

    events = []
    scheduler = FakeScheduler(events)
    fn = lambda: None
    trigger = object()
    monkeypatch.setattr(runtime, "_build_trigger", lambda _spec: trigger)
    spec = JobSpec(
        id="morning_market_intel",
        callable=fn,
        trigger=CronSpec(9, 35, "Asia/Shanghai"),
        misfire_grace_time=3600,
    )

    runtime._register_job(scheduler, spec)

    assert events == [
        (
            "add_job",
            fn,
            {
                "trigger": trigger,
                "id": "morning_market_intel",
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        )
    ]
    assert "jitter" not in events[0][2]


def test_register_job_omits_unset_misfire_grace(monkeypatch) -> None:
    from backend.scheduler import runtime
    from backend.scheduler.specs import CronSpec, JobSpec

    events = []
    monkeypatch.setattr(runtime, "_build_trigger", lambda _spec: object())

    runtime._register_job(
        FakeScheduler(events),
        JobSpec(
            id="daily_refresh",
            callable=lambda: None,
            trigger=CronSpec(20, 0, "Asia/Shanghai"),
        ),
    )

    assert "misfire_grace_time" not in events[0][2]


def test_disabled_scheduler_does_not_build_or_register(monkeypatch) -> None:
    from backend.scheduler import runtime

    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(
        runtime,
        "_build_scheduler",
        lambda: pytest.fail("disabled Scheduler must not be built"),
    )

    assert runtime.start_scheduler(enabled=False) is None


def test_start_registers_specs_before_start_and_is_idempotent(monkeypatch) -> None:
    from backend.scheduler import runtime
    from backend.scheduler.specs import CronSpec, JobSpec

    events = []
    scheduler = FakeScheduler(events)
    fn = lambda: None
    specs = (
        JobSpec(
            "daily_refresh",
            fn,
            CronSpec(20, 0, "Asia/Shanghai"),
        ),
    )
    settings = SimpleNamespace(
        scheduler_enabled=True,
        scheduler_timezone="Asia/Shanghai",
        scheduler_refresh_cron_hour=20,
        scheduler_refresh_cron_minute=0,
    )
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "_build_scheduler", lambda: scheduler)
    monkeypatch.setattr(
        runtime,
        "build_job_specs",
        lambda *_args, **_kwargs: specs,
    )

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


def test_start_resolves_settings_and_explicit_overrides(monkeypatch) -> None:
    from backend.scheduler import runtime

    settings = SimpleNamespace(
        scheduler_enabled=True,
        scheduler_timezone="Asia/Shanghai",
        scheduler_refresh_cron_hour=20,
        scheduler_refresh_cron_minute=0,
    )
    calls = []
    scheduler = FakeScheduler([])
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "_build_scheduler", lambda: scheduler)
    monkeypatch.setattr(
        runtime,
        "build_job_specs",
        lambda passed_settings, **kwargs: calls.append(
            (passed_settings, kwargs)
        )
        or (),
    )

    runtime.start_scheduler(
        hour=21,
        minute=5,
        timezone="UTC",
    )

    assert calls == [
        (
            settings,
            {"timezone": "UTC", "refresh_hour": 21, "refresh_minute": 5},
        )
    ]


def test_start_only_defaults_timezone_when_override_is_none(monkeypatch) -> None:
    from backend.scheduler import runtime

    settings = SimpleNamespace(
        scheduler_enabled=True,
        scheduler_timezone="Asia/Shanghai",
        scheduler_refresh_cron_hour=20,
        scheduler_refresh_cron_minute=0,
    )
    calls = []
    scheduler = FakeScheduler([])
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "_build_scheduler", lambda: scheduler)
    monkeypatch.setattr(
        runtime,
        "build_job_specs",
        lambda _settings, **kwargs: calls.append(kwargs) or (),
    )

    runtime.start_scheduler(timezone="")

    assert calls == [
        {"timezone": "", "refresh_hour": 20, "refresh_minute": 0}
    ]


def test_start_failure_does_not_publish_scheduler_state(monkeypatch) -> None:
    from backend.scheduler import runtime

    class FailingScheduler(FakeScheduler):
        def start(self):
            raise RuntimeError("start failed")

    scheduler = FailingScheduler([])
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(runtime, "_build_scheduler", lambda: scheduler)
    monkeypatch.setattr(
        runtime,
        "build_job_specs",
        lambda *_args, **_kwargs: (),
    )

    with pytest.raises(RuntimeError, match="start failed"):
        runtime.start_scheduler(
            enabled=True,
            hour=20,
            minute=0,
            timezone="Asia/Shanghai",
        )

    assert runtime.get_scheduler() is None


def test_shutdown_uses_wait_false_and_clears_state() -> None:
    from backend.scheduler import runtime

    events = []
    scheduler = FakeScheduler(events)
    runtime._scheduler = scheduler

    runtime.shutdown_scheduler()

    assert events == [("shutdown", False)]
    assert runtime.get_scheduler() is None


def test_get_scheduler_returns_live_runtime_state() -> None:
    from backend.scheduler import runtime

    scheduler = object()
    runtime._scheduler = scheduler

    assert runtime.get_scheduler() is scheduler
