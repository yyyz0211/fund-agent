from __future__ import annotations

from backend.services.briefing import _state
from backend.services.briefing import jobs


def setup_function():
    _state.reset_for_tests()


def teardown_function():
    _state.reset_for_tests()


def test_get_last_run_returns_empty_snapshot():
    assert _state.get_last_run() == {
        "last_run_at": None,
        "trigger": None,
        "total_funds": 0,
        "succeeded": 0,
        "failed": 0,
        "failures": [],
    }


def test_last_run_is_copied_on_write_and_read():
    snapshot = {
        "last_run_at": "2026-07-16T12:00:00",
        "trigger": "test",
        "total_funds": 1,
        "succeeded": 1,
        "failed": 0,
        "failures": [],
    }
    _state.update_last_run(snapshot)

    result = _state.get_last_run()
    result["trigger"] = "mutated"

    assert _state.get_last_run()["trigger"] == "test"


def test_active_job_claim_release_and_reset():
    assert _state.claim_active_job("job-a") is None
    assert _state.claim_active_job("job-b") == "job-a"

    _state.release_active_job("job-b")
    assert _state.claim_active_job("job-c") == "job-a"

    _state.release_active_job("job-a")
    assert _state.claim_active_job("job-c") is None

    _state.reset_for_tests()
    assert _state.claim_active_job("job-d") is None


class CapturingExecutor:
    def __init__(self):
        self.tasks = []

    def submit(self, fn):
        self.tasks.append(fn)
        return object()


def test_start_run_async_is_singleflight_and_releases_after_task(monkeypatch):
    executor = CapturingExecutor()
    calls = []
    monkeypatch.setattr(jobs, "_async_executor", executor)
    monkeypatch.setattr(
        jobs.workflow,
        "run_daily_briefing",
        lambda **kwargs: calls.append(kwargs),
    )

    first = jobs.start_run_async(
        trigger="manual",
        brief_type="pre_market",
        model="model",
    )
    duplicate = jobs.start_run_async(brief_type="pre_market", model="model")

    assert first["status"] == "started"
    assert duplicate == {
        "status": "running",
        "job_id": first["job_id"],
        "brief_type": "pre_market",
    }
    assert len(executor.tasks) == 1

    executor.tasks[0]()

    assert calls == [{
        "trigger": "manual",
        "brief_type": "pre_market",
        "model": "model",
    }]
    third = jobs.start_run_async(brief_type="pre_market", model="model")
    assert third["status"] == "started"


def test_start_run_async_releases_claim_when_workflow_raises(monkeypatch):
    import pytest

    executor = CapturingExecutor()
    monkeypatch.setattr(jobs, "_async_executor", executor)

    def fail(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs.workflow, "run_daily_briefing", fail)
    first = jobs.start_run_async(model="model")

    with pytest.raises(RuntimeError, match="boom"):
        executor.tasks[0]()

    second = jobs.start_run_async(model="model")
    assert first["job_id"] != second["job_id"]


def test_public_status_and_reset_delegate_to_state():
    _state.update_last_run({
        "last_run_at": "2026-07-16T12:00:00",
        "trigger": "test",
        "total_funds": 0,
        "succeeded": 0,
        "failed": 0,
        "failures": [],
    })

    assert jobs.get_last_run()["trigger"] == "test"

    jobs.reset_for_tests()
    assert jobs.get_last_run()["last_run_at"] is None
