"""FastAPI 依赖注入工具。

当前只导出 `get_db_session()`，与现有 `backend.db.session.get_session()`
保持一致：调用者拿 session 并自己负责关闭。本文件不引入新概念。
"""
from typing import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal


def get_db_session() -> Iterator[Session]:
    """为每个请求开一个 Session，请求结束关闭。

    设计选择：不在这里 commit/rollback —— 路由层只读，复用 service
    层的 `session=None` 默认行为。
    """
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


DBSession = Depends(get_db_session)
