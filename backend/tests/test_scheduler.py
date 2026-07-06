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

    def add_job(self, fn, trigger=None, id=None, max_instances=1, coalesce=True):
        self._recorder.append({
            "fn": fn, "trigger": trigger, "id": id,
            "max_instances": max_instances, "coalesce": coalesce,
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
    assert cron_calls == [(20, 0, "Asia/Shanghai")]

    job = next(r for r in recorder if "fn" in r)
    assert job["id"] == "daily_refresh"
    assert job["max_instances"] == 1
    assert job["coalesce"] is True
    assert any(r.get("event") == "start" for r in recorder)


def test_start_scheduler_idempotent(monkeypatch):
    from backend import scheduler as sched

    recorder = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(recorder))
    monkeypatch.setattr(sched, "_cron_trigger", lambda hour, minute, tz: ("cron",))

    first = sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
    second = sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
    assert first is second
    # 只注册了一个 job(第二次调用直接返回既有实例)。
    assert len([r for r in recorder if "fn" in r]) == 1


def test_shutdown_scheduler(monkeypatch):
    from backend import scheduler as sched

    recorder = []
    monkeypatch.setattr(sched, "_build_scheduler", lambda: _FakeScheduler(recorder))
    monkeypatch.setattr(sched, "_cron_trigger", lambda hour, minute, tz: ("cron",))

    sched.start_scheduler(enabled=True, hour=20, minute=0, timezone="Asia/Shanghai")
    sched.shutdown_scheduler()
    assert any(r.get("event") == "shutdown" for r in recorder)
    assert sched._scheduler is None
