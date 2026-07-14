"""SQLAlchemy engine、Session 工厂和共享的 declarative base。

仅支持 PostgreSQL。DATABASE_URL 必须以 postgresql 开头。

`set_session_factory` / `reset_session_factory` 提供一个轻量测试接缝:
测试可以临时把 `get_session()` 重定向到自定义工厂(connection-bound、
fixture-bound 等),使用完再 `reset_session_factory(token)` 还原。后台线程
应主动 `set_session_factory` 一次,避免隐式继承请求上下文里的工厂。
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config.settings import get_settings


class Base(DeclarativeBase):
    """`backend.db.models` 中所有 ORM 模型的声明基类。"""


def make_engine(url: str | None = None):
    """构造一个 PostgreSQL SQLAlchemy engine。

    使用 QueuePool，按 Settings 配置连接池参数。

    Args:
        url: 连接串。为空时使用 `Settings().database_url`。
    """
    settings = get_settings()
    url = url or settings.database_url

    if not url.startswith("postgresql"):
        raise ValueError(f"Only PostgreSQL is supported, got: {url}")

    return create_engine(
        url,
        pool_size=int(settings.db_pool_size),
        max_overflow=int(settings.db_max_overflow),
        pool_timeout=float(settings.db_pool_timeout_seconds),
        pool_pre_ping=True,
        future=True,
    )


# 进程级单例。重启时重新构造以反映配置变化。
engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


# `get_session()` 当前工厂覆盖。`None` 表示使用进程级 `SessionLocal`。
# 每个 ContextVar 写入仅在当前 asyncio/context 上下文可见;后台线程通过
# `contextvars.copy_context()` 或显式 `set_session_factory(...)` 隔离。
_session_factory_override: ContextVar[Callable[[], Session] | None] = ContextVar(
    "_session_factory_override", default=None,
)


def set_session_factory(factory: Callable[[], Session]) -> Token:
    """在当前上下文中把 `get_session()` 重定向到 `factory`。

    Args:
        factory: 返回新 `Session` 实例的可调用对象。
            例如 `lambda: Session(bind=connection, ...)`。

    Returns:
        `ContextVar.reset()` 所需的 token,调用方必须在退出作用域前
        传给 `reset_session_factory(token)` 还原。
    """
    return _session_factory_override.set(factory)


def reset_session_factory(token: Token) -> None:
    """还原 `get_session()` 到默认 `SessionLocal`。"""
    _session_factory_override.reset(token)


def get_session() -> Session:
    """返回一个新 Session。调用方负责关闭。

    当前上下文有覆盖工厂则使用之,否则使用进程级 `SessionLocal`。
    """
    factory = _session_factory_override.get()
    if factory is not None:
        return factory()
    return SessionLocal()
