"""SQLite 写锁瞬时争用时的指数退试重试。

背景：
- 进程内仍有 `scheduler_lock` 单飞锁来避免「同一时刻多个写入型 job」，
  但 uvicorn 同步工作线程（API 路由读写）+ scheduler 后台线程（LLM 准入/
  向量索引/基金匹配）仍可能在不同事务交错时撞上 SQLite `database is locked`。
- SQLite 的 `busy_timeout` 已经在 `db.session._install_sqlite_pragmas` 调到
  15s，但当某次写入链路本身在持锁做 5s 以上的 LLM+向量化时，15s 仍然不够。
- 本模块在应用层再套一层退避，做「最后一公里」：把偶发的 `OperationalError:
  database is locked` 转成 warning + 重试，而不是直接炸出 traceback。

**PostgreSQL 兼容性**：PostgreSQL 使用行级锁和 MVCC，不会有 `database is locked`
错误。本模块在检测到 `database_url` 以 `postgresql` 开头时会直接调用函数，不再重试。

用法：

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

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)


def _is_postgresql() -> bool:
    """检测当前 database_url 是否为 PostgreSQL。"""
    try:
        settings = get_settings()
        return settings.database_url.startswith("postgresql")
    except Exception:
        return False


_IS_PG = _is_postgresql()


def call_with_sqlite_retry(
    fn,
    *args,
    max_attempts: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    **kwargs,
):
    """对 `fn(*args, **kwargs)` 做 SQLite `database is locked` 指数退避重试。

    - **PostgreSQL**：no-op，直接调用 fn。
    - **SQLite**：检测 `database is locked` 并重试。

    Args:
        fn: 任意可调用对象；若其抛出 `OperationalError` 且消息含 "locked"，
            则按指数退避重试，最多 `max_attempts` 次。
        max_attempts: 最大尝试次数（包括首次）。
        base_delay: 首次重试前的 sleep 秒数（第 N 次退避 = base_delay * 2^(N-1)）。
        max_delay: 单次退避上限，避免长事务下把 sleep 拉到几十秒。
        *args/**kwargs: 透传给 fn。

    Returns:
        fn 的返回值（最后一次成功调用的结果）。

    Raises:
        OperationalError: 不是 `database is locked` 或者重试耗尽，原样上抛。
    """
    if _IS_PG:
        # PostgreSQL: 数据库不报 "database is locked"，直接调用
        return fn(*args, **kwargs)

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
    # 不可达，仅满足类型检查
    assert last_exc is not None
    raise last_exc
