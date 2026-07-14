import pytest

from backend.services.shared import diagnosis_refresh_jobs as jobs


@pytest.fixture(autouse=True)
def reset_jobs():
    with jobs._lock:
        jobs._jobs.clear()
        jobs._active_by_code.clear()
    yield
    with jobs._lock:
        jobs._jobs.clear()
        jobs._active_by_code.clear()


def test_start_job_returns_done_when_cache_fresh(monkeypatch):
    monkeypatch.setattr(jobs.profile_service, "is_profile_fresh", lambda code, ttl_hours=24: True)

    out = jobs.start_refresh_job("110011")

    assert out["fund_code"] == "110011"
    assert out["status"] == "done"
    assert out["job_id"]


def test_start_job_single_flight(monkeypatch):
    monkeypatch.setattr(jobs.profile_service, "is_profile_fresh", lambda code, ttl_hours=24: False)
    monkeypatch.setattr(jobs, "_submit_refresh", lambda job: None)

    first = jobs.start_refresh_job("110011")
    second = jobs.start_refresh_job("110011")

    assert first["job_id"] == second["job_id"]
    assert second["status"] in {"started", "running"}


def test_get_refresh_job_missing():
    out = jobs.get_refresh_job("110011", "missing")

    assert out["status"] == "missing"
