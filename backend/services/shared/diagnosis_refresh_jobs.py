"""In-process fund diagnosis refresh jobs.

This is intentionally local-process only. The project is single-user SQLite,
so avoiding request-thread blocking matters more than durable queue semantics.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from uuid import uuid4

from backend.services.fund import fund_profile_service as profile_service


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="diagnosis-refresh")
_lock = Lock()
_jobs: dict[str, dict] = {}
_active_by_code: dict[str, str] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _snapshot(job: dict) -> dict:
    return dict(job)


def start_refresh_job(fund_code: str, *, force: bool = False) -> dict:
    """Start or reuse a bounded background profile refresh job."""
    if not force and profile_service.is_profile_fresh(fund_code, ttl_hours=24):
        now = _now()
        return {
            "job_id": f"{fund_code}-{uuid4().hex[:8]}",
            "fund_code": fund_code,
            "status": "done",
            "started_at": now,
            "finished_at": now,
            "missing_data": [],
            "error": None,
            "as_of": now[:10],
        }
    with _lock:
        active_id = _active_by_code.get(fund_code)
        if active_id and _jobs.get(active_id, {}).get("status") in {"started", "running"}:
            job = _jobs[active_id]
            job["status"] = "running"
            return _snapshot(job)
        job_id = f"{fund_code}-{uuid4().hex[:8]}"
        job = {
            "job_id": job_id,
            "fund_code": fund_code,
            "status": "started",
            "started_at": _now(),
            "finished_at": None,
            "missing_data": [],
            "error": None,
            "as_of": _now()[:10],
        }
        _jobs[job_id] = job
        _active_by_code[fund_code] = job_id
    _submit_refresh(job)
    return _snapshot(job)


def _submit_refresh(job: dict) -> None:
    _executor.submit(_run_refresh, job["job_id"])


def _run_refresh(job_id: str) -> None:
    with _lock:
        job = _jobs[job_id]
        job["status"] = "running"
    try:
        result = profile_service.refresh_profile(job["fund_code"])
        with _lock:
            job["status"] = "done"
            job["missing_data"] = result.get("missing_data", [])
            job["as_of"] = result.get("as_of") or job["as_of"]
    except Exception as exc:  # noqa: BLE001
        with _lock:
            job["status"] = "failed"
            job["error"] = str(exc)
    finally:
        with _lock:
            job["finished_at"] = _now()
            if _active_by_code.get(job["fund_code"]) == job_id:
                _active_by_code.pop(job["fund_code"], None)


def get_refresh_job(fund_code: str, job_id: str) -> dict:
    """Return a job snapshot, or a stable missing payload."""
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.get("fund_code") != fund_code:
            return {
                "job_id": job_id,
                "fund_code": fund_code,
                "status": "missing",
                "started_at": None,
                "finished_at": None,
                "missing_data": [],
                "error": "refresh job not found",
                "as_of": None,
            }
        return _snapshot(job)
