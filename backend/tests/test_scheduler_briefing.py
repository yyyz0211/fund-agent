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
    """每个测试前后重置 `backend.scheduler._scheduler` 状态。"""
    import backend.scheduler as sched_module
    sched_module._scheduler = None
    yield
    if sched_module._scheduler is not None:
        try:
            sched_module._scheduler.shutdown(wait=False)
        except Exception:
            pass
        sched_module._scheduler = None


class TestSchedulerBriefing:
    def test_scheduler_registers_both_jobs(self):
        import backend.scheduler as sched_module

        sched_module.start_scheduler(enabled=True)
        scheduler = sched_module._scheduler
        assert scheduler is not None
        assert scheduler.get_job("daily_refresh") is not None
        assert scheduler.get_job("daily_briefing") is not None

    def test_briefing_job_disabled_when_setting_false(self, monkeypatch):
        import backend.scheduler as sched_module

        monkeypatch.setenv("SCHEDULER_BRIEFING_ENABLED", "false")
        from backend.config.settings import get_settings
        get_settings.cache_clear()

        sched_module.start_scheduler(enabled=True)
        scheduler = sched_module._scheduler
        assert scheduler is not None
        assert scheduler.get_job("daily_refresh") is not None
        assert scheduler.get_job("daily_briefing") is None

    def test_briefing_job_uses_configured_hour_minute(self, monkeypatch):
        import backend.scheduler as sched_module

        monkeypatch.setenv("SCHEDULER_BRIEFING_CRON_HOUR", "18")
        monkeypatch.setenv("SCHEDULER_BRIEFING_CRON_MINUTE", "30")
        from backend.config.settings import get_settings
        get_settings.cache_clear()

        sched_module.start_scheduler(enabled=True)
        scheduler = sched_module._scheduler
        job = scheduler.get_job("daily_briefing")
        assert job is not None
        # APScheduler CronTrigger 在 hour/minute 字段直接暴露
        trigger = job.trigger
        fields = {f.name: f for f in trigger.fields}
        assert "18" in str(fields["hour"])
        assert "30" in str(fields["minute"])