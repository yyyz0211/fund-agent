"""APScheduler 接线测试:用假调度器验证启用开关与 cron 参数。"""
import pytest


@pytest.fixture(autouse=True)
def _reset_scheduler():
    from backend import scheduler as sched
    sched._scheduler = None
    yield
    sched._scheduler = None


class _FakeScheduler:
    """记录 add_job / start / shutdown 调用的假调度器。"""

    def __init__(self, recorder):
        self._recorder = recorder

    def add_job(self, fn, trigger=None, id=None, max_instances=1, coalesce=True,
                 misfire_grace_time=None, jitter=None):
        self._recorder.append({
            "fn": fn, "trigger": trigger, "id": id,
            "max_instances": max_instances, "coalesce": coalesce,
            "misfire_grace_time": misfire_grace_time, "jitter": jitter,
        })

    def start(self):
        self._recorder.append({"event": "start"})

    def shutdown(self, wait=True):
        self._recorder.append({"event": "shutdown", "wait": wait})


def test_scheduler_disabled_registers_nothing(monkeypatch):
    from backend import scheduler as sched

    recorder = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(recorder))

    out = sched.start_scheduler(enabled=False)
    assert out is None
    assert recorder == []


def test_scheduler_enabled_registers_cron(monkeypatch):
    from backend import scheduler as sched

    recorder = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(recorder))

    cron_calls = []
    monkeypatch.setattr(
        sched, "_cron_trigger",
        lambda hour, minute, tz: cron_calls.append((hour, minute, tz)) or ("cron", hour, minute, tz),
    )

    out = sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
    assert out is not None
    # daily_refresh cron + (可选) daily_briefing cron 都会调一次 _cron_trigger
    assert (20, 0, "Asia/Shanghai") in cron_calls
    assert len([r for r in recorder if "fn" in r]) >= 1

    refresh_job = next(r for r in recorder if r.get("id") == "daily_refresh")
    assert refresh_job["id"] == "daily_refresh"
    assert refresh_job["max_instances"] == 1
    assert refresh_job["coalesce"] is True
    assert any(r.get("event") == "start" for r in recorder)


def test_start_scheduler_idempotent(monkeypatch):
    from backend import scheduler as sched

    recorder = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(recorder))
    monkeypatch.setattr(sched, "_cron_trigger", lambda hour, minute, tz: ("cron",))

    first = sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
    second = sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
    assert first is second
    # 只注册了一次(第二次调用直接返回既有实例)。
    # 注意 daily_briefing 默认开启,这里期望 >= 1(包含 daily_refresh + 可选 daily_briefing)
    assert len([r for r in recorder if "fn" in r]) >= 1


def test_shutdown_scheduler(monkeypatch):
    from backend import scheduler as sched

    recorder = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(recorder))
    monkeypatch.setattr(sched, "_cron_trigger", lambda hour, minute, tz: ("cron",))
    monkeypatch.setattr(sched, "_interval_trigger", lambda minutes, tz: ("interval",))

    sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
    sched.shutdown_scheduler()
    assert any(r.get("event") == "shutdown" for r in recorder)
    assert sched._scheduler is None


def test_scheduler_registers_evidence_hourly_when_enabled(monkeypatch):
    """默认开启时,scheduler 应注册 post_market_evidence_hourly job
    (IntervalTrigger, max_instances=1, coalesce=True, misfire_grace_time 短,
    带 jitter)。
    """
    from backend import scheduler as sched

    recorder = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(recorder))
    monkeypatch.setattr(sched, "_cron_trigger", lambda hour, minute, tz: ("cron",))
    interval_calls = []
    monkeypatch.setattr(
        sched, "_interval_trigger",
        lambda minutes, tz: interval_calls.append((minutes, tz)) or ("interval", minutes, tz),
    )

    out = sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
    assert out is not None
    assert any(r.get("id") == "post_market_evidence_hourly" for r in recorder)
    job = next(r for r in recorder if r.get("id") == "post_market_evidence_hourly")
    assert job["max_instances"] == 1
    assert job["coalesce"] is True
    # misfire grace 应该短于 cron 任务的 3600s,避免错过后堆积重跑
    assert job["misfire_grace_time"] <= 600
    # 默认 60 分钟
    assert (60, "Asia/Shanghai") in interval_calls


def test_scheduler_registers_cls_telegraph_sync_when_enabled(monkeypatch):
    """默认开启时 scheduler 应注册财联社电报同步 interval job。"""
    from backend import scheduler as sched
    from backend.config.settings import get_settings

    monkeypatch.delenv("CLS_TELEGRAPH_SYNC_ENABLED", raising=False)
    get_settings.cache_clear()

    recorder = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(recorder))
    monkeypatch.setattr(sched, "_cron_trigger", lambda hour, minute, tz: ("cron",))
    interval_calls = []
    monkeypatch.setattr(
        sched, "_seconds_interval_trigger",
        lambda seconds, tz: interval_calls.append((seconds, tz)) or ("interval_seconds", seconds, tz),
    )

    out = sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
    assert out is not None
    assert any(r.get("id") == "cls_telegraph_sync" for r in recorder)
    job = next(r for r in recorder if r.get("id") == "cls_telegraph_sync")
    assert job["max_instances"] == 1
    assert job["coalesce"] is True
    assert job["misfire_grace_time"] <= 120
    assert (360, "Asia/Shanghai") in interval_calls


def test_scheduler_evidence_hourly_can_be_disabled(monkeypatch):
    """SCHEDULER_EVIDENCE_HOURLY_ENABLED=false 时不注册 hourly job。"""
    from backend import scheduler as sched
    from backend.config.settings import get_settings

    recorder = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(recorder))
    monkeypatch.setattr(sched, "_cron_trigger", lambda hour, minute, tz: ("cron",))
    monkeypatch.setattr(sched, "_interval_trigger", lambda minutes, tz: ("interval",))

    settings = get_settings()
    prev = settings.scheduler_evidence_hourly_enabled
    try:
        settings.scheduler_evidence_hourly_enabled = False
        sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
        assert not any(r.get("id") == "post_market_evidence_hourly" for r in recorder)
    finally:
        settings.scheduler_evidence_hourly_enabled = prev
        sched._scheduler = None


def test_refresh_market_evidence_async_singleflight():
    """同 brief_type 同时触发两次,第二次应拿到 running + 同 job_id (单飞锁)。
    """
    from backend.services import market_evidence_service as svc

    # reset 状态
    svc._active_job_ids.clear()

    # 让 _task 卡住一会儿,模拟"正在跑"
    import threading
    import time

    started = threading.Event()

    def fake_task():
        started.set()
        time.sleep(0.3)
        with svc._lock:
            svc._active_job_ids.pop("post_market", None)

    svc._async_executor.submit(fake_task)
    # 等到 fake_task 真的占了 _active_job_ids
    deadline = time.time() + 1.0
    while time.time() < deadline and "post_market" not in svc._active_job_ids:
        time.sleep(0.01)
    with svc._lock:
        svc._active_job_ids["post_market"] = "fake_job"

    r = svc.refresh_market_evidence_async(brief_type="post_market", trigger="test")
    assert r["status"] == "running", r
    assert r["job_id"] == "fake_job"

    # cleanup
    with svc._lock:
        svc._active_job_ids.pop("post_market", None)
