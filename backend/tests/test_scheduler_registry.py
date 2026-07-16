"""Declarative Scheduler registry contracts."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.unit

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

ALL_JOB_IDS = [
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


def _settings(**overrides):
    return SimpleNamespace(**(DEFAULTS | overrides))


def _build(settings=None, **overrides):
    from backend.scheduler.registry import build_job_specs

    return build_job_specs(
        settings or _settings(),
        timezone=overrides.get("timezone", "Asia/Shanghai"),
        refresh_hour=overrides.get("refresh_hour", 20),
        refresh_minute=overrides.get("refresh_minute", 0),
    )


def _ids(settings=None) -> list[str]:
    return [spec.id for spec in _build(settings)]


def test_build_job_specs_preserves_complete_registration_snapshot() -> None:
    from backend.scheduler import task_functions as tasks
    from backend.scheduler.specs import CronSpec, IntervalSpec

    specs = _build()

    assert [spec.id for spec in specs] == ALL_JOB_IDS
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

    assert ids == [job_id for job_id in ALL_JOB_IDS if job_id not in missing_ids]


@pytest.mark.parametrize(
    ("field", "job_id"),
    [
        ("scheduler_evidence_hourly_minutes", "post_market_evidence_hourly"),
        ("cls_telegraph_sync_interval_seconds", "cls_telegraph_sync"),
        ("scheduler_knowledge_interval_minutes", "knowledge_ingest_index"),
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_intervals_disable_only_their_job(
    field,
    job_id,
    value,
) -> None:
    ids = _ids(_settings(**{field: value}))

    assert ids == [current for current in ALL_JOB_IDS if current != job_id]


def test_refresh_overrides_do_not_replace_briefing_schedule() -> None:
    from backend.scheduler.specs import CronSpec

    specs = _build(
        timezone="UTC",
        refresh_hour=21,
        refresh_minute=5,
    )

    by_id = {spec.id: spec for spec in specs}
    assert by_id["daily_refresh"].trigger == CronSpec(21, 5, "UTC")
    assert by_id["daily_briefing"].trigger == CronSpec(17, 0, "UTC")
    assert all(spec.trigger.timezone == "UTC" for spec in specs)
