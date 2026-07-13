from __future__ import annotations

import json
import logging
import time
from contextlib import nullcontext
from datetime import datetime

from sqlalchemy import or_, select

from backend.config.settings import get_settings
from backend.db import repository as repo
from backend.db.models import KnowledgeDocument, KnowledgeFundMatch, KnowledgeRetrievalLog
from backend.db.session import get_session
from backend.services import (
    knowledge_fund_profile_service,
    knowledge_ingestion_service,
    knowledge_match_service,
    knowledge_vector,
)
from backend.services.knowledge_embedding import build_embedding_provider
from backend.services.knowledge_pgvector import build_vector_store


STRUCTURED_FALLBACK_WARNING = (
    "语义索引暂不可用，已使用结构化检索兜底；本次结果仅基于标题/主题/"
    "基金标签关键词匹配，可能遗漏语义相近但词面不同的命中。"
)

logger = logging.getLogger(__name__)


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _freshness_score(published_at: str | None) -> float:
    if not published_at:
        return 0.5
    try:
        published = datetime.strptime(str(published_at)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0.5
    age_hours = max(0.0, (datetime.now() - published).total_seconds() / 3600)
    # 与 spec 保持一致：72 小时指数衰减，约 50 小时半衰期。
    import math
    return max(0.0, min(1.0, math.exp(-age_hours / 72)))


def _document_to_search_item(
    doc: KnowledgeDocument,
    *,
    semantic_score: float | None = None,
    fund_match: KnowledgeFundMatch | None = None,
) -> dict:
    relevance = float(doc.relevance_score or 0)
    freshness = _freshness_score(doc.published_at)
    fund_match_score = float(fund_match.match_score or 0) if fund_match else 0.0
    final_score = min(
        1.0,
        float(semantic_score or 0.0) * 0.30
        + freshness * 0.20
        + fund_match_score * 0.30
        + relevance * 0.20,
    )
    return {
        "document_id": doc.id,
        "title": doc.title,
        "topic_title": doc.topic_title,
        "summary": doc.summary,
        "source_url": doc.source_url,
        "published_at": doc.published_at,
        "final_score": round(final_score, 6),
        "retrieval_mode": "structured_fallback",
        "index_status": doc.index_status,
        "match_reason": fund_match.match_reason if fund_match else "",
        "matched_funds": [fund_match.fund_code] if fund_match else [],
        "matched_topics": _json_list(fund_match.matched_topics_json) if fund_match else [],
        "topics": _json_list(doc.topic_names_json),
    }


def merge_hybrid_candidates(
    structured_items: list[dict],
    vector_items: list[dict],
    *,
    limit: int,
) -> list[dict]:
    """按 document_id 合并候选，保留较高得分后再应用最终 limit。"""
    merged: dict[int, dict] = {}
    for item in [*structured_items, *vector_items]:
        document_id = int(item["document_id"])
        previous = merged.get(document_id)
        if previous is None or float(item.get("final_score") or 0) > float(
            previous.get("final_score") or 0
        ):
            merged[document_id] = item
    ranked = sorted(
        merged.values(),
        key=lambda item: float(item.get("final_score") or 0),
        reverse=True,
    )
    return ranked[:max(1, int(limit))]


def _apply_structured_filters(stmt, *, query, topic, source_type, date_from, date_to, include_pending):
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stmt = stmt.where(or_(
        KnowledgeDocument.effective_until.is_(None),
        KnowledgeDocument.effective_until >= now_text,
    ))
    if source_type:
        stmt = stmt.where(KnowledgeDocument.source_type == source_type)
    if topic:
        stmt = stmt.where(KnowledgeDocument.topic_names_json.like(f"%{topic}%"))
    if date_from:
        stmt = stmt.where(KnowledgeDocument.published_at >= date_from)
    if date_to:
        stmt = stmt.where(KnowledgeDocument.published_at <= date_to)
    if include_pending:
        stmt = stmt.where(KnowledgeDocument.index_status.in_(["indexed", "pending", "failed"]))
    if query:
        like = f"%{query}%"
        stmt = stmt.where(or_(
            KnowledgeDocument.title.like(like),
            KnowledgeDocument.summary.like(like),
            KnowledgeDocument.normalized_text.like(like),
            KnowledgeDocument.topic_names_json.like(like),
        ))
    return stmt


def _write_retrieval_log(session, *, query: str, filters: dict, mode: str, count: int, latency_ms: int) -> None:
    session.add(KnowledgeRetrievalLog(
        query=query or "",
        filters_json=json.dumps(filters, ensure_ascii=False),
        retrieval_mode=mode,
        result_count=count,
        latency_ms=latency_ms,
    ))
    session.flush()


def search_knowledge(
    query: str,
    *,
    fund_code: str | None = None,
    topic: str | None = None,
    source_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
    include_pending: bool = False,
    session=None,
    vector_store=None,
    embedding_provider=None,
) -> dict:
    """混合检索入口。

    基金过滤使用预计算 KnowledgeFundMatch；没有匹配时返回空结果。
    """
    started = time.monotonic()
    owns_session = session is None
    active_session = session or get_session()
    ctx = active_session if owns_session else nullcontext(active_session)
    with ctx as s:
        mode = "structured_fallback"
        warning = STRUCTURED_FALLBACK_WARNING
        try:
            active_provider = embedding_provider or build_embedding_provider(get_settings())
            active_store = vector_store or build_vector_store(s, get_settings())
        except Exception as exc:  # noqa: BLE001 - 检索必须能结构化降级
            logger.warning("knowledge vector runtime unavailable: %s", exc)
            active_provider = None
            active_store = None
        vector_available = active_provider is not None and active_store is not None
        match_by_doc: dict[int, KnowledgeFundMatch] = {}
        if fund_code:
            matches = s.scalars(
                select(KnowledgeFundMatch).where(KnowledgeFundMatch.fund_code == fund_code)
            ).all()
            match_by_doc = {match.document_id: match for match in matches}
            if not match_by_doc:
                _write_retrieval_log(
                    s,
                    query=query,
                    filters={"fund_code": fund_code, "topic": topic, "source_type": source_type},
                    mode="structured_fallback",
                    count=0,
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                if owns_session:
                    s.commit()
                return {
                    "count": 0,
                    "retrieval_mode": "structured_fallback",
                    "coverage_warning": STRUCTURED_FALLBACK_WARNING,
                    "items": [],
                }

        filters = {
            "fund_code": fund_code,
            "topic": topic,
            "source_type": source_type,
            "date_from": date_from,
            "date_to": date_to,
            "include_pending": include_pending,
        }
        candidate_limit = max(1, int(limit)) * 5
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.classification_status == "accepted"
        )
        if match_by_doc:
            stmt = stmt.where(KnowledgeDocument.id.in_(list(match_by_doc)))
        stmt = _apply_structured_filters(
            stmt,
            query=query,
            topic=topic,
            source_type=source_type,
            date_from=date_from,
            date_to=date_to,
            include_pending=include_pending,
        )
        docs = s.scalars(
            stmt.order_by(
                KnowledgeDocument.published_at.desc().nullslast(),
                KnowledgeDocument.id.desc(),
            ).limit(candidate_limit)
        ).all()
        structured_items = [
            _document_to_search_item(doc, fund_match=match_by_doc.get(doc.id))
            for doc in docs
        ]
        vector_items: list[dict] = []
        if vector_available and query.strip():
            try:
                query_vector = active_provider.embed([query])[0]
                vector_filters = {
                    key: value for key, value in {
                        "topic": topic,
                        "source_type": source_type,
                        "date_from": date_from,
                        "date_to": date_to,
                    }.items() if value not in (None, "")
                }
                hits = active_store.search(query_vector, vector_filters, candidate_limit)
                semantic_by_doc = {
                    int(hit.document_id): float(hit.score) for hit in hits
                    if not match_by_doc or int(hit.document_id) in match_by_doc
                }
                if semantic_by_doc:
                    vector_stmt = select(KnowledgeDocument).where(
                        KnowledgeDocument.id.in_(list(semantic_by_doc)),
                        KnowledgeDocument.classification_status == "accepted",
                    )
                    vector_stmt = _apply_structured_filters(
                        vector_stmt,
                        query="",
                        topic=topic,
                        source_type=source_type,
                        date_from=date_from,
                        date_to=date_to,
                        include_pending=True,
                    )
                    vector_docs = s.scalars(vector_stmt).all()
                    vector_items = [
                        _document_to_search_item(
                            doc,
                            semantic_score=semantic_by_doc.get(int(doc.id)),
                            fund_match=match_by_doc.get(doc.id),
                        )
                        for doc in vector_docs
                    ]
                mode = "hybrid"
                warning = None
            except Exception as exc:  # noqa: BLE001 - 语义失败走结构化兜底
                logger.warning("knowledge vector search failed; using fallback: %s", exc)
        items = merge_hybrid_candidates(
            structured_items,
            vector_items,
            limit=limit,
        )
        for item in items:
            item["retrieval_mode"] = mode
        _write_retrieval_log(
            s,
            query=query,
            filters=filters,
            mode=mode,
            count=len(items),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        if owns_session:
            s.commit()
        return {
            "count": len(items),
            "retrieval_mode": mode,
            "coverage_warning": warning,
            "items": items,
        }


def get_queue_status(
    *,
    source_type: str | None = None,
    classification_status: str | None = None,
    index_status: str | None = None,
    since: str | None = None,
    limit: int = 50,
    session=None,
) -> dict:
    owns_session = session is None
    active_session = session or get_session()
    ctx = active_session if owns_session else nullcontext(active_session)
    with ctx as s:
        return repo.queue_status(
            s,
            source_type=source_type,
            classification_status=classification_status,
            index_status=index_status,
            since=since,
            limit=limit,
        )


def run_knowledge_pipeline_once(
    *,
    trigger: str = "manual",
    limit: int | None = None,
    session=None,
    classifier=None,
    embedding_provider=None,
    vector_store=None,
) -> dict:
    """运行一次知识库增量流水线。

    这是一条共享入口：API 手动重建和 scheduler 定时任务都走这里，避免
    两边各自拼流程导致行为漂移。当前默认使用进程内 deterministic
    embedding + 内存向量库，保证本地开发和测试无外部依赖；后续接 Qdrant
    或真实 embedding provider 时，只需要在这里替换默认 provider/store。
    """
    settings = get_settings()
    classification_limit = int(limit or settings.knowledge_classification_batch_size)
    index_limit = int(limit or settings.knowledge_index_batch_size)
    started = time.monotonic()
    owns_session = session is None
    active_session = session or get_session()
    ctx = active_session if owns_session else nullcontext(active_session)
    with ctx as s:
        try:
            ingestion = knowledge_ingestion_service.ingest_recent_knowledge(
                limit=classification_limit,
                session=s,
                classifier=classifier,
            )
            active_provider = embedding_provider or build_embedding_provider(settings)
            active_store = vector_store or build_vector_store(s, settings)
            if active_provider is not None and active_store is not None:
                index_result = knowledge_vector.index_pending_documents(
                    session=s,
                    embedding_provider=active_provider,
                    vector_store=active_store,
                    limit=index_limit,
                    max_attempts=int(getattr(settings, "knowledge_index_max_attempts", 3)),
                    retry_seconds=int(getattr(settings, "knowledge_index_retry_seconds", 300)),
                )
            else:
                index_result = {
                    "processed": 0,
                    "indexed": 0,
                    "failed": 0,
                    "skipped": "vector_unavailable",
                }
            profiles = knowledge_fund_profile_service.refresh_fund_watchlist_profiles(session=s)
            matches = knowledge_match_service.refresh_knowledge_fund_matches(session=s)
            if owns_session:
                s.commit()
            return {
                "status": "completed",
                "trigger": trigger,
                "ingestion": ingestion,
                "index": index_result,
                "profiles": profiles,
                "matches": matches,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        except Exception:
            if owns_session:
                s.rollback()
            raise
