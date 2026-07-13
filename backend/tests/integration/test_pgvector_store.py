from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.db.init_db import ensure_pgvector_schema, init_db, rebuild_pgvector_schema
from backend.db.models import KnowledgeDocument
from backend.services.knowledge_pgvector import PgVectorStore
from backend.services.knowledge_vector import VectorItem


DATABASE_URL = os.getenv("TEST_PGVECTOR_DATABASE_URL")
pytestmark = [
    pytest.mark.pgvector,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="TEST_PGVECTOR_DATABASE_URL is not configured",
    ),
]


def _document(source_id: str, topic: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        source_type="cls_telegraph",
        source_id=source_id,
        source_url=f"https://example.com/{source_id}",
        title=topic,
        summary=topic,
        content=topic,
        normalized_text=topic,
        primary_topic=topic,
        topic_title=topic,
        topics_json="[]",
        topic_names_json=f'["{topic}"]',
        fund_theme_tags_json="[]",
        fund_type_tags_json="[]",
        markets_json="[]",
        asset_classes_json="[]",
        impact_direction="neutral",
        published_at="2026-07-10 10:00:00",
        effective_until="2099-01-01 00:00:00",
        relevance_score=0.8,
        classification_status="accepted",
        index_status="indexed",
        content_hash=f"hash-{source_id}",
        canonical_content_hash=f"canonical-{source_id}",
    )


def test_pgvector_upsert_search_filter_and_cascade():
    engine = create_engine(DATABASE_URL)
    init_db(engine)
    ensure_pgvector_schema(engine, dimensions=3)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        ai = _document("ai", "人工智能")
        consumer = _document("consumer", "消费")
        session.add_all([ai, consumer])
        session.flush()
        store = PgVectorStore(session, model="integration", version="v1", dimensions=3)
        store.upsert([
            VectorItem(ai.id, ai.normalized_text, [1.0, 0.0, 0.0], {"content_hash": ai.content_hash}),
            VectorItem(
                consumer.id,
                consumer.normalized_text,
                [0.0, 1.0, 0.0],
                {"content_hash": consumer.content_hash},
            ),
        ])

        hits = store.search([1.0, 0.0, 0.0], {"topic": "人工智能"}, limit=5)
        assert [hit.document_id for hit in hits] == [ai.id]

        session.delete(ai)
        session.flush()
        remaining = session.scalar(text(
            "SELECT count(*) FROM knowledge_embeddings WHERE document_id = :document_id"
        ), {"document_id": ai.id})
        assert remaining == 0
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_pgvector_rebuild_requeues_documents_transactionally():
    engine = create_engine(DATABASE_URL)
    init_db(engine)
    ensure_pgvector_schema(engine, dimensions=3)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    class _TransactionalEngine:
        """Keep destructive DDL inside this test's rollback-only transaction."""

        dialect = connection.dialect

        @staticmethod
        def begin():
            return connection.begin_nested()

    try:
        document = _document("rebuild", "重建测试")
        document.embedding_model = "old-model"
        document.embedding_version = "old-version"
        document.index_attempts = 2
        document.last_index_error = "old failure"
        session.add(document)
        session.flush()

        requeued = rebuild_pgvector_schema(
            _TransactionalEngine(),
            dimensions=3,
            confirmed=True,
        )
        session.expire(document)

        assert requeued >= 1
        assert document.index_status == "pending"
        assert document.embedding_model is None
        assert document.embedding_version is None
        assert document.index_attempts == 0
        assert document.last_index_error is None
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
