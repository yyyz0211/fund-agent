"""调度器单飞锁。

PostgreSQL 使用行级锁和 MVCC，天然支持并发写入。
本模块在 PostgreSQL 环境下是 no-op。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator


@contextmanager
def scheduler_lock(label: str, *, timeout_seconds: float | None = None) -> Iterator[None]:
    """调度器单飞锁。

    PostgreSQL 环境：no-op，直接 yield。
    """
    yield


def try_acquire(label: str):
    """手动 acquire/release 形式。

    PostgreSQL 环境：返回 no-op guard。
    """
    return _NoOpLockGuard(label)


class _NoOpLockGuard:
    """PostgreSQL 模式下的 no-op guard。"""

    def __init__(self, label: str) -> None:
        self._label = label

    def release(self) -> None:
        pass


class SchedulerLockBusy(RuntimeError):
    """scheduler_lock 被其他 job 占用（仅 SQLite 模式）。"""
