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
