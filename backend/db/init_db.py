"""数据库初始化入口。

PostgreSQL 单一化后，schema 直接由 SQLAlchemy 模型（`Base.metadata`）建立。
本模块负责：
1. 用 `create_all` 建表（数据可丢弃，无需迁移历史）
2. 管理 pgvector schema（PostgreSQL 特有，非模型定义）
3. 非破坏性健康校验与 watchlist 回填
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

import backend.db.models  # noqa: F401
from backend.config.settings import get_settings
from backend.db.repositories.watchlist import backfill_watchlist_fund_names
from backend.db.session import Base
from backend.db.session import engine as default_engine
from backend.db.session import get_session

logger = logging.getLogger(__name__)


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
        missing_columns: Optional[set[str]] = None,
        table_missing: bool = False,
        database_dimension: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.missing_columns = missing_columns or set()
        self.table_missing = table_missing
        self.database_dimension = database_dimension


class PgVectorDimensionMismatch(PgVectorSchemaError):
    """Configured embedding dimensions differ from the existing vector column."""


class PgVectorUnavailableError(PgVectorSchemaError):
    """PostgreSQL could not initialize the pgvector extension/table."""


def init_db(engine: Optional[Engine] = None) -> None:
    """初始化数据库。

    用 SQLAlchemy 模型建表并管理 pgvector schema。数据可丢弃，
    改模型即 drop & recreate，不保留迁移历史。

    Args:
        engine: SQLAlchemy engine。默认为进程级 engine。
    """
    eng = engine or default_engine

    # 验证方言
    if eng.dialect.name != "postgresql":
        raise ValueError(f"Only PostgreSQL is supported, got: {eng.dialect.name}")

    # 建表（幂等：已存在的表跳过）。pgvector 的 knowledge_embeddings 非模型定义，
    # 由下面的 ensure_pgvector_schema 单独建，依赖此处先建好 knowledge_documents。
    Base.metadata.create_all(eng)

    # pgvector schema 管理
    settings = get_settings()
    if settings.knowledge_vector_backend != "structured":
        try:
            ensure_pgvector_schema(eng, settings.knowledge_embedding_dimensions)
        except PgVectorSchemaError as exc:
            logger.warning(
                "Knowledge vector schema unavailable during startup: %s", exc,
            )

    # 回填 watchlist.fund_name（仅在需要时）
    try:
        session = get_session()
        try:
            backfilled = backfill_watchlist_fund_names(session)
            if backfilled:
                logger.info("Backfilled watchlist.fund_name for %d rows.", backfilled)
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001  # 降级边界：启动期允许回填失败
        logger.warning(
            "watchlist.fund_name backfill skipped due to error: %s",
            exc,
            exc_info=False,
        )


def ensure_pgvector_schema(eng: Engine, dimensions: Optional[int]) -> bool:
    """在 PostgreSQL 上创建持久向量表。"""
    if dimensions is None:
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


def get_pgvector_dimension(conn) -> Optional[int]:
    """Read the local PostgreSQL vector column dimension."""
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


def _parse_pgvector_dimension(existing_type: Optional[str]) -> Optional[int]:
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
    """Validate required columns and vector dimension from local catalogs."""
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
    """Create the vector index table."""
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
    dimensions: Optional[int],
    *,
    confirmed: bool,
) -> int:
    """Rebuild knowledge_embeddings and requeue documents.

    All DDL and document state changes share one transaction.
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


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
