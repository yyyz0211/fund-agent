"""每日定时刷新任务的 APScheduler 接线。

进程内单例:`BackgroundScheduler` 随 FastAPI 进程启动而启动、随进程停止而停止。
调度到点时调用 `scheduled_refresh.refresh_all_watchlist`,遍历自选池刷新 NAV + 画像。
`max_instances=1` + `coalesce=True` 保证上一次没跑完时不会叠加触发。

写入型 job（`cls_telegraph_sync`、`knowledge_ingest_index`）额外走
`scheduler_lock` 进程级单飞锁，确保同进程内任意时刻只有一个写入型
scheduler job 在跑。这避免了 SQLite 单文件场景下并发写锁 + QueuePool
排干的双层放大故障（见 [`terminals/9.txt`](../../.cursor/projects/Users-leon-fund-agent/terminals/9.txt)）。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.config.settings import get_settings
from backend.services import briefing_service
from backend.services.scheduled_refresh import refresh_all_watchlist
from backend.services.scheduler_lock import SchedulerLockBusy, scheduler_lock


logger = logging.getLogger(__name__)


_scheduler: BackgroundScheduler | None = None


def _safe_job(label: str, fn, *args, **kwargs):
    """把 scheduler job 主体包进 scheduler_lock。

    - 锁空闲时正常执行；
    - 锁被占（fast_fail=True）时打 warning 并直接放弃本次触发，由
      APScheduler 在下一轮 interval 自然重试，不会叠加积压；
    - 业务异常向上抛给 APScheduler 记录（保持现有行为）。
    """
    try:
        with scheduler_lock(label):
            return fn(*args, **kwargs)
    except SchedulerLockBusy as exc:
        logger.warning(
            "[scheduler] job=%s skipped: %s",
            label, exc,
        )
        return None


def _build_scheduler() -> BackgroundScheduler:
    """构造调度器实例。抽成函数便于测试用假对象替换。"""
    return BackgroundScheduler(timezone="Asia/Shanghai")


def _cron_trigger(hour: int, minute: int, tz: str) -> CronTrigger:
    return CronTrigger(hour=hour, minute=minute, timezone=tz)


def _interval_trigger(minutes: int, tz: str) -> IntervalTrigger:
    """每 N 分钟触发一次。minutes<=0 视为关闭。"""
    return IntervalTrigger(minutes=max(1, int(minutes)), timezone=tz)


def _seconds_interval_trigger(seconds: int, tz: str) -> IntervalTrigger:
    """每 N 秒触发一次。seconds<=0 视为 60 秒。"""
    return IntervalTrigger(seconds=max(1, int(seconds)), timezone=tz)


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

    # market intel: morning (09:35) + post_market (15:35)
    from backend.services import market_intel_service
    scheduler.add_job(
        lambda: market_intel_service.collect_market_intel(None, "morning"),
        trigger=_cron_trigger(9, 35, timezone),
        id="morning_market_intel",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        lambda: market_intel_service.collect_market_intel(None, "post_market"),
        trigger=_cron_trigger(15, 35, timezone),
        id="post_market_market_intel",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # market evidence 采集 (Wave 1):
    # pre_market 08:30 → 抓宏观(FRED) + 政策(NMPA/CSRC/PBOC/NDRC/MOF)
    # post_market 16:00 → 抓政策 + 公告 + 宏观 + 行业热点(sector)
    from backend.services import market_evidence_service
    if bool(getattr(settings, "scheduler_evidence_enabled", True)):
        scheduler.add_job(
            lambda: market_evidence_service.refresh_market_evidence_async(
                brief_type="pre_market", trigger="scheduled",
            ),
            trigger=_cron_trigger(8, 30, timezone),
            id="pre_market_evidence",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            lambda: market_evidence_service.refresh_market_evidence_async(
                brief_type="post_market", trigger="scheduled",
            ),
            trigger=_cron_trigger(16, 0, timezone),
            id="post_market_evidence",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

    # market evidence hourly 增量(post_market only — pre_market 没必要按小时拉)。
    # 与 16:00 cron 共享同 service + 同一 brief_type 走 _lock 单飞:
    #   cron 撞上 hourly 时, 第二次 submit 会拿到现有 job_id 并返回 "running",
    #   不会叠加触发;DB 唯一键 (trade_date, brief_type, source_url) 保证即使真
    #   并发跑两次也不会写重复行(upsert 是 select-then-insert, 第二次是 no-op)。
    # 用户可调 scheduler_evidence_hourly_minutes (默认 60) 或关闭
    # scheduler_evidence_hourly_enabled 来调整节奏。
    if bool(getattr(settings, "scheduler_evidence_hourly_enabled", True)):
        hourly_minutes = int(getattr(settings, "scheduler_evidence_hourly_minutes", 60))
        if hourly_minutes > 0:
            scheduler.add_job(
                lambda: market_evidence_service.refresh_market_evidence_async(
                    brief_type="post_market", trigger="scheduled_hourly",
                ),
                trigger=_interval_trigger(hourly_minutes, timezone),
                id="post_market_evidence_hourly",
                max_instances=1,
                coalesce=True,
                # 短 misfire grace — 5 分钟内补跑可接受, 超过直接丢
                # (下一轮会拉同样数据, 重复拉浪费但无害)
                misfire_grace_time=300,
                jitter=60,
            )

    if bool(getattr(settings, "cls_telegraph_sync_enabled", True)):
        from backend.services import cls_telegraph_sync_service
        interval_seconds = int(getattr(settings, "cls_telegraph_sync_interval_seconds", 60))
        if interval_seconds > 0:
            scheduler.add_job(
                lambda: _safe_job(
                    "cls_telegraph_sync",
                    cls_telegraph_sync_service.run_scheduled_cls_telegraph_sync,
                ),
                trigger=_seconds_interval_trigger(interval_seconds, timezone),
                id="cls_telegraph_sync",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=120,
                jitter=min(10, max(0, interval_seconds // 5)),
            )

    # 知识库增量流水线:从已落库的信息源中做 LLM 准入、向量索引和基金匹配。
    # 它依赖本地已有数据,不负责远程抓取;远程财联社电报同步由上面的
    # cls_telegraph_sync job 独立完成。默认 6 分钟一次,避免 LLM/索引任务过密。
    if bool(getattr(settings, "scheduler_knowledge_enabled", True)):
        from backend.services import knowledge_search_service
        knowledge_minutes = int(getattr(settings, "scheduler_knowledge_interval_minutes", 6))
        if knowledge_minutes > 0:
            scheduler.add_job(
                lambda: _safe_job(
                    "knowledge_ingest_index",
                    knowledge_search_service.run_knowledge_pipeline_once,
                    trigger="scheduled",
                ),
                trigger=_interval_trigger(knowledge_minutes, timezone),
                id="knowledge_ingest_index",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
                jitter=min(60, max(0, knowledge_minutes * 10)),
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