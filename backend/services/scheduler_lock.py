"""进程级调度器单飞锁。

背景：
- APScheduler 每个 job 自身的 `max_instances=1, coalesce=True` 只能防止
  同一个 job 重复触发,但 **多个不同 job**（例如 `cls_telegraph_sync`
  和 `knowledge_ingest_index`）仍会同时进入执行队列。
- 在 SQLite 单文件场景下，多个会写库的 scheduler job 并发时容易撞到
  全局写锁；再加上 uvicorn 同步工作线程也在读写，连锁时容易触发
  `QueuePool limit of size ... reached` 进一步放大故障面。
- 本模块提供 **进程级 `threading.Lock`**，所有写入 SQLite 的
  scheduler job 都应通过 `with scheduler_lock(...)` 包住，保证
  同进程内任意时刻只有一个写入型 job 在跑。

用法：

```python
from backend.services.scheduler_lock import scheduler_lock

@scheduler_job(trigger="interval", minutes=6)
def run_knowledge_pipeline():
    with scheduler_lock("knowledge_ingest_index"):
        knowledge_search_service.run_knowledge_pipeline_once()
```
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


# 进程内唯一锁。所有调度器写入型 job 共享。
_LOCK = threading.Lock()

# 标识当前持有者（label/job_id），用于诊断和 fast-fail。
_OWNER: dict[str, object] = {"label": None, "since": None}


@contextmanager
def scheduler_lock(label: str, *, timeout_seconds: float | None = None):
    """获取 scheduler 进程级单飞锁。

    Args:
        label: 持有者标识（例如 `cls_telegraph_sync`、`knowledge_ingest_index`）。
            出现在日志中便于排障。
        timeout_seconds: 最长等待秒数。默认 `None` 保持旧行为——非阻塞立即
            抢锁，失败立即抛 `SchedulerLockBusy`。传入正数后改为阻塞模式，
            最多等 `timeout_seconds` 秒；超时抛 `SchedulerLockBusy`。负数
            视为 `None`（立即失败）。

    Raises:
        SchedulerLockBusy: 锁被占且超过 `timeout_seconds`（或默认立即失败）。
            调用方应放弃本次触发，由 APScheduler 在下一轮 interval 自然重试。
    """
    blocking = timeout_seconds is not None and timeout_seconds > 0
    deadline = (time.monotonic() + float(timeout_seconds)) if blocking else None

    if blocking:
        # 循环 + 短 sleep：避免 _LOCK.acquire 超长阻塞（它本身能接受 timeout），
        # 同时方便定期检查 deadline。
        while True:
            if _LOCK.acquire(timeout=min(0.05, float(timeout_seconds))):
                break
            if deadline is not None and time.monotonic() >= deadline:
                owner = _OWNER.get("label")
                since = _OWNER.get("since")
                wait_for = (time.monotonic() - since) if since else 0.0
                raise SchedulerLockBusy(
                    f"scheduler_lock held by {owner!r} for {wait_for:.2f}s; "
                    f"requester={label!r} timed out after {timeout_seconds:.2f}s"
                )
    else:
        if not _LOCK.acquire(blocking=False):
            owner = _OWNER.get("label")
            since = _OWNER.get("since")
            wait_for = (time.monotonic() - since) if since else 0.0
            raise SchedulerLockBusy(
                f"scheduler_lock held by {owner!r} for {wait_for:.2f}s; "
                f"requester={label!r} rejected"
            )

    _OWNER["label"] = label
    _OWNER["since"] = time.monotonic()
    try:
        yield
    finally:
        _OWNER["label"] = None
        _OWNER["since"] = None
        _LOCK.release()


def try_acquire(label: str) -> Optional[_LockGuard]:
    """手动 acquire/release 形式。

    用 `with` 时释放；不需要用则调 `release()`。

    ```python
    guard = try_acquire("knowledge_reindex")
    if guard is None:
        return {"status": "busy"}
    try:
        ...
    finally:
        guard.release()
    ```
    """
    if not _LOCK.acquire(blocking=False):
        return None
    _OWNER["label"] = label
    _OWNER["since"] = time.monotonic()
    return _LockGuard(label)


class _LockGuard:
    def __init__(self, label: str) -> None:
        self._label = label
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if _OWNER["label"] == self._label:
            _OWNER["label"] = None
            _OWNER["since"] = None
        _LOCK.release()


class SchedulerLockBusy(RuntimeError):
    """scheduler_lock 被其他 job 占用。

    调用方应直接放弃本次触发（或返回 `{"status": "busy"}`），让
    APScheduler 在下一次 interval tick 自然重试。
    """