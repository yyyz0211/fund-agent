from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import date, datetime, timedelta

from sqlalchemy import select

from backend.config.settings import get_settings
from backend.db import repository as repo
from backend.db.models import KnowledgeClassificationState
from backend.db.session import get_session
from backend.services import knowledge_classifier
from backend.services.knowledge_normalizer import (
    build_normalized_text,
    canonical_content_hash,
    content_hash,
    effective_until,
    topic_names,
)
from backend.services.knowledge_schema import KnowledgeClassificationResult


def candidate_from_cls(row: dict) -> dict:
    """把财联社电报投影成知识候选。"""
    return {
        "source_type": "cls_telegraph",
        "source_id": str(row.get("cls_id") or row.get("id")),
        "source_url": row.get("source_url") or "",
        "title": row.get("title") or "",
        "brief": row.get("brief"),
        "content": row.get("content"),
        "cls_subjects": row.get("subjects") or [],
        "symbols": row.get("symbols") or [],
        "published_at": row.get("published_at"),
    }


def candidate_from_market_evidence(row: dict) -> dict:
    """把 market_evidence 投影成知识候选。"""
    return {
        "source_type": "market_evidence",
        "source_id": str(row.get("id")),
        "source_url": row.get("source_url") or "",
        "title": row.get("title") or "",
        "brief": row.get("summary"),
        "content": row.get("summary"),
        "cls_subjects": [],
        "symbols": row.get("symbols") or [],
        "published_at": row.get("published_at"),
    }


def _classify(classifier, candidate: dict) -> knowledge_classifier.ClassificationOutcome:
    if classifier is None:
        return knowledge_classifier.classify_candidate(candidate)
    if hasattr(classifier, "classify"):
        return classifier.classify(candidate)
    return classifier(candidate)


def _classification_state(session, candidate: dict):
    return session.scalar(
        select(KnowledgeClassificationState).where(
            KnowledgeClassificationState.source_type == candidate["source_type"],
            KnowledgeClassificationState.source_id == candidate["source_id"],
        )
    )


def _next_attempt_no(state, canonical_hash: str, prompt_version: str) -> int:
    if (
        state is None
        or state.canonical_content_hash != canonical_hash
        or state.prompt_version != prompt_version
    ):
        return 1
    return int(state.latest_attempt_no or 0) + 1


def should_classify_candidate(
    state,
    canonical_hash: str,
    prompt_version: str,
    now: datetime,
    max_attempts: int,
) -> tuple[bool, str]:
    """判断候选是否需要调用 LLM，避免稳定内容被周期性重复计费。"""
    if state is None:
        return True, "new"
    unchanged = (
        state.canonical_content_hash == canonical_hash
        and state.prompt_version == prompt_version
    )
    if unchanged and state.status in {"accepted", "rejected"}:
        return False, "unchanged"
    if unchanged and state.status == "failed":
        if int(state.latest_attempt_no or 0) >= max(1, int(max_attempts)):
            return False, "max_attempts"
        if state.next_retry_at and state.next_retry_at > now:
            return False, "retry_deferred"
    return True, "changed_or_retryable"


def _topics_json(result: KnowledgeClassificationResult) -> str:
    return json.dumps([topic.model_dump() for topic in result.topics], ensure_ascii=False)


def _list_json(values: list[str]) -> str | None:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def _document_payload(
    candidate: dict,
    result: KnowledgeClassificationResult,
    *,
    default_ttl_days: int,
) -> dict:
    normalized_text = build_normalized_text(candidate, result)
    canonical_hash = canonical_content_hash(candidate)
    until, ttl_days, ttl_clamped = effective_until(
        candidate.get("published_at"),
        candidate["source_type"],
        result.effective_ttl_days,
        default_ttl_days,
    )
    reason = result.reason
    if ttl_clamped:
        reason = f"{reason}; ttl_clamped=true effective_ttl_days={ttl_days}"
    return {
        "source_type": candidate["source_type"],
        "source_id": candidate["source_id"],
        "source_url": candidate.get("source_url") or "",
        "title": candidate.get("title") or "",
        "summary": result.summary,
        "content": candidate.get("content") or candidate.get("brief"),
        "normalized_text": normalized_text,
        "primary_topic": result.primary_topic,
        "topic_title": result.topic_title,
        "topics_json": _topics_json(result),
        "topic_names_json": _list_json(topic_names(result.topics)),
        "fund_theme_tags_json": _list_json(result.fund_theme_tags),
        "fund_type_tags_json": _list_json(result.fund_type_tags),
        "markets_json": _list_json(result.markets),
        "asset_classes_json": _list_json(result.asset_classes),
        "impact_direction": result.impact_direction,
        "published_at": candidate.get("published_at"),
        "effective_until": until,
        "relevance_score": result.relevance_score,
        "classification_status": "accepted",
        "index_status": "pending",
        "content_hash": content_hash(normalized_text),
        "canonical_content_hash": canonical_hash,
        "raw_reason": reason,
    }


def _write_classification(
    session,
    candidate: dict,
    outcome: knowledge_classifier.ClassificationOutcome,
    *,
    attempt_no: int,
    prompt_version: str,
    canonical_hash: str,
    document_id: int | None = None,
    attempted_at: datetime,
    retry_seconds: int,
) -> None:
    result = outcome.result
    repo.append_classification_log(session, {
        "source_type": candidate["source_type"],
        "source_id": candidate["source_id"],
        "canonical_content_hash": canonical_hash,
        "attempt_no": attempt_no,
        "prompt_version": prompt_version,
        "status": outcome.status,
        "should_index": result.should_index if result else False,
        "relevance_score": result.relevance_score if result else None,
        "reason": result.reason if result else None,
        "raw_response_json": outcome.raw_response,
        "error_message": outcome.error_message,
        "latency_ms": outcome.latency_ms,
    })
    repo.upsert_classification_state(session, {
        "source_type": candidate["source_type"],
        "source_id": candidate["source_id"],
        "canonical_content_hash": canonical_hash,
        "latest_attempt_no": attempt_no,
        "should_index": result.should_index if result else False,
        "relevance_score": result.relevance_score if result else None,
        "prompt_version": prompt_version,
        "status": outcome.status,
        "reason": result.reason if result else outcome.error_message,
        "document_id": document_id,
        "last_error_message": outcome.error_message,
        "last_attempt_at": attempted_at,
        "next_retry_at": (
            attempted_at + timedelta(seconds=max(1, int(retry_seconds)))
            if outcome.status == "failed"
            else None
        ),
    })


def ingest_candidates(
    candidates: list[dict],
    *,
    classifier=None,
    session,
) -> dict:
    """处理一批候选：准入、去重、写文档和状态。

    返回计数供调度器 / API 展示；所有写入都使用调用方传入的事务。
    """
    settings = get_settings()
    prompt_version = settings.knowledge_classification_prompt_version
    result_counts = {
        "processed": 0,
        "accepted": 0,
        "rejected": 0,
        "failed": 0,
        "documents_created": 0,
        "documents_reused": 0,
        "skipped_unchanged": 0,
        "retry_deferred": 0,
        "retry_exhausted": 0,
    }

    for raw_candidate in candidates:
        candidate = {
            **raw_candidate,
            "source_id": str(raw_candidate.get("source_id")),
            "source_type": str(raw_candidate.get("source_type")),
        }
        if not candidate.get("title"):
            continue
        result_counts["processed"] += 1
        canonical_hash = canonical_content_hash(candidate)
        state = _classification_state(session, candidate)
        attempted_at = datetime.utcnow()
        should_classify, decision = should_classify_candidate(
            state,
            canonical_hash,
            prompt_version,
            attempted_at,
            settings.knowledge_classification_max_attempts,
        )
        if not should_classify:
            if decision == "unchanged":
                result_counts["skipped_unchanged"] += 1
            elif decision == "retry_deferred":
                result_counts["retry_deferred"] += 1
            else:
                result_counts["retry_exhausted"] += 1
            continue
        attempt_no = _next_attempt_no(state, canonical_hash, prompt_version)
        outcome = _classify(classifier, candidate)

        if outcome.status == "failed" or outcome.result is None:
            result_counts["failed"] += 1
            _write_classification(
                session, candidate, outcome, attempt_no=attempt_no,
                prompt_version=prompt_version, canonical_hash=canonical_hash,
                attempted_at=attempted_at,
                retry_seconds=settings.knowledge_classification_retry_seconds,
            )
            continue

        if not outcome.result.should_index:
            result_counts["rejected"] += 1
            _write_classification(
                session, candidate, outcome, attempt_no=attempt_no,
                prompt_version=prompt_version, canonical_hash=canonical_hash,
                attempted_at=attempted_at,
                retry_seconds=settings.knowledge_classification_retry_seconds,
            )
            continue

        result_counts["accepted"] += 1
        doc_payload = _document_payload(
            candidate,
            outcome.result,
            default_ttl_days=settings.knowledge_default_ttl_days,
        )
        document, created = repo.upsert_knowledge_document(session, doc_payload)
        repo.upsert_knowledge_source_link(session, {
            "document_id": document["id"],
            "source_type": candidate["source_type"],
            "source_id": candidate["source_id"],
            "source_url": candidate.get("source_url"),
            "is_primary": bool(created),
        })
        result_counts["documents_created" if created else "documents_reused"] += 1
        _write_classification(
            session, candidate, outcome, attempt_no=attempt_no,
            prompt_version=prompt_version, canonical_hash=canonical_hash,
            document_id=document["id"],
            attempted_at=attempted_at,
            retry_seconds=settings.knowledge_classification_retry_seconds,
        )

    session.flush()
    return result_counts


def ingest_recent_knowledge(
    *,
    limit: int = 50,
    session=None,
    classifier=None,
) -> dict:
    """从现有来源表抽取最近候选并进入知识准入流程。"""
    owns_session = session is None
    active_session = session or get_session()
    ctx = active_session if owns_session else nullcontext(active_session)
    with ctx as s:
        cls_rows = repo.search_cls_telegraph_items(s, limit=limit)
        evidence_rows = repo.search_market_evidence(
            s, trade_date=date.today().isoformat(), limit=limit,
        )
        candidates = [candidate_from_cls(row) for row in cls_rows]
        candidates.extend(candidate_from_market_evidence(row) for row in evidence_rows)
        result = ingest_candidates(candidates, classifier=classifier, session=s)
        if owns_session:
            s.commit()
        return result
