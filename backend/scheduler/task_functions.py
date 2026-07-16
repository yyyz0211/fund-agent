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
