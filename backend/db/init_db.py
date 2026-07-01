"""建表入口:把 `backend.db.models` 中定义的所有表建出来。

`Base.metadata.create_all` 对已存在的表不会再发 DDL,这意味着给
老表加新字段(例如本次引入的 `Watchlist.cost_nav_basis`)时,已
存在的 DB 不会自动升级 —— 这是 SQLite + create_all 组合的已知
限制,不是 bug。本模块用一个**轻量级 schema migration** 补丁处理
这种情况:

1. 先 `create_all` 创建/确保新表存在(`fund_transactions`)。
2. 然后反射所有 ORM 模型声明的列,逐一比对实际表结构;
   缺的列用 `ALTER TABLE ... ADD COLUMN` 补齐(只在 SQLite 上跑,
   其他方言理论上有类似行为,但本项目目前只对 SQLite 做补列)。
3. 补列完成后再 `create_all` 一次保险。

反射 → ALTER 的过程是幂等的,可以重复运行。
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

import backend.db.models  # noqa: F401  (必须 import,模型才会注册到 Base.metadata)
from backend.db.session import Base, engine as default_engine


def init_db(engine: Engine | None = None) -> None:
    """用指定的 engine 建齐 `Base.metadata` 中的全部表,并对已存在的
    老表按 ORM 模型补齐缺失的列。

    Args:
        engine: SQLAlchemy engine。为空时使用绑定到
            `Settings().database_url` 的进程级 engine。测试通常
            传一个内存 engine 来保证隔离。
    """
    eng = engine or default_engine
    Base.metadata.create_all(eng)
    _apply_missing_columns(eng)
    # create_all 不冲突,再跑一次只是补 sanity(新表的索引等)。
    Base.metadata.create_all(eng)


def _apply_missing_columns(eng: Engine) -> None:
    """对每个 ORM 表反射真实 schema,与声明的列对比,缺啥补啥。

    只处理"加列",不改类型 / 不删列 / 不改约束 —— 那是 alembic 的事。
    新列若 server_default 是字面量(本次 `cost_nav_basis` 没设,
    留 None),SQLite ALTER 会允许 NULL,不需要额外 default。
    """
    insp = inspect(eng)
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                # create_all 刚建好,理论上不存在,但保险。
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                # SQLite ALTER TABLE ADD COLUMN 不支持 NOT NULL 但允许
                # NULL(默认)。本次缺的 `cost_nav_basis` 模型声明是
                # nullable=True,直接 ADD 即可。
                col_type = col.type.compile(eng.dialect)
                conn.execute(text(
                    f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}"
                ))


if __name__ == "__main__":
    import os
    # SQLite 文件落在 backend/data/ 下;先把目录建出来,SQLAlchemy
    # 才能直接打开文件,省掉一次额外的手动 mkdir。
    os.makedirs("backend/data", exist_ok=True)
    init_db()
    print("Tables created.")