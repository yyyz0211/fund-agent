"""每日定时刷新任务的 APScheduler 接线。

进程内单例:`BackgroundScheduler` 随 FastAPI 进程启动而启动、随进程停止而停止。
调度到点时调用 `scheduled_refresh.refresh_all_watchlist`,遍历自选池刷新 NAV + 画像。
`max_instances=1` + `coalesce=True` 保证上一次没跑完时不会叠加触发。
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config.settings import get_settings
from backend.services import briefing_service
from backend.services.scheduled_refresh import refresh_all_watchlist


_scheduler: BackgroundScheduler | None = None


def _build_scheduler() -> BackgroundScheduler:
    """构造调度器实例。抽成函数便于测试用假对象替换。"""
    return BackgroundScheduler(timezone="Asia/Shanghai")


def _cron_trigger(hour: int, minute: int, tz: str) -> CronTrigger:
    return CronTrigger(hour=hour, minute=minute, timezone=tz)


def start_scheduler(*, enabled: bool | None = None,
                    hour: int | None = None,
                    minute: int | None = None,
                    timezone: str | None = None) -> BackgroundScheduler | None:
    """启动进程内 APScheduler,注册每日刷新 cron 任务。

    参数为空时回落到 `Settings` 配置。返回调度器实例(禁用时返回 None),
    方便测试内省。已启动时直接返回既有实例,避免重复注册。
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    if enabled is None:
        enabled = bool(settings.scheduler_enabled)
    if not enabled:
        return None

    if timezone is None:
        timezone = settings.scheduler_timezone
    if hour is None:
        hour = int(settings.scheduler_refresh_cron_hour)
    if minute is None:
        minute = int(settings.scheduler_refresh_cron_minute)

    scheduler = _build_scheduler()
    scheduler.add_job(
        lambda: refresh_all_watchlist(trigger="scheduled"),
        trigger=_cron_trigger(hour, minute, timezone),
        id="daily_refresh",
        max_instances=1,
        coalesce=True,
    )

    # 每日简报(Wave 3.3);独立 cron,可独立关闭。
    if bool(getattr(settings, "scheduler_briefing_enabled", True)):
        b_hour = int(getattr(settings, "scheduler_briefing_cron_hour", 17))
        b_minute = int(getattr(settings, "scheduler_briefing_cron_minute", 0))
        scheduler.add_job(
            lambda: briefing_service.run_daily_briefing(trigger="scheduled"),
            trigger=_cron_trigger(b_hour, b_minute, timezone),
            id="daily_briefing",
            max_instances=1,
            coalesce=True,
        )

    # 市场情报快照 job
    # morning: 09:35 (涨停池数据可能不完整)
    from backend.services import market_intel_service
    scheduler.add_job(
        lambda: market_intel_service.collect_market_intel(None, "morning"),
        trigger=_cron_trigger(9, 35, timezone),
        id="morning_market_intel",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    # post_market: 15:35 (涨停池数据完整)
    scheduler.add_job(
        lambda: market_intel_service.collect_market_intel(None, "post_market"),
        trigger=_cron_trigger(15, 35, timezone),
        id="post_market_market_intel",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    """停止调度器(进程退出时调用)。"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
