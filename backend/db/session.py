"""SQLAlchemy engine、Session 工厂和共享的 declarative base。

导入本模块会有副作用:会基于 `Settings().database_url` 构造一个默认
engine。除非有特别理由,大部分调用方应当走 `get_session()` 而不是
直接操作 engine。
"""
from sqlalchemy import create_engine
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
    return create_engine(url, connect_args=connect_args, future=True)


# 进程级单例,默认代码路径都直接用这两个。
engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Session:
    """开一个新的 Session。调用方负责关闭。"""
    return SessionLocal()