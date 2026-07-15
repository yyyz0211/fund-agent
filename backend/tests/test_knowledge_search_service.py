from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.db.models import KnowledgeDocument
from backend.services.knowledge import knowledge_search_service as service
from backend.services.knowledge.knowledge_vector import (
    DeterministicEmbeddingProvider,
    InMemoryVectorStore,
    VectorItem,
)


def test_pipeline_uses_independent_classification_and_index_limits(monkeypatch):
    calls: dict[str, int] = {}
    settings = SimpleNamespace(
        knowledge_classification_batch_size=10,
        knowledge_index_batch_size=20,
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        service.knowledge_ingestion_service,
        "ingest_recent_knowledge",
        lambda **kwargs: calls.setdefault("classification_limit", kwargs["limit"]) or {},
    )
    monkeypatch.setattr(
        service.knowledge_vector,
        "index_pending_documents",
        lambda **kwargs: calls.setdefault("index_limit", kwargs["limit"]) or {},
    )
    monkeypatch.setattr(
        service.knowledge_fund_profile_service,
        "refresh_fund_watchlist_profiles",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        service.knowledge_match_service,
        "refresh_knowledge_fund_matches",
        lambda **_kwargs: {},
    )

    service.run_knowledge_pipeline_once(
        session=object(),
        embedding_provider=object(),
        vector_store=object(),
    )

    assert calls == {"classification_limit": 10, "index_limit": 20}


def _add_search_doc(
    session,
    *,
    source_id: str,
    effective_until: str,
    index_status: str = "indexed",
    text: str = "人工智能行业消息",
):
    doc = KnowledgeDocument(
        source_type="cls_telegraph",
        source_id=source_id,
        source_url=f"https://example.com/{source_id}",
        title=f"AI消息 {source_id}",
        summary=text,
        content=text,
        normalized_text=text,
        primary_topic="人工智能",
        topic_title="人工智能",
        topics_json="[]",
        topic_names_json='["人工智能"]',
        fund_theme_tags_json="[]",
        fund_type_tags_json="[]",
        markets_json="[]",
        asset_classes_json="[]",
        impact_direction="neutral",
        published_at="2026-07-10 10:00:00",
        effective_until=effective_until,
        relevance_score=0.8,
        classification_status="accepted",
        index_status=index_status,
        content_hash=f"hash-{source_id}",
        canonical_content_hash=f"canonical-{source_id}",
    )
    session.add(doc)
    return doc


@pytest.mark.db
def test_structured_search_excludes_expired_documents(db_session):
    _add_search_doc(
        db_session, source_id="active", effective_until="2099-01-01 00:00:00",
    )
    _add_search_doc(
        db_session, source_id="expired", effective_until="2020-01-01 00:00:00",
    )
    db_session.flush()

    result = service.search_knowledge("人工智能", session=db_session)

    assert [item["title"] for item in result["items"]] == ["AI消息 active"]


def test_merge_hybrid_candidates_dedupes_then_applies_limit():
    structured = [
        {"document_id": 1, "final_score": 0.30},
        {"document_id": 2, "final_score": 0.40},
    ]
    vector = [
        {"document_id": 2, "final_score": 0.80},
        {"document_id": 3, "final_score": 0.90},
    ]

    result = service.merge_hybrid_candidates(structured, vector, limit=2)

    assert [item["document_id"] for item in result] == [3, 2]


@pytest.mark.db
def test_search_uses_injected_vector_runtime_for_hybrid_retrieval(db_session):
    provider = DeterministicEmbeddingProvider()
    store = InMemoryVectorStore()
    doc = _add_search_doc(
        db_session,
        source_id="semantic-only",
        effective_until="2099-01-01 00:00:00",
        text="芯片产业链扩产",
    )
    db_session.flush()
    store.upsert([VectorItem(
        document_id=doc.id,
        text=doc.normalized_text,
        vector=provider.embed([doc.normalized_text])[0],
        metadata={"source_type": doc.source_type},
    )])

    result = service.search_knowledge(
        "没有词面命中的查询",
        session=db_session,
        embedding_provider=provider,
        vector_store=store,
    )

    assert result["retrieval_mode"] == "hybrid"
    assert [item["document_id"] for item in result["items"]] == [doc.id]


@pytest.mark.db
def test_structured_fallback_keeps_accepted_pending_document_visible(db_session):
    doc = _add_search_doc(
        db_session,
        source_id="pending",
        effective_until="2099-01-01 00:00:00",
        index_status="pending",
    )
    db_session.flush()

    result = service.search_knowledge("人工智能", session=db_session)

    assert result["retrieval_mode"] == "structured_fallback"
    assert [item["document_id"] for item in result["items"]] == [doc.id]
