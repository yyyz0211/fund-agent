from __future__ import annotations

from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.unit


class FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return FakeMappings(self._rows)


class RecordingSession:
    def __init__(self, *, dialect="postgresql", rows=None):
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
        self.rows = rows or []
        self.calls: list[tuple[str, dict]] = []

    def get_bind(self):
        return self.bind

    def execute(self, statement, params=None):
        self.calls.append((str(statement), dict(params or {})))
        return FakeResult(self.rows)


def _settings(**overrides):
    values = {
        "knowledge_rag_enabled": True,
        "knowledge_vector_backend": "auto",
        "knowledge_embedding_model": "embed-model",
        "knowledge_embedding_version": "v1",
        "knowledge_embedding_dimensions": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_vector_store_factory_degrades_for_non_postgresql_dialect():
    from backend.services.knowledge.knowledge_pgvector import build_vector_store

    assert build_vector_store(RecordingSession(dialect="mysql"), _settings()) is None


def test_vector_store_factory_builds_pgvector_for_postgres():
    from backend.services.knowledge.knowledge_pgvector import PgVectorStore, build_vector_store

    store = build_vector_store(RecordingSession(), _settings())

    assert isinstance(store, PgVectorStore)


def test_pgvector_store_uses_parameterized_upsert_search_and_delete():
    from backend.services.knowledge.knowledge_pgvector import PgVectorStore
    from backend.services.knowledge.knowledge_vector import VectorItem

    session = RecordingSession(rows=[{
        "document_id": 7,
        "score": 0.9,
        "source_type": "cls_telegraph",
        "source_id": "cls-7",
        "primary_topic": "人工智能",
        "topic_names_json": '["人工智能"]',
        "fund_theme_tags_json": "[]",
        "fund_type_tags_json": "[]",
        "published_at": "2026-07-10 10:00:00",
        "effective_until": "2099-01-01 00:00:00",
        "index_status": "indexed",
    }])
    store = PgVectorStore(session, model="embed-model", version="v1", dimensions=3)
    store.upsert([VectorItem(
        document_id=7,
        text="人工智能",
        vector=[0.1, 0.2, 0.3],
        metadata={"content_hash": "hash-7"},
    )])
    hits = store.search([0.1, 0.2, 0.3], {"source_type": "cls_telegraph"}, 5)
    store.delete([7])

    sql = "\n".join(call[0] for call in session.calls)
    assert "ON CONFLICT (document_id) DO UPDATE" in sql
    assert "<=> CAST(:query_vector AS vector)" in sql
    assert "document_id = ANY(:document_ids)" in sql
    assert "[0.1,0.2,0.3]" not in sql
    assert session.calls[0][1]["embedding"] == "[0.1,0.2,0.3]"
    assert [hit.document_id for hit in hits] == [7]
    assert hits[0].metadata["topics"] == ["人工智能"]


def test_pgvector_store_rejects_wrong_vector_dimension():
    from backend.exceptions import InputValidationError
    from backend.services.knowledge.knowledge_pgvector import PgVectorStore
    from backend.services.knowledge.knowledge_vector import VectorItem

    store = PgVectorStore(RecordingSession(), model="embed-model", version="v1", dimensions=3)

    with pytest.raises(InputValidationError, match="dimension"):
        store.upsert([VectorItem(
            document_id=1,
            text="bad",
            vector=[0.1, 0.2],
            metadata={"content_hash": "hash-1"},
        )])
