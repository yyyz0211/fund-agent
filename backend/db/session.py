"""SQLAlchemy engine、Session 工厂和共享的 declarative base。

导入本模块会有副作用:会基于 `Settings().database_url` 构造一个默认
engine。除非有特别理由,大部分调用方应当走 `get_session()` 而不是
直接操作 engine。
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from backend.config.settings import get_settings


class Base(DeclarativeBase):
    """`backend.db.models` 中所有 ORM 模型的声明基类。"""


def make_engine(url: str | None = None):
    """构造一个 SQLAlchemy engine。

    Pool 策略按 URL 方言选择:

    - ``sqlite:///:memory:`` / ``sqlite://`` → ``StaticPool``，
      进程内单连接复用，专用于测试。
    - 其他 ``sqlite://...`` (文件库) → ``NullPool``，每个 Session 用完即关，
      不在进程内排队。SQLite 全局写锁是唯一的同步点，配合
      ``busy_timeout=15000`` 和 WAL 使用，把锁等待交给 SQLite 而非
      SQLAlchemy 队列。
    - 其他 (Postgres, MySQL…) → ``QueuePool``，显式 ``pool_size`` /
      ``max_overflow`` / ``pool_timeout``，加上 ``pool_pre_ping=True``
      检测断连。

    Args:
        url: 连接串。为空时回退到 `Settings().database_url`。
            测试通常传入 `"sqlite:///:memory:"` 以获得隔离的内存库。
    """
    settings = get_settings()
    url = url or settings.database_url

    if url.startswith("sqlite:") and (":memory:" in url or url == "sqlite://"):
        # :memory: 或 Unix socket → StaticPool（测试专用）
        connect_args = {"check_same_thread": False}
        eng = create_engine(
            url,
            connect_args=connect_args,
            poolclass=StaticPool,
            future=True,
        )
        _install_sqlite_pragmas(eng, busy_timeout_ms=15000)
    elif url.startswith("sqlite"):
        # 文件型 SQLite → NullPool + WAL + 长 busy_timeout
        connect_args = {"check_same_thread": False}
        eng = create_engine(
            url,
            connect_args=connect_args,
            poolclass=NullPool,
            future=True,
        )
        _install_sqlite_pragmas(eng, busy_timeout_ms=15000)
    else:
        # Postgres / MySQL 等 → QueuePool，参数由 Settings 驱动
        eng = create_engine(
            url,
            pool_size=int(settings.db_pool_size),
            max_overflow=int(settings.db_max_overflow),
            pool_timeout=float(settings.db_pool_timeout_seconds),
            pool_pre_ping=True,
            future=True,
        )

    return eng


def _install_sqlite_pragmas(eng, busy_timeout_ms: int = 15000) -> None:
    """给 SQLite 连接设置本地单用户场景下更友好的并发参数。

    Args:
        eng: SQLAlchemy engine 实例。
        busy_timeout_ms: SQLite busy_timeout 毫秒数。默认 15000 (15s)，
            比旧值 5s 更宽松，配合 NullPool 使用，把锁等待交给 SQLite
            而不是 SQLAlchemy 的 30s 超时兜底。
    """

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:
                # in-memory SQLite 不支持 WAL; 文件库失败也不应阻断测试建库。
                pass
        finally:
            cursor.close()


# 进程级单例，默认代码路径都直接用这两个。
# 重启时重新构造以反映配置变化（get_settings 由 lru_cache 记忆化，
# 故 engine 在进程启动时只读一次）。
engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Session:
    """开一个新的 Session。调用方负责关闭。"""
    return SessionLocal()
