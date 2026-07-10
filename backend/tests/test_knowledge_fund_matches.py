from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.db.init_db import init_db
from backend.db.models import FundWatchlistProfile, KnowledgeDocument, KnowledgeFundMatch
from backend.services.knowledge_match_service import (
    calculate_match_score,
    refresh_knowledge_fund_matches,
)


def test_calculate_match_score_prioritizes_holding_primary_topic():
    document = {
        "primary_topic": "人工智能",
        "topic_names": ["人工智能", "半导体"],
        "fund_theme_tags": ["科技成长", "人工智能"],
        "fund_type_tags": ["混合型"],
    }
    profile = {
        "fund_code": "000001",
        "fund_name": "人工智能主题混合",
        "priority": "holding",
        "holding_weight": 0.8,
        "theme_tags": ["人工智能", "科技成长"],
        "fund_type": "混合型",
    }

    score, topics, reason = calculate_match_score(document, profile)

    assert score > 0.7
    assert "人工智能" in topics
    assert "命中持仓基金" in reason


def test_calculate_match_score_returns_zero_for_unrelated_profile():
    score, topics, reason = calculate_match_score(
        {
            "primary_topic": "人工智能",
            "topic_names": ["人工智能"],
            "fund_theme_tags": ["科技成长"],
            "fund_type_tags": [],
        },
        {
            "fund_code": "000002",
            "fund_name": "消费主题混合",
            "priority": "watching",
            "holding_weight": 0,
            "theme_tags": ["消费"],
            "fund_type": "债券型",
        },
    )

    assert score == 0
    assert topics == []
    assert reason == ""


def test_refresh_matches_deletes_relationship_that_no_longer_matches():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    with Session(eng) as s:
        doc = KnowledgeDocument(
            source_type="cls_telegraph",
            source_id="cls-1",
            source_url="u1",
            title="AI消息",
            summary="summary",
            content="content",
            normalized_text="AI消息",
            primary_topic="人工智能",
            topic_title="人工智能",
            topics_json="[]",
            topic_names_json='["人工智能"]',
            fund_theme_tags_json='["科技成长"]',
            fund_type_tags_json="[]",
            markets_json="[]",
            asset_classes_json="[]",
            impact_direction="neutral",
            published_at="2026-07-10 10:00:00",
            effective_until="2099-01-01 00:00:00",
            relevance_score=0.8,
            classification_status="accepted",
            index_status="indexed",
            content_hash="hash-1",
            canonical_content_hash="canonical-1",
        )
        profile = FundWatchlistProfile(
            fund_code="000001",
            fund_name="消费主题基金",
            priority="watching",
            theme_tags_json='["消费"]',
            fund_type="债券型",
            profile_status="ready",
        )
        s.add_all([doc, profile])
        s.flush()
        s.add(KnowledgeFundMatch(
            document_id=doc.id,
            fund_code=profile.fund_code,
            match_score=0.8,
            matched_topics_json='["人工智能"]',
            match_reason="旧关系",
        ))
        s.commit()

        result = refresh_knowledge_fund_matches(session=s)

        assert result["matches_deleted"] == 1
        assert s.scalar(select(KnowledgeFundMatch)) is None
