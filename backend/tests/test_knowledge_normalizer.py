from __future__ import annotations

from backend.services.knowledge.knowledge_normalizer import (
    build_normalized_text,
    canonical_content_hash,
    effective_until,
    topic_names,
)
from backend.services.knowledge.knowledge_schema import KnowledgeClassificationResult, TopicTag


def test_canonical_content_hash_is_source_independent():
    cls = {
        "source_type": "cls_telegraph",
        "source_id": "cls-1",
        "title": "AI产业链回调",
        "content": "美股AI相关科技股回调。",
        "published_at": "2026-07-09 10:00:00",
    }
    evidence = {
        "source_type": "market_evidence",
        "source_id": "ev-1",
        "title": "AI产业链回调",
        "content": "美股AI相关科技股回调。",
        "published_at": "2026-07-09 10:03:00",
    }

    assert canonical_content_hash(cls) == canonical_content_hash(evidence)


def test_topic_names_keeps_first_seen_order():
    topics = [
        TopicTag(name="人工智能", weight="high", source="cls_subject"),
        TopicTag(name="半导体", weight="high", source="llm"),
        TopicTag(name="人工智能", weight="medium", source="llm"),
    ]

    assert topic_names(topics) == ["人工智能", "半导体"]


def test_effective_until_clamps_cls_ttl_to_upper_bound():
    until, ttl, clamped = effective_until(
        "2026-07-09 10:00:00",
        "cls_telegraph",
        365,
        14,
    )

    assert ttl == 30
    assert clamped is True
    assert until == "2026-08-08 10:00:00"


def test_build_normalized_text_uses_stable_template():
    candidate = {
        "title": "AI产业链回调",
        "content": "美股AI相关科技股回调。",
        "source_type": "cls_telegraph",
        "published_at": "2026-07-09 10:00:00",
    }
    classification = KnowledgeClassificationResult(
        should_index=True,
        relevance_score=0.8,
        summary="美股AI相关科技股回调。",
        primary_topic="人工智能",
        topics=[TopicTag(name="人工智能", weight="high", source="cls_subject")],
        topic_title="人工智能",
        fund_theme_tags=["科技成长"],
        fund_type_tags=["混合型"],
        markets=["美股", "A股"],
        asset_classes=["股票", "基金"],
        impact_direction="negative",
        effective_ttl_days=14,
        reason="与科技成长相关",
        confidence="high",
    )

    text = build_normalized_text(candidate, classification)

    assert "标题：AI产业链回调" in text
    assert "主题：人工智能" in text
    assert "基金主题：科技成长" in text
    assert "发布时间：2026-07-09 10:00:00" in text
