"""Alembic 迁移后的 PostgreSQL knowledge schema 与 ORM 回归测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import inspect, select

from backend.db.models import (
    KnowledgeClassificationLog,
    KnowledgeClassificationState,
    KnowledgeDocument,
    KnowledgeSourceLink,
)


pytestmark = pytest.mark.db


def test_create_all_creates_knowledge_tables(postgres_engine):
    tables = set(inspect(postgres_engine).get_table_names())
    assert {
        "knowledge_documents",
        "knowledge_source_links",
        "knowledge_classification_state",
        "knowledge_classification_log",
        "knowledge_chunks",
        "fund_watchlist_profiles",
        "knowledge_fund_matches",
        "knowledge_retrieval_logs",
    }.issubset(tables)


def test_canonical_content_hash_supports_multiple_source_links(db_session):
    doc = KnowledgeDocument(
        source_type="cls_telegraph",
        source_id="cls-1",
        source_url="https://www.cls.cn/detail/1",
        title="AI news",
        summary="summary",
        content="content",
        normalized_text="标题：AI news\n摘要：summary",
        primary_topic="人工智能",
        topic_title="人工智能",
        topics_json="[]",
        topic_names_json='["人工智能"]',
        fund_theme_tags_json='["科技成长"]',
        fund_type_tags_json='["混合型"]',
        markets_json='["A股"]',
        asset_classes_json='["基金"]',
        impact_direction="unknown",
        published_at="2026-07-09 10:00:00",
        effective_until="2026-07-23 10:00:00",
        relevance_score=0.8,
        classification_status="accepted",
        index_status="pending",
        content_hash="full-hash-1",
        canonical_content_hash="canonical-1",
        raw_reason="accepted",
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add_all([
        KnowledgeSourceLink(
            document_id=doc.id,
            source_type="cls_telegraph",
            source_id="cls-1",
            source_url="https://www.cls.cn/detail/1",
            is_primary=True,
        ),
        KnowledgeSourceLink(
            document_id=doc.id,
            source_type="market_evidence",
            source_id="ev-1",
            source_url="https://www.cls.cn/detail/1",
            is_primary=False,
        ),
    ])
    db_session.commit()

    links = db_session.scalars(
        select(KnowledgeSourceLink).where(KnowledgeSourceLink.document_id == doc.id)
    ).all()
    assert {link.source_type for link in links} == {"cls_telegraph", "market_evidence"}


def test_classification_log_allows_multiple_attempts(db_session):
    db_session.add(KnowledgeClassificationState(
        source_type="cls_telegraph",
        source_id="cls-1",
        canonical_content_hash="canonical-1",
        latest_attempt_no=2,
        should_index=True,
        relevance_score=0.8,
        prompt_version="v1",
        status="accepted",
        reason="accepted",
    ))
    for attempt_no, status in [(1, "failed"), (2, "accepted")]:
        db_session.add(KnowledgeClassificationLog(
            source_type="cls_telegraph",
            source_id="cls-1",
            canonical_content_hash="canonical-1",
            attempt_no=attempt_no,
            prompt_version="v1",
            status=status,
            should_index=status == "accepted",
            relevance_score=0.8 if status == "accepted" else None,
            error_message="bad json" if status == "failed" else None,
            latency_ms=10 + attempt_no,
        ))
    db_session.commit()

    state = db_session.scalar(select(KnowledgeClassificationState))
    assert state.latest_attempt_no == 2
    assert len(db_session.scalars(select(KnowledgeClassificationLog)).all()) == 2


def test_classification_state_persists_retry_schedule(db_session):
    attempted_at = datetime(2026, 7, 10, 10, 0, 0)
    db_session.add(KnowledgeClassificationState(
        source_type="cls_telegraph",
        source_id="retry-1",
        canonical_content_hash="canonical-retry",
        latest_attempt_no=1,
        prompt_version="v1",
        status="failed",
        last_attempt_at=attempted_at,
        next_retry_at=attempted_at + timedelta(minutes=5),
    ))
    db_session.commit()

    state = db_session.scalar(select(KnowledgeClassificationState))
    assert state.last_attempt_at == attempted_at
    assert state.next_retry_at == attempted_at + timedelta(minutes=5)


def test_classification_log_unique_constraint_includes_content_hash(postgres_engine):
    unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspect(postgres_engine).get_unique_constraints(
            "knowledge_classification_log"
        )
    }
    assert (
        "source_type",
        "source_id",
        "canonical_content_hash",
        "prompt_version",
        "attempt_no",
    ) in unique_sets
