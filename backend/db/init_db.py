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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import backend.db.models  # noqa: F401  (必须 import,模型才会注册到 Base.metadata)
from backend.config.settings import get_settings
from backend.db.repository import backfill_watchlist_fund_names
from backend.db.session import Base, engine as default_engine, get_session


_PGVECTOR_REQUIRED_COLUMNS = frozenset({
    "document_id",
    "embedding",
    "embedding_model",
    "embedding_version",
    "content_hash",
    "created_at",
    "updated_at",
})


class PgVectorSchemaError(RuntimeError):
    """Vector-only schema/setup failure that must not prevent API startup."""

    def __init__(
        self,
        message: str,
        *,
        missing_columns: set[str] | None = None,
        table_missing: bool = False,
        database_dimension: int | None = None,
    ) -> None:
        super().__init__(message)
        self.missing_columns = missing_columns or set()
        self.table_missing = table_missing
        self.database_dimension = database_dimension


class PgVectorDimensionMismatch(PgVectorSchemaError):
    """Configured embedding dimensions differ from the existing vector column."""


class PgVectorUnavailableError(PgVectorSchemaError):
    """PostgreSQL could not initialize the pgvector extension/table/index."""


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
    _migrate_briefings_unique_constraint(eng)
    _migrate_knowledge_classification_log_unique_constraint(eng)
    _drop_obsolete_columns(eng)
    # create_all 不冲突,再跑一次只是补 sanity(新表的索引等)。
    Base.metadata.create_all(eng)
    settings = get_settings()
    if settings.knowledge_vector_backend != "structured":
        try:
            ensure_pgvector_schema(eng, settings.knowledge_embedding_dimensions)
        except PgVectorSchemaError as exc:
            # Vector storage is a rebuildable optional component. Keep the primary
            # ORM schema available and let health expose the precise local failure.
            import logging

            logging.getLogger(__name__).warning(
                "Knowledge vector schema unavailable during startup: %s", exc,
            )
    # Wave 2: Watchlist 加了 fund_name 列后, 老行是 NULL。
    # 启动时自动从 funds.fund_name 回填, 避免 briefing 一直显示空字符串。
    try:
        s = Session(eng)
        try:
            backfilled = backfill_watchlist_fund_names(s)
            if backfilled:
                import logging
                logging.getLogger(__name__).info(
                    "Backfilled watchlist.fund_name for %d rows.", backfilled
                )
        finally:
            s.close()
    except Exception:
        # 回填失败不能阻挡 DB 启动, 运行时仍以 _watchlist_to_dict 返回 None 让上游降级。
        pass


def ensure_pgvector_schema(eng: Engine, dimensions: int | None) -> bool:
    """在 PostgreSQL 上创建持久向量表；SQLite 和未配置维度时明确跳过。"""
    if eng.dialect.name != "postgresql" or dimensions is None:
        return False
    dimension = int(dimensions)
    if dimension <= 0:
        raise ValueError("knowledge embedding dimensions must be positive")

    try:
        with eng.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            _create_pgvector_table(conn, dimension)
            validate_pgvector_schema(conn, dimension)
    except PgVectorSchemaError:
        raise
    except SQLAlchemyError as exc:
        raise PgVectorUnavailableError(
            f"pgvector schema setup failed: {type(exc).__name__}: {exc}"
        ) from exc
    return True


def get_pgvector_dimension(conn) -> int | None:
    """Read the local PostgreSQL vector column dimension; return None if absent."""
    return _parse_pgvector_dimension(_get_pgvector_columns(conn).get("embedding"))


def _get_pgvector_columns(conn) -> dict[str, str]:
    """Read local vector table columns/types from PostgreSQL catalogs."""
    rows = conn.execute(text("""
        SELECT a.attname, format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute AS a
        JOIN pg_class AS c ON c.oid = a.attrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = 'knowledge_embeddings'
          AND a.attnum > 0
          AND NOT a.attisdropped
    """)).all()
    return {str(row[0]): str(row[1]) for row in rows}


def _parse_pgvector_dimension(existing_type: str | None) -> int | None:
    if existing_type is None:
        return None
    value = str(existing_type)
    if not value.startswith("vector(") or not value.endswith(")"):
        raise RuntimeError(f"unexpected knowledge embedding type: {value}")
    try:
        return int(value[len("vector("):-1])
    except ValueError as exc:
        raise RuntimeError(f"unexpected knowledge embedding type: {value}") from exc


def validate_pgvector_schema(conn, configured_dimension: int) -> dict[str, object]:
    """Strictly validate required columns and vector dimension from local catalogs."""
    columns = _get_pgvector_columns(conn)
    missing = set(_PGVECTOR_REQUIRED_COLUMNS).difference(columns)
    if missing:
        raise PgVectorSchemaError(
            "knowledge_embeddings schema is incomplete; missing columns: "
            + ", ".join(sorted(missing)),
            missing_columns=missing,
            table_missing=not columns,
        )
    try:
        database_dimension = _parse_pgvector_dimension(columns.get("embedding"))
    except RuntimeError as exc:
        raise PgVectorSchemaError(str(exc)) from exc
    if database_dimension != int(configured_dimension):
        raise PgVectorDimensionMismatch(
            "knowledge embedding dimension mismatch: "
            f"database=vector({database_dimension}), "
            f"configured=vector({int(configured_dimension)}); "
            "rebuild knowledge_embeddings before restarting",
            database_dimension=database_dimension,
        )
    return {"columns": sorted(columns), "dimensions": database_dimension}


def _create_pgvector_table(conn, dimension: int) -> None:
    """Create the disposable vector index table on an existing transaction."""
    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS knowledge_embeddings (
            document_id BIGINT PRIMARY KEY
                REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            embedding vector({dimension}) NOT NULL,
            embedding_model VARCHAR NOT NULL,
            embedding_version VARCHAR NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_knowledge_embeddings_cosine
        ON knowledge_embeddings USING hnsw (embedding vector_cosine_ops)
    """))


def rebuild_pgvector_schema(
    eng: Engine,
    dimensions: int | None,
    *,
    confirmed: bool,
) -> int:
    """Explicitly rebuild only ``knowledge_embeddings`` and requeue documents.

    This deliberately cannot be reached through ordinary reindexing. All DDL and
    document state changes share one PostgreSQL transaction so a failed rebuild
    does not leave the knowledge index half-reset.
    """
    if not confirmed:
        raise ValueError("vector schema rebuild requires confirm=true")
    if eng.dialect.name != "postgresql":
        raise ValueError("vector schema rebuild is only supported on PostgreSQL")
    if dimensions is None or int(dimensions) <= 0:
        raise ValueError("knowledge embedding dimensions must be positive")

    dimension = int(dimensions)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("DROP TABLE IF EXISTS knowledge_embeddings"))
        _create_pgvector_table(conn, dimension)
        result = conn.execute(text("""
            UPDATE knowledge_documents
            SET index_status = 'pending',
                embedding_model = NULL,
                embedding_version = NULL,
                index_attempts = 0,
                last_index_error = NULL,
                next_index_retry_at = NULL
        """))
    return int(result.rowcount or 0)


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


def _drop_obsolete_columns(eng: Engine) -> None:
    """清理已经从 ORM 模型移除的 SQLite 旧列。

    当前只处理 `watchlist.peer_category`。同类分类的权威缓存保留在
    `fund_profiles.peer_category`,自选池表不再冗余存一份。
    """
    insp = inspect(eng)
    if eng.dialect.name != "sqlite" or not insp.has_table("watchlist"):
        return
    existing = {c["name"] for c in insp.get_columns("watchlist")}
    if "peer_category" not in existing:
        return
    with eng.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE watchlist DROP COLUMN peer_category"))
        except Exception:
            # 旧 SQLite 版本不支持 DROP COLUMN 时,至少运行时代码已经
            # 不再读写该列;不让启动因为历史冗余列失败。
            pass


def _migrate_briefings_unique_constraint(eng: Engine) -> None:
    """把旧版 `UNIQUE(briefing_date)` 迁移为 `(briefing_date, brief_type)`。

    SQLite 不能直接删除唯一约束；旧本地库需要重建 briefings 表。
    新表或已迁移表只做 brief_type 空值回填。
    """
    insp = inspect(eng)
    if eng.dialect.name != "sqlite" or not insp.has_table("briefings"):
        return

    def _unique_index_columns(conn) -> list[list[str]]:
        indexes = conn.exec_driver_sql("PRAGMA index_list(briefings)").all()
        unique_columns: list[list[str]] = []
        for idx in indexes:
            # PRAGMA index_list: seq, name, unique, origin, partial
            if not bool(idx[2]):
                continue
            index_name = idx[1]
            cols = [
                col[2]
                for col in conn.exec_driver_sql(f"PRAGMA index_info({index_name})").all()
            ]
            unique_columns.append(cols)
        return unique_columns

    with eng.begin() as conn:
        existing_cols = {c["name"] for c in insp.get_columns("briefings")}
        if "brief_type" not in existing_cols:
            return

        conn.execute(text(
            "UPDATE briefings SET brief_type = 'post_market' "
            "WHERE brief_type IS NULL OR brief_type = ''"
        ))

        unique_columns = _unique_index_columns(conn)
        has_old_unique = ["briefing_date"] in unique_columns
        if not has_old_unique:
            return

        conn.execute(text("ALTER TABLE briefings RENAME TO briefings_old"))
        conn.execute(text("""
            CREATE TABLE briefings (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                briefing_date VARCHAR NOT NULL,
                brief_type VARCHAR(32),
                title VARCHAR NOT NULL,
                markdown VARCHAR NOT NULL,
                sections_json VARCHAR NOT NULL,
                source VARCHAR,
                as_of VARCHAR,
                data_quality VARCHAR,
                confidence VARCHAR,
                missing_data_json VARCHAR,
                evidence_count INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_briefing_date_type UNIQUE (briefing_date, brief_type)
            )
        """))
        conn.execute(text("""
            INSERT INTO briefings (
                id, briefing_date, brief_type, title, markdown, sections_json,
                source, as_of, data_quality, confidence, missing_data_json,
                evidence_count, created_at, updated_at
            )
            SELECT
                id,
                briefing_date,
                COALESCE(NULLIF(brief_type, ''), 'post_market'),
                title,
                markdown,
                sections_json,
                source,
                as_of,
                data_quality,
                confidence,
                missing_data_json,
                evidence_count,
                created_at,
                updated_at
            FROM briefings_old
        """))
        conn.execute(text("DROP TABLE briefings_old"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_briefings_briefing_date "
            "ON briefings (briefing_date)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_briefings_brief_type "
            "ON briefings (brief_type)"
        ))


def _migrate_knowledge_classification_log_unique_constraint(eng: Engine) -> None:
    """按内容版本隔离 classification attempt 编号。

    SQLite 无法删除表级 UNIQUE 约束，因此仅重建 classification log 表；
    PostgreSQL 可以原地替换命名约束。两条路径均可安全重复执行。
    """
    table_name = "knowledge_classification_log"
    old_constraint = "uq_knowledge_classification_log_attempt"
    new_constraint = "uq_knowledge_classification_log_content_attempt"

    if eng.dialect.name == "postgresql":
        with eng.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE {table_name} "
                f"DROP CONSTRAINT IF EXISTS {old_constraint}"
            ))
            conn.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = '{new_constraint}'
                          AND conrelid = '{table_name}'::regclass
                    ) THEN
                        ALTER TABLE {table_name}
                        ADD CONSTRAINT {new_constraint} UNIQUE (
                            source_type, source_id, canonical_content_hash,
                            prompt_version, attempt_no
                        );
                    END IF;
                END $$
            """))
        return

    insp = inspect(eng)
    if eng.dialect.name != "sqlite" or not insp.has_table(table_name):
        return

    with eng.begin() as conn:
        unique_columns: list[list[str]] = []
        for idx in conn.exec_driver_sql(
            f"PRAGMA index_list({table_name})"
        ).all():
            if not bool(idx[2]):
                continue
            unique_columns.append([
                col[2]
                for col in conn.exec_driver_sql(
                    f"PRAGMA index_info({idx[1]})"
                ).all()
            ])

        expected = [
            "source_type",
            "source_id",
            "canonical_content_hash",
            "prompt_version",
            "attempt_no",
        ]
        if expected in unique_columns:
            return

        conn.execute(text(
            "ALTER TABLE knowledge_classification_log "
            "RENAME TO knowledge_classification_log_old"
        ))
        conn.execute(text(f"""
            CREATE TABLE knowledge_classification_log (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                source_type VARCHAR(32) NOT NULL,
                source_id VARCHAR(128) NOT NULL,
                canonical_content_hash VARCHAR(64),
                attempt_no INTEGER NOT NULL,
                prompt_version VARCHAR(32) NOT NULL,
                status VARCHAR(16) NOT NULL,
                should_index BOOLEAN,
                relevance_score FLOAT,
                reason VARCHAR,
                raw_response_json VARCHAR,
                error_message VARCHAR,
                latency_ms INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CONSTRAINT {new_constraint} UNIQUE (
                    source_type, source_id, canonical_content_hash,
                    prompt_version, attempt_no
                )
            )
        """))
        conn.execute(text("""
            INSERT INTO knowledge_classification_log (
                id, source_type, source_id, canonical_content_hash, attempt_no,
                prompt_version, status, should_index, relevance_score, reason,
                raw_response_json, error_message, latency_ms, created_at
            )
            SELECT
                id, source_type, source_id, canonical_content_hash, attempt_no,
                prompt_version, status, should_index, relevance_score, reason,
                raw_response_json, error_message, latency_ms, created_at
            FROM knowledge_classification_log_old
        """))
        conn.execute(text("DROP TABLE knowledge_classification_log_old"))
        for column in (
            "source_type",
            "source_id",
            "canonical_content_hash",
            "status",
        ):
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS "
                f"ix_knowledge_classification_log_{column} "
                f"ON knowledge_classification_log ({column})"
            ))


if __name__ == "__main__":
    import os
    # SQLite 文件落在 backend/data/ 下;先把目录建出来,SQLAlchemy
    # 才能直接打开文件,省掉一次额外的手动 mkdir。
    os.makedirs("backend/data", exist_ok=True)
    init_db()
    print("Tables created.")
