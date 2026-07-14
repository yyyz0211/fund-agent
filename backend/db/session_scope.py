"""顶层事务上下文管理器。

用途：
- CLI/维护脚本的顶层入口
- Scheduler job 的事务边界
- 后台线程的事务边界

注意：
- service 接收外部 Session 时不得调用此函数
- service 只允许 flush()，不得 commit/rollback/close

用法示例(scheduler / CLI / 跨 service 原子操作):

    from backend.db.session_scope import session_scope

    def scheduled_job():
        with session_scope() as session:
            # 业务逻辑
            session.add(obj)
        # 自动 commit;异常时自动 rollback + raise

禁止用法:
- service 函数体内部禁止开 session_scope()(破坏调用方事务)
- service 函数体内部禁止 commit/rollback/close(只允许 flush)
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session

from backend.db import session as _session_module


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """顶层事务上下文管理器。

    自动处理 commit/rollback 和 session 关闭。

    用法：
    ```python
    from backend.db.session_scope import session_scope

    def top_level_operation():
        with session_scope() as session:
            # 业务逻辑
            session.add(obj)
            # 自动 commit 或 rollback
    ```
    """
    session = _session_module.SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
