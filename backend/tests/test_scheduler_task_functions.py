"""Scheduler domain task-function behavior."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.unit


def test_thin_market_tasks_preserve_domain_arguments(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks

    calls: list[tuple] = []
    monkeypatch.setattr(
        tasks.scheduled_refresh,
        "refresh_all_watchlist",
        lambda *, trigger: calls.append(("refresh", trigger)),
    )
    monkeypatch.setattr(
        tasks.market_intel_service,
        "collect_market_intel",
        lambda session, brief_type: calls.append(
            ("intel", session, brief_type)
        ),
    )
    monkeypatch.setattr(
        tasks.market_evidence_service,
        "refresh_market_evidence_async",
        lambda **kwargs: calls.append(("evidence", kwargs)),
    )

    tasks.run_daily_refresh()
    tasks.run_morning_market_intel()
    tasks.run_post_market_intel()
    tasks.run_pre_market_evidence()
    tasks.run_post_market_evidence()
    tasks.run_post_market_evidence_hourly()

    assert calls == [
        ("refresh", "scheduled"),
        ("intel", None, "morning"),
        ("intel", None, "post_market"),
        ("evidence", {"brief_type": "pre_market", "trigger": "scheduled"}),
        ("evidence", {"brief_type": "post_market", "trigger": "scheduled"}),
        (
            "evidence",
            {"brief_type": "post_market", "trigger": "scheduled_hourly"},
        ),
    ]


def test_daily_briefing_builds_and_injects_model(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks

    model = object()
    calls: list[tuple] = []
    monkeypatch.setattr(tasks, "_build_briefing_model", lambda: model)
    monkeypatch.setattr(
        tasks.briefing_workflow,
        "run_daily_briefing",
        lambda **kwargs: calls.append(("briefing", kwargs)),
    )

    tasks.run_daily_briefing()

    assert calls == [
        ("briefing", {"trigger": "scheduled", "model": model}),
    ]


def test_daily_briefing_skips_only_model_configuration_error(
    monkeypatch,
) -> None:
    from backend.scheduler import task_functions as tasks

    warnings = []
    monkeypatch.setattr(
        tasks.logger,
        "warning",
        lambda message, *args: warnings.append((message, args)),
    )
    monkeypatch.setattr(
        tasks,
        "_build_briefing_model",
        lambda: (_ for _ in ()).throw(RuntimeError("missing key")),
    )
    monkeypatch.setattr(
        tasks.briefing_workflow,
        "run_daily_briefing",
        lambda **_kwargs: pytest.fail("workflow must be skipped"),
    )

    tasks.run_daily_briefing()

    assert len(warnings) == 1
    assert warnings[0][0] == "[scheduler] daily_briefing skipped: %s"
    assert isinstance(warnings[0][1][0], RuntimeError)
    assert str(warnings[0][1][0]) == "missing key"


def test_daily_briefing_propagates_workflow_errors(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks

    monkeypatch.setattr(tasks, "_build_briefing_model", lambda: object())
    monkeypatch.setattr(
        tasks.briefing_workflow,
        "run_daily_briefing",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("workflow failed")),
    )

    with pytest.raises(ValueError, match="workflow failed"):
        tasks.run_daily_briefing()


def test_cls_sync_uses_stable_scheduler_singleflight_key(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks

    calls: list[tuple] = []

    @contextmanager
    def fake_singleflight(key, **kwargs):
        calls.append(("lock", key, kwargs))
        yield

    monkeypatch.setattr(tasks, "process_singleflight", fake_singleflight)
    monkeypatch.setattr(
        tasks.cls_telegraph_sync_service,
        "run_scheduled_cls_telegraph_sync",
        lambda: calls.append(("run",)),
    )

    tasks.run_cls_telegraph_sync()

    assert calls == [
        ("lock", "scheduler.cls_telegraph_sync", {}),
        ("run",),
    ]


def test_cls_sync_skips_when_singleflight_is_busy(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks
    from backend.services.shared.process_singleflight import SingleflightBusy

    warnings = []
    monkeypatch.setattr(
        tasks.logger,
        "warning",
        lambda message, *args: warnings.append((message, args)),
    )

    @contextmanager
    def busy_singleflight(_key, **_kwargs):
        raise SingleflightBusy("scheduler.cls_telegraph_sync")
        yield

    monkeypatch.setattr(tasks, "process_singleflight", busy_singleflight)
    monkeypatch.setattr(
        tasks.cls_telegraph_sync_service,
        "run_scheduled_cls_telegraph_sync",
        lambda: pytest.fail("busy task must not run"),
    )

    tasks.run_cls_telegraph_sync()

    assert len(warnings) == 1
    assert warnings[0][0] == "[scheduler] job=cls_telegraph_sync skipped: %s"
    assert isinstance(warnings[0][1][0], SingleflightBusy)


def test_knowledge_task_creates_and_starts_scheduled_job(monkeypatch) -> None:
    from backend.scheduler import task_functions as tasks

    calls: list[tuple] = []

    @contextmanager
    def fake_singleflight(key, **kwargs):
        calls.append(("lock", key, kwargs))
        yield

    monkeypatch.setattr(tasks, "process_singleflight", fake_singleflight)
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "create_job",
        lambda *, trigger: calls.append(("create", trigger))
        or SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "run_job_in_background",
        lambda job_id, *, pipeline_kwargs: calls.append(
            ("run", job_id, pipeline_kwargs)
        ),
    )

    tasks.run_knowledge_ingest_index()

    assert calls == [
        (
            "lock",
            "scheduler.knowledge_ingest_index",
            {"timeout_seconds": 2.0},
        ),
        ("create", "scheduled"),
        ("run", 42, {"trigger": "scheduled"}),
    ]


def test_knowledge_task_skips_when_singleflight_is_busy(
    monkeypatch,
) -> None:
    from backend.scheduler import task_functions as tasks
    from backend.services.shared.process_singleflight import SingleflightBusy

    warnings = []
    monkeypatch.setattr(
        tasks.logger,
        "warning",
        lambda message, *args: warnings.append((message, args)),
    )

    @contextmanager
    def busy_singleflight(_key, **_kwargs):
        raise SingleflightBusy("scheduler.knowledge_ingest_index")
        yield

    monkeypatch.setattr(tasks, "process_singleflight", busy_singleflight)
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "create_job",
        lambda **_kwargs: pytest.fail("busy task must not create a job"),
    )

    tasks.run_knowledge_ingest_index()

    assert warnings == [
        (
            "[scheduler] knowledge_ingest_index skipped: "
            "previous pipeline still finalizing",
            (),
        )
    ]


def test_knowledge_task_returns_when_job_creation_fails(
    monkeypatch,
) -> None:
    from backend.scheduler import task_functions as tasks

    exceptions = []
    monkeypatch.setattr(
        tasks.logger,
        "exception",
        lambda message, *args: exceptions.append((message, args)),
    )

    @contextmanager
    def fake_singleflight(_key, **_kwargs):
        yield

    monkeypatch.setattr(tasks, "process_singleflight", fake_singleflight)
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "create_job",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("create")),
    )
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "run_job_in_background",
        lambda *_args, **_kwargs: pytest.fail("missing job must not start"),
    )

    tasks.run_knowledge_ingest_index()

    assert exceptions == [
        ("[scheduler] knowledge pipeline failed to create job record", ())
    ]


def test_knowledge_task_marks_job_failed_when_background_start_fails(
    monkeypatch,
) -> None:
    from backend.scheduler import task_functions as tasks

    @contextmanager
    def fake_singleflight(_key, **_kwargs):
        yield

    monkeypatch.setattr(tasks, "process_singleflight", fake_singleflight)
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "create_job",
        lambda *, trigger: SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "run_job_in_background",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("submit")),
    )
    failures: list[tuple] = []
    monkeypatch.setattr(
        tasks.knowledge_reindex_jobs,
        "mark_failed",
        lambda job_id, *, error: failures.append((job_id, error)),
    )

    tasks.run_knowledge_ingest_index()

    assert failures == [(42, "RuntimeError: submit")]
