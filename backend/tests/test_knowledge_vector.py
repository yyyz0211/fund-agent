from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.init_db import init_db
from backend.db.models import KnowledgeDocument
from backend.services.knowledge_vector import (
    DeterministicEmbeddingProvider,
    InMemoryVectorStore,
    index_pending_documents,
)


def add_doc(session):
    doc = KnowledgeDocument(
        source_type="cls_telegraph",
        source_id="cls-1",
        source_url="u1",
        title="AI消息",
        summary="summary",
        content="content",
        normalized_text="标题：AI消息\n摘要：summary",
        primary_topic="人工智能",
        topic_title="人工智能",
        topics_json="[]",
        topic_names_json='["人工智能"]',
        fund_theme_tags_json='["科技成长"]',
        fund_type_tags_json='["混合型"]',
        markets_json='["A股"]',
        asset_classes_json='["基金"]',
        impact_direction="negative",
        published_at="2026-07-09 10:00:00",
        effective_until="2026-07-23 10:00:00",
        relevance_score=0.8,
        classification_status="accepted",
        index_status="pending",
        embedding_model=None,
        embedding_version=None,
        content_hash="hash-1",
        canonical_content_hash="canonical-1",
        raw_reason="accepted",
    )
    session.add(doc)
    session.commit()
    return doc.id


def test_index_pending_documents_marks_indexed():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    store = InMemoryVectorStore()

    with Session(eng) as s:
        doc_id = add_doc(s)
        result = index_pending_documents(
            session=s,
            embedding_provider=DeterministicEmbeddingProvider(),
            vector_store=store,
            limit=10,
        )

        assert result["indexed"] == 1
        assert s.get(KnowledgeDocument, doc_id).index_status == "indexed"
        assert store.items[doc_id].metadata["topics"] == ["人工智能"]


def test_indexed_documents_are_requeued_for_provider_metadata_mismatch():
    provider = DeterministicEmbeddingProvider()
    mismatches = [
        (None, provider.version),
        (provider.model, None),
        ("old-model", provider.version),
        (provider.model, "old-version"),
    ]

    for embedding_model, embedding_version in mismatches:
        eng = create_engine("sqlite:///:memory:")
        init_db(eng)
        store = InMemoryVectorStore()

        with Session(eng) as s:
            doc_id = add_doc(s)
            doc = s.get(KnowledgeDocument, doc_id)
            doc.index_status = "indexed"
            doc.embedding_model = embedding_model
            doc.embedding_version = embedding_version
            s.flush()

            result = index_pending_documents(
                session=s,
                embedding_provider=provider,
                vector_store=store,
                limit=10,
            )

            refreshed = s.get(KnowledgeDocument, doc_id)
            assert result == {"processed": 1, "indexed": 1, "failed": 0}
            assert refreshed.embedding_model == provider.model
            assert refreshed.embedding_version == provider.version
            assert doc_id in store.items


def test_indexed_document_with_matching_provider_metadata_is_not_requeued():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    provider = DeterministicEmbeddingProvider()
    store = InMemoryVectorStore()

    with Session(eng) as s:
        doc_id = add_doc(s)
        doc = s.get(KnowledgeDocument, doc_id)
        doc.index_status = "indexed"
        doc.embedding_model = provider.model
        doc.embedding_version = provider.version
        s.flush()

        result = index_pending_documents(
            session=s,
            embedding_provider=provider,
            vector_store=store,
            limit=10,
        )

        assert result == {"processed": 0, "indexed": 0, "failed": 0}
        assert doc_id not in store.items


def test_vector_search_respects_metadata_filter():
    store = InMemoryVectorStore()
    provider = DeterministicEmbeddingProvider()
    query = provider.embed(["人工智能"])[0]
    store.upsert([
        {
            "document_id": 1,
            "text": "人工智能",
            "vector": provider.embed(["人工智能"])[0],
            "metadata": {"topics": ["人工智能"]},
        },
        {
            "document_id": 2,
            "text": "消费",
            "vector": provider.embed(["消费"])[0],
            "metadata": {"topics": ["消费"]},
        },
    ])

    hits = store.search(query, {"topics": "人工智能"}, limit=5)

    assert [hit.document_id for hit in hits] == [1]


class FailingOnceVectorStore(InMemoryVectorStore):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def upsert(self, items):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary vector outage")
        return super().upsert(items)


def test_failed_index_is_retried_after_backoff():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    store = FailingOnceVectorStore()
    started = datetime(2026, 7, 10, 10, 0, 0)

    with Session(eng) as s:
        doc_id = add_doc(s)
        first = index_pending_documents(
            session=s,
            embedding_provider=DeterministicEmbeddingProvider(),
            vector_store=store,
            limit=10,
            now=started,
            retry_seconds=60,
        )
        failed = s.get(KnowledgeDocument, doc_id)
        assert first["failed"] == 1
        assert failed.index_status == "failed"
        assert failed.index_attempts == 1
        assert failed.next_index_retry_at == started + timedelta(seconds=60)

        second = index_pending_documents(
            session=s,
            embedding_provider=DeterministicEmbeddingProvider(),
            vector_store=store,
            limit=10,
            now=started + timedelta(seconds=61),
            retry_seconds=60,
        )
        indexed = s.get(KnowledgeDocument, doc_id)
        assert second["indexed"] == 1
        assert indexed.index_status == "indexed"
        assert indexed.last_index_error is None
        assert indexed.next_index_retry_at is None
