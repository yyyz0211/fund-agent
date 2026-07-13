from __future__ import annotations

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from backend.db.init_db import init_db
from backend.db.models import (
    KnowledgeClassificationLog,
    KnowledgeClassificationState,
    KnowledgeDocument,
    KnowledgeSourceLink,
)


def test_init_db_creates_knowledge_tables():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    tables = set(inspect(eng).get_table_names())

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


def test_canonical_content_hash_dedupes_across_sources():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    with Session(eng) as s:
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
            embedding_model=None,
            embedding_version=None,
            content_hash="full-hash-1",
            canonical_content_hash="canonical-1",
            raw_reason="accepted",
        )
        s.add(doc)
        s.flush()
        s.add(KnowledgeSourceLink(
            document_id=doc.id,
            source_type="cls_telegraph",
            source_id="cls-1",
            source_url="https://www.cls.cn/detail/1",
            is_primary=True,
        ))
        s.add(KnowledgeSourceLink(
            document_id=doc.id,
            source_type="market_evidence",
            source_id="ev-1",
            source_url="https://www.cls.cn/detail/1",
            is_primary=False,
        ))
        s.commit()

        links = s.scalars(select(KnowledgeSourceLink).where(
            KnowledgeSourceLink.document_id == doc.id
        )).all()
        assert {link.source_type for link in links} == {"cls_telegraph", "market_evidence"}


def test_classification_log_allows_multiple_attempts():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    with Session(eng) as s:
        s.add(KnowledgeClassificationState(
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
        s.add(KnowledgeClassificationLog(
            source_type="cls_telegraph",
            source_id="cls-1",
            canonical_content_hash="canonical-1",
            attempt_no=1,
            prompt_version="v1",
            status="failed",
            should_index=False,
            relevance_score=None,
            reason=None,
            raw_response_json=None,
            error_message="bad json",
            latency_ms=10,
        ))
        s.add(KnowledgeClassificationLog(
            source_type="cls_telegraph",
            source_id="cls-1",
            canonical_content_hash="canonical-1",
            attempt_no=2,
            prompt_version="v1",
            status="accepted",
            should_index=True,
            relevance_score=0.8,
            reason="accepted",
            raw_response_json='{"should_index": true}',
            error_message=None,
            latency_ms=12,
        ))
        s.commit()

        assert s.scalar(select(KnowledgeClassificationState).where(
            KnowledgeClassificationState.source_id == "cls-1"
        )).latest_attempt_no == 2


def test_classification_state_persists_retry_schedule():
    from datetime import datetime, timedelta

    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    attempted_at = datetime(2026, 7, 10, 10, 0, 0)
    with Session(eng) as s:
        s.add(KnowledgeClassificationState(
            source_type="cls_telegraph",
            source_id="retry-1",
            canonical_content_hash="canonical-retry",
            latest_attempt_no=1,
            prompt_version="v1",
            status="failed",
            last_attempt_at=attempted_at,
            next_retry_at=attempted_at + timedelta(minutes=5),
        ))
        s.commit()

        state = s.scalar(select(KnowledgeClassificationState))
        assert state.last_attempt_at == attempted_at
        assert state.next_retry_at == attempted_at + timedelta(minutes=5)


def test_init_db_migrates_classification_log_constraint_idempotently():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text("""
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
                CONSTRAINT uq_knowledge_classification_log_attempt UNIQUE (
                    source_type, source_id, prompt_version, attempt_no
                )
            )
        """))
        conn.execute(text("""
            INSERT INTO knowledge_classification_log (
                source_type, source_id, canonical_content_hash, attempt_no,
                prompt_version, status, error_message, latency_ms
            ) VALUES (
                'cls_telegraph', 'legacy-1', 'old-hash', 1,
                'v1', 'failed', 'temporary failure', 10
            )
        """))

    init_db(eng)
    init_db(eng)

    with eng.connect() as conn:
        unique_columns = [
            [
                column[2]
                for column in conn.exec_driver_sql(
                    f"PRAGMA index_info({index[1]})"
                ).all()
            ]
            for index in conn.exec_driver_sql(
                "PRAGMA index_list(knowledge_classification_log)"
            ).all()
            if bool(index[2])
        ]
    assert [
            "source_type",
            "source_id",
            "canonical_content_hash",
            "prompt_version",
            "attempt_no",
        ] in unique_columns

    with Session(eng) as s:
        preserved = s.scalar(select(KnowledgeClassificationLog))
        assert preserved.canonical_content_hash == "old-hash"
        assert preserved.error_message == "temporary failure"
        s.add(KnowledgeClassificationLog(
            source_type="cls_telegraph",
            source_id="legacy-1",
            canonical_content_hash="new-hash",
            attempt_no=1,
            prompt_version="v1",
            status="failed",
            error_message="another temporary failure",
            latency_ms=11,
        ))
        s.commit()

        assert len(s.scalars(select(KnowledgeClassificationLog)).all()) == 2
