"""建表入口:把 `backend.db.models` 中定义的所有表建出来。

可重复调用:`Base.metadata.create_all` 对已存在的表不会再发 DDL。
"""
from backend.db.session import Base, engine as default_engine
import backend.db.models  # noqa: F401  (必须 import,模型才会注册到 Base.metadata)


def init_db(engine=None) -> None:
    """用指定的 engine 建齐 `Base.metadata` 中的全部表。

    Args:
        engine: SQLAlchemy engine。为空时使用绑定到
            `Settings().database_url` 的进程级 engine。测试通常
            传一个内存 engine 来保证隔离。
    """
    Base.metadata.create_all(engine or default_engine)


if __name__ == "__main__":
    import os
    # SQLite 文件落在 backend/data/ 下;先把目录建出来,SQLAlchemy
    # 才能直接打开文件,省掉一次额外的手动 mkdir。
    os.makedirs("backend/data", exist_ok=True)
    init_db()
    print("Tables created.")