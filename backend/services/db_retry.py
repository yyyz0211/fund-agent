"""SQLite 写锁瞬时争用时的指数退试重试。

背景:
- 进程内仍有 `scheduler_lock` 单飞锁来避免「同一时刻多个写入型 job」,
  但 uvicorn 同步工作线程(API 路由读写) + scheduler 后台线程(LLM 准入/
  向量索引/基金匹配) 仍可能在不同事务交错时撞上 SQLite `database is locked`。
- SQLite 的 `busy_timeout` 已经在 `db.session._install_sqlite_pragmas` 调到
  15s,但当某次写入链路本身在持锁做 5s 以上的 LLM+向量化时,15s 仍然不够。
- 本模块在应用层再套一层退避,做「最后一公里」:把偶发的 `OperationalError:
  database is locked` 转成 warning + 重试,而不是直接炸出 traceback。

注意:`with` 协议 + `gen.throw` 在 contextmanager 内部 yield 处重新抛异常
的语义与「接住后 sleep 再重试」冲突 — generator 的下一次 yield 会让
`__exit__` 走到「generator didn't stop after throw()」分支。所以这里把
重试逻辑放在**调用方显式传入的 callable** 上,而不是用 `with` 块封装
任意代码。这点与典型 retry-decorator 库(retries, tenacity)一致。

用法:

```python
from backend.services.db_retry import call_with_sqlite_retry

def _commit():
    session.commit()

call_with_sqlite_retry(_commit)
```
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.exc import OperationalError


logger = logging.getLogger(__name__)


def call_with_sqlite_retry(
    fn,
    *args,
    max_attempts: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    **kwargs,
):
    """对 `fn(*args, **kwargs)` 做 SQLite `database is locked` 指数退避重试。

    Args:
        fn: 任意可调用对象;若其抛出 `OperationalError` 且消息含 "locked",
            则按指数退避重试,最多 `max_attempts` 次。
        max_attempts: 最大尝试次数(包括首次)。
        base_delay: 首次重试前的 sleep 秒数(第 N 次退避 = base_delay * 2^(N-1))。
        max_delay: 单次退避上限,避免长事务下把 sleep 拉到几十秒。
        *args/**kwargs: 透传给 fn。

    Returns:
        fn 的返回值(最后一次成功调用的结果)。

    Raises:
        OperationalError: 不是 `database is locked` 或者重试耗尽,原样上抛。
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    last_exc: OperationalError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except OperationalError as exc:
            msg = str(exc).lower()
            if "locked" not in msg or attempt >= max_attempts:
                raise
            last_exc = exc
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            logger.warning(
                "[sqlite_retry] attempt=%d/%d sleeping=%.2fs err=%s",
                attempt,
                max_attempts,
                delay,
                exc,
            )
            time.sleep(delay)
    # 不可达,仅满足类型检查
    assert last_exc is not None
    raise last_exc
