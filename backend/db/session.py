"""SQLAlchemy engine、Session 工厂和共享的 declarative base。

导入本模块会有副作用:会基于 `Settings().database_url` 构造一个默认
engine。除非有特别理由,大部分调用方应当走 `get_session()` 而不是
直接操作 engine。
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config.settings import get_settings


class Base(DeclarativeBase):
    """`backend.db.models` 中所有 ORM 模型的声明基类。"""


def make_engine(url: str | None = None):
    """构造一个 SQLAlchemy engine。

    Args:
        url: 连接串。为空时回退到 `Settings().database_url`。
            测试通常传入 `"sqlite:///:memory:"` 以获得隔离的内存库。

    SQLite 必须加 `check_same_thread=False`:SQLAlchemy 默认连接池
    可能把连接给到任意工作线程,不加这个参数会报错;其他方言保持
    默认连接参数即可。
    """
    url = url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    eng = create_engine(url, connect_args=connect_args, future=True)
    if url.startswith("sqlite"):
        _install_sqlite_pragmas(eng)
    return eng


def _install_sqlite_pragmas(eng) -> None:
    """给 SQLite 连接设置本地单用户场景下更友好的并发参数。"""

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:
                # in-memory SQLite 不支持 WAL;文件库失败也不应阻断测试建库。
                pass
        finally:
            cursor.close()


# 进程级单例,默认代码路径都直接用这两个。
engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Session:
    """开一个新的 Session。调用方负责关闭。"""
    return SessionLocal()
