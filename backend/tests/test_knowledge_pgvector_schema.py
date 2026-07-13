from __future__ import annotations

from sqlalchemy import create_engine, inspect
import pytest
from types import SimpleNamespace


class FakeConnection:
    def __init__(self, existing_type=None):
        self.existing_type = existing_type
        self.statements: list[str] = []

    def execute(self, statement, _params=None):
        self.statements.append(str(statement))
        return type("Result", (), {"rowcount": 3})()

    def scalar(self, statement):
        self.statements.append(str(statement))
        return self.existing_type


class FakeBegin:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return False


class FakePostgresEngine:
    dialect = type("Dialect", (), {"name": "postgresql"})()

    def __init__(self, existing_type=None):
        self.connection = FakeConnection(existing_type)

    def begin(self):
        return FakeBegin(self.connection)


def test_pgvector_schema_is_noop_for_sqlite():
    from backend.db.init_db import ensure_pgvector_schema

    engine = create_engine("sqlite:///:memory:")

    assert ensure_pgvector_schema(engine, dimensions=16) is False
    assert "knowledge_embeddings" not in inspect(engine).get_table_names()


def test_pgvector_schema_creates_extension_table_and_cosine_index():
    from backend.db.init_db import ensure_pgvector_schema

    engine = FakePostgresEngine()

    assert ensure_pgvector_schema(engine, dimensions=16) is True
    sql = "\n".join(engine.connection.statements)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "embedding vector(16)" in sql
    assert "vector_cosine_ops" in sql


def test_pgvector_schema_rejects_existing_dimension_mismatch():
    from backend.db.init_db import PgVectorDimensionMismatch, ensure_pgvector_schema

    engine = FakePostgresEngine(existing_type="vector(768)")

    with pytest.raises(PgVectorDimensionMismatch, match="dimension mismatch"):
        ensure_pgvector_schema(engine, dimensions=1024)


def test_init_db_tolerates_pgvector_dimension_mismatch(monkeypatch):
    import backend.db.init_db as init_module

    engine = FakePostgresEngine()
    monkeypatch.setattr(init_module.Base.metadata, "create_all", lambda _engine: None)
    monkeypatch.setattr(init_module, "_apply_missing_columns", lambda _engine: None)
    monkeypatch.setattr(init_module, "_migrate_briefings_unique_constraint", lambda _engine: None)
    monkeypatch.setattr(
        init_module,
        "_migrate_knowledge_classification_log_unique_constraint",
        lambda _engine: None,
    )
    monkeypatch.setattr(init_module, "_drop_obsolete_columns", lambda _engine: None)
    monkeypatch.setattr(
        init_module,
        "get_settings",
        lambda: SimpleNamespace(
            knowledge_vector_backend="pgvector",
            knowledge_embedding_dimensions=1024,
        ),
    )
    calls = []

    def mismatch(_engine, dimensions):
        calls.append(dimensions)
        raise init_module.PgVectorDimensionMismatch("dimension mismatch")

    monkeypatch.setattr(init_module, "ensure_pgvector_schema", mismatch)

    init_module.init_db(engine)

    assert calls == [1024]


def test_pgvector_rebuild_requires_explicit_confirmation():
    from backend.db.init_db import rebuild_pgvector_schema

    engine = FakePostgresEngine()

    with pytest.raises(ValueError, match="confirm=true"):
        rebuild_pgvector_schema(engine, dimensions=16, confirmed=False)
    assert engine.connection.statements == []


def test_pgvector_rebuild_rejects_sqlite_without_dropping_tables():
    from backend.db.init_db import rebuild_pgvector_schema

    engine = create_engine("sqlite:///:memory:")

    with pytest.raises(ValueError, match="only supported on PostgreSQL"):
        rebuild_pgvector_schema(engine, dimensions=16, confirmed=True)
    assert "knowledge_embeddings" not in inspect(engine).get_table_names()


def test_pgvector_rebuild_drops_only_vector_table_and_requeues_documents():
    from backend.db.init_db import rebuild_pgvector_schema

    engine = FakePostgresEngine()

    assert rebuild_pgvector_schema(engine, dimensions=16, confirmed=True) == 3

    sql = "\n".join(engine.connection.statements)
    assert "DROP TABLE IF EXISTS knowledge_embeddings" in sql
    assert "DROP TABLE IF EXISTS knowledge_documents" not in sql
    assert "embedding vector(16)" in sql
    assert "UPDATE knowledge_documents" in sql
    assert "index_status = 'pending'" in sql
    assert "embedding_model = NULL" in sql
    assert "embedding_version = NULL" in sql
    assert "index_attempts = 0" in sql
    assert "last_index_error = NULL" in sql
    assert "next_index_retry_at = NULL" in sql


def test_postgres_classification_log_constraint_migration_is_idempotent():
    from backend.db.init_db import (
        _migrate_knowledge_classification_log_unique_constraint,
    )

    engine = FakePostgresEngine()

    _migrate_knowledge_classification_log_unique_constraint(engine)
    _migrate_knowledge_classification_log_unique_constraint(engine)

    sql = "\n".join(engine.connection.statements)
    assert "DROP CONSTRAINT IF EXISTS uq_knowledge_classification_log_attempt" in sql
    assert "uq_knowledge_classification_log_content_attempt" in sql
    assert (
        "source_type, source_id, canonical_content_hash,\n"
        "                            prompt_version, attempt_no"
    ) in sql
    assert sql.count("IF NOT EXISTS") == 2
