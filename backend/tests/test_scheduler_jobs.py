"""Scheduler JobSpec 到 APScheduler 参数的契约测试。"""
from __future__ import annotations

from backend.scheduler.jobs import cron_job, interval_job


def test_cron_job_preserves_trigger_kwargs():
    spec = cron_job("daily", lambda: None, {"hour": 8, "minute": 30, "timezone": "Asia/Shanghai"})

    kwargs = spec.to_apscheduler_kwargs()

    assert kwargs["hour"] == 8
    assert kwargs["minute"] == 30
    assert kwargs["timezone"] == "Asia/Shanghai"
    assert "callable" not in kwargs


def test_interval_job_preserves_trigger_kwargs():
    spec = interval_job("sync", lambda: None, {"seconds": 90})

    assert spec.to_apscheduler_kwargs()["seconds"] == 90


def test_optional_scheduler_kwargs_are_omitted_when_unset():
    spec = cron_job("daily", lambda: None, {"hour": 8})

    kwargs = spec.to_apscheduler_kwargs()

    assert "misfire_grace_time" not in kwargs
    assert "jitter" not in kwargs
