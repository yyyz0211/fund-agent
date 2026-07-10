"""scheduler_lock 进程级单飞锁的单元测试。"""
import threading
import time

import pytest

import backend.services.scheduler_lock as _scheduler_lock
from backend.services.scheduler_lock import (
    SchedulerLockBusy,
    scheduler_lock,
    try_acquire,
)


@pytest.fixture(autouse=True)
def _reset_lock():
    """每个测试结束确保锁被释放。"""
    yield
    # 重置模块内 owner 状态,避免跨测试污染
    _scheduler_lock._OWNER["label"] = None
    _scheduler_lock._OWNER["since"] = None


def test_lock_acquire_and_release():
    """基本 acquire/release。"""
    with scheduler_lock("test_job"):
        assert _scheduler_lock._OWNER["label"] == "test_job"
        assert _scheduler_lock._OWNER["since"] is not None
    assert _scheduler_lock._OWNER["label"] is None
    assert _scheduler_lock._OWNER["since"] is None


def test_lock_fast_fail_when_held():
    """锁被占时锁请求方立刻抛 SchedulerLockBusy。"""
    with scheduler_lock("holder"):
        with pytest.raises(SchedulerLockBusy) as excinfo:
            with scheduler_lock("requester"):
                pass
        assert "holder" in str(excinfo.value)
        assert "requester" in str(excinfo.value)


def test_lock_serializes_concurrent_callers():
    """两个线程同时抢锁, 只有一个能进, 另一个被 SchedulerLockBusy 拒绝。

    锁是非阻塞的（fast_fail），这是 scheduler 场景下的预期行为：
    不积压触发，让下一轮 interval tick 自然重试。
    """
    winners: list[str] = []
    rejected: list[str] = []
    barrier = threading.Barrier(2)

    def worker(name: str, hold_for: float):
        barrier.wait(timeout=2.0)
        try:
            with scheduler_lock(name):
                winners.append(name)
                time.sleep(hold_for)
        except SchedulerLockBusy:
            rejected.append(name)

    threads = [
        threading.Thread(target=worker, args=("A", 0.2)),
        threading.Thread(target=worker, args=("B", 0.2)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    # 一个赢、一个输（顺序不确定）
    assert len(winners) == 1
    assert len(rejected) == 1
    assert winners[0] != rejected[0]


def test_try_acquire_returns_guard_when_free():
    """try_acquire 在锁空闲时返回 guard。"""
    guard = try_acquire("manual")
    assert guard is not None
    guard.release()
    # 释放后能再次 acquire
    guard2 = try_acquire("manual2")
    assert guard2 is not None
    guard2.release()


def test_try_acquire_returns_none_when_held():
    """try_acquire 在锁被占时返回 None。"""
    with scheduler_lock("holder"):
        assert try_acquire("requester") is None