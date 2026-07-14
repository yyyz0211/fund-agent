"""process_singleflight 按业务键隔离的单进程单飞锁。

PostgreSQL 行级锁替代品：同 key 串行、不同 key 并发。
取代原全局单飞锁的"全局单实例"语义。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class SingleflightBusy(RuntimeError):
    """`process_singleflight(key)` 已被同一进程内的其他 caller 持有。

    Args:
        key: 触发冲突的业务键。
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"process_singleflight key already held: {key!r}")
        self.key = key


# 注册表受 `_registry_guard` 保护;`_locks` 的值是 per-key threading.Lock。
# 单进程内多线程共享同一字典,所以同 key 总是拿到同一把锁。
_registry_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _get_lock(key: str) -> threading.Lock:
    with _registry_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


@contextmanager
def process_singleflight(
    key: str,
    *,
    timeout_seconds: float = 0.0,
) -> Iterator[None]:
    """按 `key` 隔离的单进程单飞锁。

    与原全局单飞锁相比:
    - 不同 key 互不阻塞(原 label 是全局唯一)。
    - 仍然支持 fast_fail(`timeout_seconds=0`)和限时等待。

    Args:
        key: 业务键(如 `"scheduler.knowledge_ingest_index"` 或
            `"knowledge_reindex:42"`)。
        timeout_seconds: 等待锁的最长秒数。`<=0` 表示立刻失败,不等。

    Raises:
        SingleflightBusy: 锁被占且等待超时。
    """
    lock = _get_lock(key)
    if not lock.acquire(timeout=max(0.0, float(timeout_seconds))):
        raise SingleflightBusy(key)
    try:
        yield
    finally:
        lock.release()


def reset_for_tests() -> None:
    """清空所有 key 锁。仅测试使用,确保用例之间互不污染。

    单飞锁是状态对象,跨测试泄漏会让"两个 key 都拿锁"这种断言失败。
    """
    with _registry_guard:
        # 不在此处强制 release 锁 — 那会抛 RuntimeError,且语义不清晰。
        # 如果用例持有锁未释放,后续用例会撞 busy(单飞正确行为)。
        # 因此此函数只清字典,假定调用方已退出所有 with 块。
        _locks.clear()