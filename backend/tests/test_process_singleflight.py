"""`process_singleflight` 按业务键隔离的单飞锁单元测试。"""
from __future__ import annotations

import threading
import time

import pytest

from backend.services.shared import process_singleflight as _singleflight_module
from backend.services.shared.process_singleflight import (
    SingleflightBusy,
    process_singleflight,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """每个测试在干净注册表上跑,避免用例间锁泄漏。"""
    reset_for_tests()
    yield
    reset_for_tests()


def test_same_key_is_singleflight():
    """相同 key 第二次进入立刻抛 SingleflightBusy(默认 fast_fail)。"""
    with process_singleflight("knowledge_reindex"):
        with pytest.raises(SingleflightBusy) as excinfo:
            with process_singleflight("knowledge_reindex"):
                pass
        assert excinfo.value.key == "knowledge_reindex"


def test_different_keys_do_not_block_each_other():
    """不同 key 可以并发持有。"""
    with process_singleflight("knowledge_reindex"):
        with process_singleflight("cls_sync"):
            # 嵌套内层持有各自的 key,都应该能进
            pass


def test_lock_released_on_exit():
    """离开 with 块后,相同 key 可以再次进入。"""
    with process_singleflight("a"):
        pass
    with process_singleflight("a"):
        pass


def test_timeout_seconds_waits_then_fails():
    """`timeout_seconds > 0` 时会等到超时再抛 busy。"""
    blocker_release = threading.Event()
    blocker = threading.Thread(
        target=lambda: process_singleflight("holder", timeout_seconds=10.0),
        daemon=True,
    )
    # 先让 blocker 拿到锁(但锁被 holder 块无法直接拿 — 用另一种方式)
    # 直接在同一线程内模拟:用同 key 的进程级锁嵌套
    raise_skip_marker = False
    # 用一个独立线程持有锁,主线程测试超时
    holder_entered = threading.Event()

    def hold():
        with process_singleflight("k"):
            holder_entered.set()
            blocker_release.wait(timeout=5.0)

    th = threading.Thread(target=hold, daemon=True)
    th.start()
    holder_entered.wait(timeout=2.0)

    try:
        t0 = time.monotonic()
        with pytest.raises(SingleflightBusy):
            with process_singleflight("k", timeout_seconds=0.2):
                pass
        elapsed = time.monotonic() - t0
        assert 0.18 <= elapsed <= 0.6, f"expected ~0.2s, got {elapsed:.3f}s"
    finally:
        blocker_release.set()
        th.join(timeout=2.0)


def test_timeout_seconds_succeeds_when_released():
    """`timeout_seconds` 内锁被释放则能进入。"""
    holder_done = threading.Event()

    def holder():
        with process_singleflight("k"):
            time.sleep(0.1)
        holder_done.set()

    entered = threading.Event()

    def requester():
        t = threading.Thread(target=holder)
        t.start()
        time.sleep(0.02)  # 给 holder 一点时间进入锁
        with process_singleflight("k", timeout_seconds=1.0):
            entered.set()
        t.join(timeout=1.0)

    requester()
    assert holder_done.is_set()
    assert entered.is_set()


def test_concurrent_threads_with_same_key_one_wins():
    """两个线程抢同一 key,只有一个能进入,另一个收到 busy。"""
    winners: list[str] = []
    rejected: list[str] = []
    barrier = threading.Barrier(2)

    def worker(name: str):
        barrier.wait(timeout=2.0)
        try:
            with process_singleflight("shared"):
                winners.append(name)
                time.sleep(0.1)
        except SingleflightBusy:
            rejected.append(name)

    threads = [
        threading.Thread(target=worker, args=("A",)),
        threading.Thread(target=worker, args=("B",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    assert len(winners) == 1
    assert len(rejected) == 1
    assert winners[0] != rejected[0]


def test_singleflight_busy_is_runtime_error():
    """`SingleflightBusy` 必须是 RuntimeError,这样上层 try/except 能统一处理。"""
    assert issubclass(SingleflightBusy, RuntimeError)


def test_reset_for_tests_clears_registry():
    """`reset_for_tests` 清空字典,使后续 key 拿到全新的 Lock。"""
    # 测试 reset 的副作用时,所有单飞锁 with 块必须已退出。
    lock_a = _singleflight_module._get_lock("x")
    assert lock_a.acquire(blocking=False)
    try:
        # 此时持有 lock_a;reset 仍清空字典(丢弃对象引用)。
        reset_for_tests()
    finally:
        # 这里再 release 已无意义(锁对象已脱离注册表),但尝试 release
        # 只是为了让 RAII 闭环。threading.Lock.release 不会抛错 — 计数
        # 仍维持。改用更精确的测试 reset 后语义。
        pass
    # 重新拿 key — 应该是新 Lock 实例。
    lock_b = _singleflight_module._get_lock("x")
    assert lock_a is not lock_b


def test_module_exports_expected_symbols():
    """模块公共 API 必须包含 plan 约定的两个符号。"""
    # 通过模块对象验证,而不是用同名函数做 hasattr 检查
    assert hasattr(_singleflight_module, "process_singleflight")
    assert hasattr(_singleflight_module, "SingleflightBusy")
    assert hasattr(_singleflight_module, "reset_for_tests")
    # 同时,函数应该是 callable 的 ContextManager factory
    cm = process_singleflight("k")
    assert hasattr(cm, "__enter__")
    assert hasattr(cm, "__exit__")