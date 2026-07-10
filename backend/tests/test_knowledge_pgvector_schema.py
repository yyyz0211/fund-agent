from __future__ import annotations

from sqlalchemy import create_engine, inspect
import pytest


class FakeConnection:
    def __init__(self, existing_type=None):
        self.existing_type = existing_type
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))

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
    from backend.db.init_db import ensure_pgvector_schema

    engine = FakePostgresEngine(existing_type="vector(768)")

    with pytest.raises(RuntimeError, match="dimension mismatch"):
        ensure_pgvector_schema(engine, dimensions=1024)
