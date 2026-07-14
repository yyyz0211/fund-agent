"""Background preload jobs for newly-added watchlist funds.

The project is a local single-user app. A small in-process queue is enough to
avoid blocking watchlist writes on slow AkShare calls while still warming the
local cache soon after a fund is added.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from uuid import uuid4

from backend.db import repository as repo
from backend.db.session import get_session
from backend.services.fund import fund_profile_service as profile_service
from backend.services.fund import fund_service as fs


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="watchlist-preload")
_lock = Lock()
_jobs: dict[str, dict] = {}
_active_by_code: dict[str, str] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _snapshot(job: dict) -> dict:
    return dict(job)


def _set_watchlist_preload(fund_code: str, *,
                           status: str | None = None) -> None:
    s = get_session()
    try:
        repo.update_watchlist_preload(
            s,
            fund_code,
            status=status,
        )
    finally:
        s.close()


def start_preload_job(fund_code: str, *, run_inline: bool = False) -> dict:
    """Start or reuse a bounded background preload job.

    `run_inline` is reserved for deterministic tests; production callers should
    leave it at the default so watchlist writes return immediately.
    """
    with _lock:
        active_id = _active_by_code.get(fund_code)
        if active_id and _jobs.get(active_id, {}).get("status") in {"pending", "running"}:
            return _snapshot(_jobs[active_id])
        job_id = f"{fund_code}-{uuid4().hex[:8]}"
        job = {
            "job_id": job_id,
            "fund_code": fund_code,
            "status": "pending",
            "started_at": _now(),
            "finished_at": None,
            "missing_data": [],
            "errors": [],
            "as_of": None,
        }
        _jobs[job_id] = job
        _active_by_code[fund_code] = job_id
    _set_watchlist_preload(fund_code, status="pending")
    if run_inline:
        _run_preload(job_id)
        return get_preload_job(fund_code, job_id)
    _executor.submit(_run_preload, job_id)
    return _snapshot(job)


def _run_preload(job_id: str) -> None:
    with _lock:
        job = _jobs[job_id]
        job["status"] = "running"
    fund_code = job["fund_code"]
    _set_watchlist_preload(fund_code, status="running")

    missing_data: list[str] = []
    errors: list[str] = []
    successful_steps = 0
    as_of = None

    try:
        try:
            fund_result = fs.refresh_fund(fund_code)
            if isinstance(fund_result, dict) and "error" in fund_result:
                errors.append(fund_result["error"])
                missing_data.extend(["fund", "nav"])
            else:
                successful_steps += 1
                as_of = (fund_result or {}).get("as_of")
                if (fund_result or {}).get("fund_info_warn"):
                    errors.append((fund_result or {})["fund_info_warn"])
                    missing_data.append("fund")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"refresh_fund failed: {exc}")
            missing_data.extend(["fund", "nav"])

        try:
            profile_result = profile_service.refresh_profile(fund_code)
            successful_steps += 1
            as_of = profile_result.get("as_of") or as_of
            missing_data.extend(profile_result.get("missing_data") or [])
            errors.extend(profile_result.get("errors") or [])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"refresh_profile failed: {exc}")
            missing_data.append("profile")

        missing_data = list(dict.fromkeys(missing_data))
        errors = list(dict.fromkeys(errors))
        if successful_steps == 0:
            status = "failed"
        elif missing_data or errors:
            status = "partial"
        else:
            status = "done"
        _set_watchlist_preload(fund_code, status=status)
        with _lock:
            job["status"] = status
            job["missing_data"] = missing_data
            job["errors"] = errors
            job["as_of"] = as_of
    finally:
        with _lock:
            job = _jobs.get(job_id)
            if job:
                job["finished_at"] = _now()
                if _active_by_code.get(fund_code) == job_id:
                    _active_by_code.pop(fund_code, None)


def get_preload_job(fund_code: str, job_id: str) -> dict:
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
                "errors": ["preload job not found"],
                "as_of": None,
            }
        return _snapshot(job)
