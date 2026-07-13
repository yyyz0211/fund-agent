from __future__ import annotations

import json

import pytest

from backend.services.knowledge_classifier import (
    build_classification_prompt,
    classify_candidate,
    parse_classification_response,
)
from backend.services.knowledge_schema import KnowledgeCandidate


class FakeModel:
    def __init__(self, text: str):
        self.text = text

    def invoke(self, _prompt: str):
        class Message:
            content = self.text
        return Message()


def _valid_payload() -> dict:
    return {
        "should_index": True,
        "relevance_score": 0.8,
        "summary": "summary",
        "primary_topic": "人工智能",
        "topics": [{"name": "人工智能", "weight": "high", "source": "cls_subject"}],
        "topic_title": "人工智能",
        "fund_theme_tags": ["科技成长"],
        "fund_type_tags": ["混合型"],
        "markets": ["A股"],
        "asset_classes": ["基金"],
        "impact_direction": "negative",
        "effective_ttl_days": 14,
        "reason": "market related",
        "confidence": "high",
    }


def test_parse_classification_response_accepts_strict_json():
    result = parse_classification_response(json.dumps(_valid_payload(), ensure_ascii=False))

    assert result.should_index is True
    assert result.topics[0].name == "人工智能"


def test_parse_classification_response_rejects_non_json():
    with pytest.raises(ValueError, match="strict JSON"):
        parse_classification_response("这条新闻和市场有关")


def test_parse_classification_response_rejects_bad_score_range():
    payload = _valid_payload()
    payload["relevance_score"] = 1.5

    with pytest.raises(ValueError, match="schema validation failed"):
        parse_classification_response(json.dumps(payload, ensure_ascii=False))


def test_classify_candidate_returns_failed_outcome_for_bad_json():
    candidate = {
        "source_type": "cls_telegraph",
        "source_id": "cls-1",
        "title": "AI消息",
        "content": "AI消息",
    }

    outcome = classify_candidate(candidate, model=FakeModel("not json"))

    assert outcome.status == "failed"
    assert outcome.result is None
    assert "strict JSON" in outcome.error_message


def test_prompt_includes_no_advice_boundary():
    candidate = KnowledgeCandidate(
        source_type="cls_telegraph",
        source_id="cls-1",
        title="AI消息",
        content="AI消息",
    )

    prompt = build_classification_prompt(candidate, prompt_version="v1")

    assert "不要输出买入" in prompt
    assert "strict JSON" in prompt
