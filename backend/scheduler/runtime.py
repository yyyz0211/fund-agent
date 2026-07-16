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
    kwargs: dict[str, object] = {
        "timezone": spec.timezone,
        "jitter": max(0, int(spec.jitter)),
        "start_date": start_date,
    }
    if spec.minutes is not None:
        kwargs["minutes"] = max(1, int(spec.minutes))
    else:
        assert spec.seconds is not None
        kwargs["seconds"] = max(1, int(spec.seconds))
    return IntervalTrigger(**kwargs)


def _register_job(scheduler: BackgroundScheduler, spec: JobSpec) -> None:
    kwargs: dict[str, object] = {
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

    resolved_timezone = (
        settings.scheduler_timezone if timezone is None else timezone
    )
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
