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


def test_lock_default_is_fast_fail():
    """不传 timeout_seconds 时保持旧行为——非阻塞立即失败。"""
    with scheduler_lock("holder"):
        t0 = time.monotonic()
        with pytest.raises(SchedulerLockBusy):
            with scheduler_lock("requester"):
                pass
        elapsed = time.monotonic() - t0
        # 立即失败,不应该 sleep 等待
        assert elapsed < 0.1, f"expected fast fail within 100ms, got {elapsed:.3f}s"


def test_lock_timeout_seconds_waits_then_fails():
    """传 timeout_seconds 时等够时间后抛 SchedulerLockBusy。"""
    with scheduler_lock("holder"):
        t0 = time.monotonic()
        with pytest.raises(SchedulerLockBusy) as excinfo:
            with scheduler_lock("requester", timeout_seconds=0.3):
                pass
        elapsed = time.monotonic() - t0
        # 应该等待到 timeout,允许 ±100ms 抖动(轮询 sleep 50ms)
        assert 0.25 <= elapsed <= 0.6, f"expected ~0.3s, got {elapsed:.3f}s"
        assert "timed out" in str(excinfo.value)


def test_lock_timeout_seconds_succeeds_when_released():
    """传 timeout_seconds 时,锁在超时前释放应该能成功进入。"""
    holder_acquired = threading.Event()
    holder_release = threading.Event()
    requester_entered = threading.Event()

    def holder():
        with scheduler_lock("holder"):
            holder_acquired.set()
            holder_release.wait(timeout=2.0)

    def requester():
        holder_acquired.wait(timeout=2.0)
        # 给 holder 一点时间稳定在锁内,然后开始等
        time.sleep(0.05)
        try:
            with scheduler_lock("requester", timeout_seconds=1.5):
                requester_entered.set()
        except SchedulerLockBusy:
            pass

    t_holder = threading.Thread(target=holder)
    t_req = threading.Thread(target=requester)
    t_holder.start()
    t_req.start()

    # holder 进入后等 0.2s 释放,requester 应该能拿到锁
    holder_acquired.wait(timeout=1.0)
    time.sleep(0.2)
    holder_release.set()

    t_holder.join(timeout=2.0)
    t_req.join(timeout=2.0)
    assert requester_entered.is_set(), "requester should have entered the lock after holder released"