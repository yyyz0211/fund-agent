"""SQLAlchemy engine、Session 工厂和共享的 declarative base。

仅支持 PostgreSQL。DATABASE_URL 必须以 postgresql 开头。
"""
from __future__ import annotations

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


def get_session() -> Session:
    """开一个新的 Session。调用方负责关闭。"""
    return SessionLocal()
