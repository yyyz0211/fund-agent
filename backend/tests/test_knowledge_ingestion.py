from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.db.models import (
    KnowledgeClassificationLog,
    KnowledgeClassificationState,
    KnowledgeDocument,
)
from backend.services.knowledge.knowledge_classifier import ClassificationOutcome
from backend.services.knowledge.knowledge_ingestion_service import ingest_candidates
from backend.services.knowledge.knowledge_schema import KnowledgeClassificationResult, TopicTag


pytestmark = pytest.mark.db


class StaticClassifier:
    def __init__(self, result):
        self.result = result

    def classify(self, _candidate):
        return ClassificationOutcome(
            status="accepted" if self.result.should_index else "rejected",
            result=self.result,
            raw_response=self.result.model_dump_json(),
            error_message=None,
            latency_ms=1,
        )


class CountingClassifier(StaticClassifier):
    def __init__(self, result):
        super().__init__(result)
        self.calls = 0

    def classify(self, candidate):
        self.calls += 1
        return super().classify(candidate)


class CountingFailedClassifier:
    def __init__(self):
        self.calls = 0

    def classify(self, _candidate):
        self.calls += 1
        return ClassificationOutcome(
            status="failed",
            result=None,
            raw_response=None,
            error_message="temporary failure",
            latency_ms=1,
        )


def accepted_result():
    return KnowledgeClassificationResult(
        should_index=True,
        relevance_score=0.8,
        summary="summary",
        primary_topic="人工智能",
        topics=[TopicTag(name="人工智能", weight="high", source="cls_subject")],
        topic_title="人工智能",
        fund_theme_tags=["科技成长"],
        fund_type_tags=["混合型"],
        markets=["A股"],
        asset_classes=["基金"],
        impact_direction="negative",
        effective_ttl_days=14,
        reason="accepted",
        confidence="high",
    )


def test_ingest_candidates_creates_document_for_accepted_item(db_session):
    candidate = {
        "source_type": "cls_telegraph",
        "source_id": "cls-1",
        "source_url": "https://www.cls.cn/detail/1",
        "title": "AI消息",
        "content": "AI消息",
        "published_at": "2026-07-09 10:00:00",
    }

    result = ingest_candidates(
        [candidate], classifier=StaticClassifier(accepted_result()), session=db_session,
    )

    assert result["accepted"] == 1
    doc = db_session.scalar(select(KnowledgeDocument))
    assert doc.title == "AI消息"
    assert doc.index_status == "pending"
    state = db_session.scalar(select(KnowledgeClassificationState))
    assert state.status == "accepted"
    assert state.document_id == doc.id


def test_ingest_candidates_logs_rejected_without_document(db_session):
    rejected = accepted_result().model_copy(update={"should_index": False, "reason": "not market related"})

    result = ingest_candidates([{
        "source_type": "cls_telegraph",
        "source_id": "cls-2",
        "title": "无关消息",
        "content": "无关消息",
    }], classifier=StaticClassifier(rejected), session=db_session)

    assert result["rejected"] == 1
    assert db_session.scalar(select(KnowledgeDocument)) is None
    assert db_session.scalar(select(KnowledgeClassificationState)).status == "rejected"


def test_ingest_candidates_dedupes_cross_source_items(db_session):
    candidates = [
        {
            "source_type": "cls_telegraph",
            "source_id": "cls-1",
            "source_url": "u1",
            "title": "AI消息",
            "content": "同一内容",
            "published_at": "2026-07-09 10:00:00",
        },
        {
            "source_type": "market_evidence",
            "source_id": "ev-1",
            "source_url": "u1",
            "title": "AI消息",
            "content": "同一内容",
            "published_at": "2026-07-09 10:02:00",
        },
    ]

    result = ingest_candidates(
        candidates, classifier=StaticClassifier(accepted_result()), session=db_session,
    )

    assert result["accepted"] == 2
    assert result["documents_created"] == 1


def test_ingest_candidates_skips_unchanged_candidate_with_same_prompt(db_session):
    classifier = CountingClassifier(accepted_result())
    candidate = {
        "source_type": "cls_telegraph",
        "source_id": "stable-1",
        "title": "AI消息",
        "content": "内容没有变化",
        "published_at": "2026-07-09 10:00:00",
    }

    ingest_candidates([candidate], classifier=classifier, session=db_session)
    second = ingest_candidates([candidate], classifier=classifier, session=db_session)

    assert classifier.calls == 1
    assert second["skipped_unchanged"] == 1
    assert db_session.scalar(select(KnowledgeClassificationState)).latest_attempt_no == 1


def test_ingest_candidates_stops_retrying_after_max_attempts(db_session):
    classifier = CountingFailedClassifier()
    candidate = {
        "source_type": "cls_telegraph",
        "source_id": "failed-1",
        "title": "AI消息",
        "content": "分类服务暂时失败",
    }

    ingest_candidates([candidate], classifier=classifier, session=db_session)
    state = db_session.scalar(select(KnowledgeClassificationState))
    state.latest_attempt_no = 3
    state.next_retry_at = None
    db_session.flush()

    second = ingest_candidates([candidate], classifier=classifier, session=db_session)

    assert classifier.calls == 1
    assert second["retry_exhausted"] == 1


def test_changed_content_resets_exhausted_classification_attempts(db_session):
    classifier = CountingFailedClassifier()
    candidate = {
        "source_type": "cls_telegraph",
        "source_id": "changed-after-failure-1",
        "title": "AI消息",
        "content": "旧内容",
    }

    ingest_candidates([candidate], classifier=classifier, session=db_session)
    state = db_session.scalar(select(KnowledgeClassificationState))
    state.latest_attempt_no = 3
    state.next_retry_at = None
    db_session.flush()

    changed = {**candidate, "content": "新内容"}
    second = ingest_candidates([changed], classifier=classifier, session=db_session)
    logs = db_session.scalars(
        select(KnowledgeClassificationLog).order_by(KnowledgeClassificationLog.id)
    ).all()

    assert classifier.calls == 2
    assert second["failed"] == 1
    assert state.latest_attempt_no == 1
    assert [log.attempt_no for log in logs] == [1, 1]
    assert logs[0].canonical_content_hash != logs[1].canonical_content_hash
