"""顶层事务上下文管理器。

用途：
- CLI/维护脚本的顶层入口
- Scheduler job 的事务边界
- 后台线程的事务边界

注意：
- service 接收外部 Session 时不得调用此函数
- service 只允许 flush()，不得 commit/rollback/close
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session

from backend.db.session import SessionLocal


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
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
