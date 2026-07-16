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
        specs.append(
            JobSpec(
                id="daily_briefing",
                callable=tasks.run_daily_briefing,
                trigger=CronSpec(
                    int(getattr(settings, "scheduler_briefing_cron_hour", 17)),
                    int(getattr(settings, "scheduler_briefing_cron_minute", 0)),
                    timezone,
                ),
            )
        )

    specs.extend(
        (
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
        )
    )

    if bool(getattr(settings, "scheduler_evidence_enabled", True)):
        specs.extend(
            (
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
            )
        )

    if bool(getattr(settings, "scheduler_evidence_hourly_enabled", True)):
        hourly_minutes = int(
            getattr(settings, "scheduler_evidence_hourly_minutes", 60)
        )
        if hourly_minutes > 0:
            specs.append(
                JobSpec(
                    id="post_market_evidence_hourly",
                    callable=tasks.run_post_market_evidence_hourly,
                    trigger=IntervalSpec(
                        timezone=timezone,
                        minutes=hourly_minutes,
                        jitter=60,
                    ),
                    misfire_grace_time=300,
                )
            )

    if bool(getattr(settings, "cls_telegraph_sync_enabled", True)):
        interval_seconds = int(
            getattr(settings, "cls_telegraph_sync_interval_seconds", 60)
        )
        if interval_seconds > 0:
            specs.append(
                JobSpec(
                    id="cls_telegraph_sync",
                    callable=tasks.run_cls_telegraph_sync,
                    trigger=IntervalSpec(
                        timezone=timezone,
                        seconds=interval_seconds,
                        jitter=min(10, max(0, interval_seconds // 5)),
                    ),
                    misfire_grace_time=120,
                )
            )

    if bool(getattr(settings, "scheduler_knowledge_enabled", True)):
        knowledge_minutes = int(
            getattr(settings, "scheduler_knowledge_interval_minutes", 6)
        )
        if knowledge_minutes > 0:
            specs.append(
                JobSpec(
                    id="knowledge_ingest_index",
                    callable=tasks.run_knowledge_ingest_index,
                    trigger=IntervalSpec(
                        timezone=timezone,
                        minutes=knowledge_minutes,
                        jitter=min(60, max(0, knowledge_minutes * 10)),
                        start_delay_seconds=30,
                    ),
                    misfire_grace_time=300,
                )
            )

    return tuple(specs)
