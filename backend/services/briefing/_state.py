"""Thread-safe process-local Briefing runtime state."""
from __future__ import annotations

from threading import Lock

_last_run_lock = Lock()
_active_job_lock = Lock()
_last_run: dict = {}
_active_job_id: str | None = None


def _empty_snapshot() -> dict:
    return {
        "last_run_at": None,
        "trigger": None,
        "total_funds": 0,
        "succeeded": 0,
        "failed": 0,
        "failures": [],
    }


def update_last_run(snapshot: dict) -> None:
    with _last_run_lock:
        _last_run.clear()
        _last_run.update(snapshot)


def get_last_run() -> dict:
    with _last_run_lock:
        if not _last_run or _last_run.get("last_run_at") is None:
            return _empty_snapshot()
        return dict(_last_run)


def claim_active_job(job_id: str) -> str | None:
    global _active_job_id
    with _active_job_lock:
        if _active_job_id is not None:
            return _active_job_id
        _active_job_id = job_id
        return None


def release_active_job(job_id: str) -> None:
    global _active_job_id
    with _active_job_lock:
        if _active_job_id == job_id:
            _active_job_id = None


def reset_for_tests() -> None:
    global _active_job_id
    with _last_run_lock:
        _last_run.clear()
    with _active_job_lock:
        _active_job_id = None
