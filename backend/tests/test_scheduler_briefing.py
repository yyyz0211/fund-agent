"""scheduler briefing cron 注册测试。"""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """每个测试前后清 lru_cache,避免 settings 复用。"""
    from backend.config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_scheduler_module():
    """每个测试前后重置 runtime Scheduler 状态。"""
    import backend.scheduler as scheduler
    from backend.scheduler import runtime

    runtime._scheduler = None
    yield
    if scheduler.get_scheduler() is not None:
        try:
            scheduler.shutdown_scheduler()
        except Exception:
            pass
        runtime._scheduler = None


class TestSchedulerBriefing:
    def test_scheduler_registers_both_jobs(self):
        import backend.scheduler as scheduler

        scheduler.start_scheduler(enabled=True)
        active = scheduler.get_scheduler()
        assert active is not None
        assert active.get_job("daily_refresh") is not None
        assert active.get_job("daily_briefing") is not None

    def test_briefing_job_disabled_when_setting_false(self, monkeypatch):
        import backend.scheduler as scheduler

        monkeypatch.setenv("SCHEDULER_BRIEFING_ENABLED", "false")
        from backend.config.settings import get_settings
        get_settings.cache_clear()

        scheduler.start_scheduler(enabled=True)
        active = scheduler.get_scheduler()
        assert active is not None
        assert active.get_job("daily_refresh") is not None
        assert active.get_job("daily_briefing") is None

    def test_briefing_job_uses_configured_hour_minute(self, monkeypatch):
        import backend.scheduler as scheduler

        monkeypatch.setenv("SCHEDULER_BRIEFING_CRON_HOUR", "18")
        monkeypatch.setenv("SCHEDULER_BRIEFING_CRON_MINUTE", "30")
        from backend.config.settings import get_settings
        get_settings.cache_clear()

        scheduler.start_scheduler(enabled=True)
        active = scheduler.get_scheduler()
        assert active is not None
        job = active.get_job("daily_briefing")
        assert job is not None
        # APScheduler CronTrigger 在 hour/minute 字段直接暴露
        trigger = job.trigger
        fields = {f.name: f for f in trigger.fields}
        assert "18" in str(fields["hour"])
        assert "30" in str(fields["minute"])

    def test_registered_briefing_job_runs_workflow_with_scheduled_model(self):
        import backend.scheduler as scheduler
        from backend.scheduler import task_functions

        model = object()
        with (
            patch("backend.graph.model.build_model", return_value=model) as build_model,
            patch.object(
                task_functions.briefing_workflow,
                "run_daily_briefing",
            ) as run_daily_briefing,
        ):
            scheduler.start_scheduler(enabled=True)
            active = scheduler.get_scheduler()
            assert active is not None
            job = active.get_job("daily_briefing")
            assert job is not None

            job.func()

        build_model.assert_called_once_with()
        run_daily_briefing.assert_called_once_with(
            trigger="scheduled",
            model=model,
        )
