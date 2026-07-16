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
