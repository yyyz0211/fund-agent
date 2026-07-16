"""Briefing asynchronous submission and public runtime status."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from backend.services.briefing import _state, workflow
from backend.services.briefing.types import ChatModel

_async_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="briefing-run",
)


def get_last_run() -> dict:
    return _state.get_last_run()


def reset_for_tests() -> None:
    _state.reset_for_tests()


def start_run_async(
    *,
    trigger: str = "manual",
    brief_type: str = "post_market",
    model: ChatModel | None = None,
) -> dict:
    job_id = uuid.uuid4().hex[:8]
    active_job_id = _state.claim_active_job(job_id)
    if active_job_id is not None:
        return {
            "status": "running",
            "job_id": active_job_id,
            "brief_type": brief_type,
        }

    def _task() -> None:
        try:
            workflow.run_daily_briefing(
                trigger=trigger,
                brief_type=brief_type,
                model=model,
            )
        finally:
            _state.release_active_job(job_id)

    _async_executor.submit(_task)
    return {
        "status": "started",
        "trigger": trigger,
        "brief_type": brief_type,
        "job_id": job_id,
    }


__all__ = ["get_last_run", "reset_for_tests", "start_run_async"]
