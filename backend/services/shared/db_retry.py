"""数据库操作包装器。

PostgreSQL 使用行级锁和 MVCC，不会有 SQLite 的 `database is locked` 问题。
如需 PostgreSQL retry（如 deadlock、serialization failure），在此模块添加。
"""
from __future__ import annotations


def call_with_sqlite_retry(
    fn,
    *args,
    max_attempts: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    **kwargs,
):
    """PostgreSQL 环境直接调用 fn，不再做 SQLite 锁重试。

    保留此函数避免大规模修改调用方。SQLite 移除后，此函数仅透传调用。
    如需 PostgreSQL 重试策略，在此添加。
    """
    return fn(*args, **kwargs)
