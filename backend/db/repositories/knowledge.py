"""Knowledge repository: 知识库、RAG 相关持久化。"""
from __future__ import annotations

from sqlalchemy import Integer, and_, cast, func, or_, select

from backend.db.models import (
    ClsTelegraphItem,
    ClsTelegraphSyncState,
    KnowledgeClassificationLog,
    KnowledgeClassificationState,
    KnowledgeDocument,
    KnowledgeFundMatch,
    KnowledgeSourceLink,
)
from backend.db.repositories._serialization import json_loads as _json_loads


def _cls_telegraph_to_dict(row: ClsTelegraphItem) -> dict:
    """ClsTelegraphItem 的可序列化投影。"""
    subjects = _json_loads(row.subjects_json, [])
    symbols = _json_loads(row.symbols_json, [])
    raw_json = _json_loads(row.raw_json, {})
    return {
        "id": row.id,
        "cls_id": row.cls_id,
        "title": row.title,
        "brief": row.brief,
        "content": row.content,
        "category": row.category,
        "subjects": subjects if isinstance(subjects, list) else [],
        "symbols": symbols if isinstance(symbols, list) else [],
        "source_url": row.source_url,
        "ctime": row.ctime,
        "published_at": row.published_at,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "raw_json": raw_json if isinstance(raw_json, dict) else {},
    }


def upsert_cls_telegraph_item(s, row: dict) -> bool:
    """按 `cls_id` upsert 财联社电报。

    返回 True 表示新建,False 表示更新已有行。
    """
    import json as _json
    from datetime import datetime

    cls_id = str(row["cls_id"])
    subjects = row.get("subjects") or []
    symbols = row.get("symbols") or []
    raw_json = row.get("raw_json") or {}
    now = datetime.utcnow()
    payload = {
        "cls_id": cls_id,
        "title": row["title"],
        "brief": row.get("brief"),
        "content": row.get("content"),
        "category": row.get("category") or None,
        "subjects_json": _json.dumps(subjects, ensure_ascii=False) if subjects else None,
        "symbols_json": _json.dumps(symbols, ensure_ascii=False) if symbols else None,
        "source_url": row["source_url"],
        "ctime": int(row["ctime"]) if row.get("ctime") is not None else None,
        "published_at": row.get("published_at"),
        "raw_json": _json.dumps(raw_json, ensure_ascii=False) if raw_json else None,
        "fetched_at": now,
        "updated_at": now,
    }
    existing = s.scalar(select(ClsTelegraphItem).where(ClsTelegraphItem.cls_id == cls_id))
    if existing is None:
        s.add(ClsTelegraphItem(**payload, created_at=now))
        s.flush()
        return True
    for key, value in payload.items():
        setattr(existing, key, value)
    s.flush()
    return False


def search_cls_telegraph_items(
    s,
    *,
    limit: int = 50,
    category: str | None = None,
    since_id: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """查询财联社电报,默认按 `ctime/id` 新到旧排序。"""
    stmt = select(ClsTelegraphItem)
    if category:
        stmt = stmt.where(ClsTelegraphItem.category == category)
    if since_id:
        try:
            stmt = stmt.where(cast(ClsTelegraphItem.cls_id, Integer) > int(since_id))
        except (TypeError, ValueError):
            stmt = stmt.where(ClsTelegraphItem.cls_id > str(since_id))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                ClsTelegraphItem.title.like(like),
                ClsTelegraphItem.brief.like(like),
                ClsTelegraphItem.content.like(like),
            )
        )
    stmt = stmt.order_by(
        ClsTelegraphItem.ctime.desc().nullslast(),
        ClsTelegraphItem.id.desc(),
    ).limit(max(1, min(200, int(limit))))
    rows = s.scalars(stmt).all()
    return [_cls_telegraph_to_dict(row) for row in rows]


def _cls_state_to_dict(row: ClsTelegraphSyncState | None) -> dict:
    if row is None:
        return {
            "last_seen_ctime": None,
            "last_seen_cls_id": None,
            "last_success_at": None,
            "last_error": None,
        }
    return {
        "last_seen_ctime": row.last_seen_ctime,
        "last_seen_cls_id": row.last_seen_cls_id,
        "last_success_at": row.last_success_at,
        "last_error": row.last_error,
    }


def get_cls_telegraph_sync_state(s) -> dict:
    """读取财联社电报同步状态。无状态行时返回空状态。"""
    row = s.get(ClsTelegraphSyncState, "default")
    return _cls_state_to_dict(row)


def update_cls_telegraph_sync_state(
    s,
    *,
    last_seen_ctime: int | None = None,
    last_seen_cls_id: str | None = None,
    last_success_at: str | None = None,
    last_error: str | None = None,
) -> dict:
    """更新同步状态；传 None 的断点字段会保留原值。"""
    row = s.get(ClsTelegraphSyncState, "default")
    if row is None:
        row = ClsTelegraphSyncState(id="default")
        s.add(row)
    if last_seen_ctime is not None:
        row.last_seen_ctime = int(last_seen_ctime)
    if last_seen_cls_id is not None:
        row.last_seen_cls_id = str(last_seen_cls_id)
    if last_success_at is not None:
        row.last_success_at = last_success_at
    row.last_error = last_error
    s.flush()
    return _cls_state_to_dict(row)


# ---------------------------------------------------------------------------
# Knowledge Base / RAG
# ---------------------------------------------------------------------------

def _knowledge_document_to_dict(row: KnowledgeDocument) -> dict:
    """KnowledgeDocument 的可序列化投影。

    JSON 字段在 SQLite 中以字符串保存；这里统一解析成 list，避免 service
    层到处重复写容错解析。
    """
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_url": row.source_url,
        "title": row.title,
        "summary": row.summary,
        "content": row.content,
        "normalized_text": row.normalized_text,
        "primary_topic": row.primary_topic,
        "topic_title": row.topic_title,
        "topics": _json_loads(row.topics_json, []),
        "topic_names": _json_loads(row.topic_names_json, []),
        "fund_theme_tags": _json_loads(row.fund_theme_tags_json, []),
        "fund_type_tags": _json_loads(row.fund_type_tags_json, []),
        "markets": _json_loads(row.markets_json, []),
        "asset_classes": _json_loads(row.asset_classes_json, []),
        "impact_direction": row.impact_direction,
        "published_at": row.published_at,
        "effective_until": row.effective_until,
        "relevance_score": row.relevance_score,
        "classification_status": row.classification_status,
        "index_status": row.index_status,
        "embedding_model": row.embedding_model,
        "embedding_version": row.embedding_version,
        "index_attempts": row.index_attempts,
        "last_index_error": row.last_index_error,
        "next_index_retry_at": (
            row.next_index_retry_at.isoformat() if row.next_index_retry_at else None
        ),
        "content_hash": row.content_hash,
        "canonical_content_hash": row.canonical_content_hash,
        "raw_reason": row.raw_reason,
        "conflict_status": row.conflict_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _classification_state_to_dict(row: KnowledgeClassificationState) -> dict:
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "canonical_content_hash": row.canonical_content_hash,
        "latest_attempt_no": row.latest_attempt_no,
        "should_index": row.should_index,
        "relevance_score": row.relevance_score,
        "prompt_version": row.prompt_version,
        "status": row.status,
        "reason": row.reason,
        "document_id": row.document_id,
        "last_error_message": row.last_error_message,
        "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _source_link_to_dict(row: KnowledgeSourceLink) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_url": row.source_url,
        "is_primary": row.is_primary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def upsert_classification_state(s, payload: dict) -> dict:
    """按 `(source_type, source_id)` 更新候选的最新 LLM 准入状态。"""
    row = s.scalar(
        select(KnowledgeClassificationState).where(
            KnowledgeClassificationState.source_type == payload["source_type"],
            KnowledgeClassificationState.source_id == payload["source_id"],
        )
    )
    values = {
        "source_type": payload["source_type"],
        "source_id": payload["source_id"],
        "canonical_content_hash": payload.get("canonical_content_hash"),
        "latest_attempt_no": int(payload.get("latest_attempt_no") or 0),
        "should_index": payload.get("should_index"),
        "relevance_score": payload.get("relevance_score"),
        "prompt_version": payload.get("prompt_version") or "v1",
        "status": payload.get("status") or "pending",
        "reason": payload.get("reason"),
        "document_id": payload.get("document_id"),
        "last_error_message": payload.get("last_error_message"),
        "last_attempt_at": payload.get("last_attempt_at"),
        "next_retry_at": payload.get("next_retry_at"),
    }
    if row is None:
        row = KnowledgeClassificationState(**values)
        s.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    s.flush()
    return _classification_state_to_dict(row)


def append_classification_log(s, payload: dict) -> dict:
    """追加一次 LLM 准入尝试日志。"""
    row = KnowledgeClassificationLog(
        source_type=payload["source_type"],
        source_id=payload["source_id"],
        canonical_content_hash=payload.get("canonical_content_hash"),
        attempt_no=int(payload.get("attempt_no") or 1),
        prompt_version=payload.get("prompt_version") or "v1",
        status=payload.get("status") or "failed",
        should_index=payload.get("should_index"),
        relevance_score=payload.get("relevance_score"),
        reason=payload.get("reason"),
        raw_response_json=payload.get("raw_response_json"),
        error_message=payload.get("error_message"),
        latency_ms=payload.get("latency_ms"),
    )
    s.add(row)
    s.flush()
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "attempt_no": row.attempt_no,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def upsert_knowledge_document(s, payload: dict) -> tuple[dict, bool]:
    """按 `canonical_content_hash` 跨来源去重写入知识文档。

    返回 `(document, created)`；`created=False` 表示已存在同一知识。
    """
    existing = s.scalar(
        select(KnowledgeDocument).where(
            or_(
                KnowledgeDocument.canonical_content_hash == payload["canonical_content_hash"],
                and_(
                    KnowledgeDocument.source_type == payload["source_type"],
                    KnowledgeDocument.source_id == payload["source_id"],
                ),
            )
        )
    )
    values = {
        "source_type": payload["source_type"],
        "source_id": payload["source_id"],
        "source_url": payload.get("source_url") or "",
        "title": payload["title"],
        "summary": payload.get("summary"),
        "content": payload.get("content"),
        "normalized_text": payload["normalized_text"],
        "primary_topic": payload.get("primary_topic"),
        "topic_title": payload.get("topic_title"),
        "topics_json": payload.get("topics_json"),
        "topic_names_json": payload.get("topic_names_json"),
        "fund_theme_tags_json": payload.get("fund_theme_tags_json"),
        "fund_type_tags_json": payload.get("fund_type_tags_json"),
        "markets_json": payload.get("markets_json"),
        "asset_classes_json": payload.get("asset_classes_json"),
        "impact_direction": payload.get("impact_direction") or "unknown",
        "published_at": payload.get("published_at"),
        "effective_until": payload.get("effective_until"),
        "relevance_score": payload.get("relevance_score"),
        "classification_status": payload.get("classification_status") or "accepted",
        "index_status": payload.get("index_status") or "pending",
        "embedding_model": payload.get("embedding_model"),
        "embedding_version": payload.get("embedding_version"),
        "content_hash": payload["content_hash"],
        "canonical_content_hash": payload["canonical_content_hash"],
        "raw_reason": payload.get("raw_reason"),
        "supersedes_id": payload.get("supersedes_id"),
        "conflict_group_id": payload.get("conflict_group_id"),
        "conflict_status": payload.get("conflict_status") or "active",
    }
    if existing is None:
        row = KnowledgeDocument(**values)
        s.add(row)
        s.flush()
        return _knowledge_document_to_dict(row), True

    # 同一来源重复入库时刷新标准化内容；跨来源复用时保留主来源字段。
    if existing.source_type == values["source_type"] and existing.source_id == values["source_id"]:
        for key, value in values.items():
            setattr(existing, key, value)
        s.flush()
    return _knowledge_document_to_dict(existing), False


def upsert_knowledge_source_link(s, payload: dict) -> dict:
    """按 `(source_type, source_id)` 维护知识文档来源链接。"""
    row = s.scalar(
        select(KnowledgeSourceLink).where(
            KnowledgeSourceLink.source_type == payload["source_type"],
            KnowledgeSourceLink.source_id == payload["source_id"],
        )
    )
    values = {
        "document_id": int(payload["document_id"]),
        "source_type": payload["source_type"],
        "source_id": payload["source_id"],
        "source_url": payload.get("source_url"),
        "is_primary": bool(payload.get("is_primary", False)),
    }
    if row is None:
        row = KnowledgeSourceLink(**values)
        s.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    s.flush()
    return _source_link_to_dict(row)


def get_knowledge_document(s, document_id: int) -> dict | None:
    row = s.get(KnowledgeDocument, int(document_id))
    return _knowledge_document_to_dict(row) if row else None


def queue_status(
    s,
    *,
    source_type: str | None = None,
    classification_status: str | None = None,
    index_status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict:
    """返回知识准入 / 索引队列状态。

    rejected / failed 候选来自 classification state；accepted 且已写入
    document 的记录会附带 document/index 状态。
    """
    state_stmt = select(KnowledgeClassificationState)
    if source_type:
        state_stmt = state_stmt.where(KnowledgeClassificationState.source_type == source_type)
    if classification_status:
        state_stmt = state_stmt.where(KnowledgeClassificationState.status == classification_status)
    if since:
        state_stmt = state_stmt.where(KnowledgeClassificationState.created_at > since)
    state_rows = s.scalars(
        state_stmt.order_by(KnowledgeClassificationState.id.desc()).limit(max(1, int(limit)))
    ).all()

    by_classification: dict[str, int] = {}
    for status, count in s.execute(
        select(KnowledgeClassificationState.status, func.count())
        .group_by(KnowledgeClassificationState.status)
    ):
        by_classification[status] = int(count)

    doc_stmt = select(KnowledgeDocument)
    if index_status:
        doc_stmt = doc_stmt.where(KnowledgeDocument.index_status == index_status)
    by_index: dict[str, int] = {}
    for status, count in s.execute(
        select(KnowledgeDocument.index_status, func.count())
        .group_by(KnowledgeDocument.index_status)
    ):
        by_index[status] = int(count)
    docs_by_id = {
        row.id: row for row in s.scalars(doc_stmt).all()
    }

    items: list[dict] = []
    for row in state_rows:
        doc = docs_by_id.get(row.document_id) if row.document_id else None
        if index_status and doc is None:
            continue
        items.append({
            "document_id": doc.id if doc else None,
            "source_type": row.source_type,
            "source_id": row.source_id,
            "title": doc.title if doc else None,
            "classification_status": row.status,
            "index_status": doc.index_status if doc else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return {
        "counts": {
            "by_classification": by_classification,
            "by_index": by_index,
        },
        "items": items[:max(1, int(limit))],
    }

def _knowledge_fund_match_to_dict(row: KnowledgeFundMatch) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "fund_code": row.fund_code,
        "match_score": row.match_score,
        "matched_topics": _json_loads(row.matched_topics_json, []),
        "match_reason": row.match_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def upsert_knowledge_fund_match(s, payload: dict) -> dict:
    """按 `(document_id, fund_code)` upsert 知识-基金匹配关系。"""
    row = s.scalar(
        select(KnowledgeFundMatch).where(
            KnowledgeFundMatch.document_id == int(payload["document_id"]),
            KnowledgeFundMatch.fund_code == payload["fund_code"],
        )
    )
    values = {
        "document_id": int(payload["document_id"]),
        "fund_code": payload["fund_code"],
        "match_score": float(payload.get("match_score") or 0),
        "matched_topics_json": payload.get("matched_topics_json"),
        "match_reason": payload.get("match_reason"),
    }
    if row is None:
        row = KnowledgeFundMatch(**values)
        s.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    s.flush()
    return _knowledge_fund_match_to_dict(row)


__all__ = [
    "upsert_classification_state",
    "append_classification_log",
    "upsert_knowledge_document",
    "upsert_knowledge_source_link",
    "get_knowledge_document",
    "queue_status",
    "upsert_knowledge_fund_match",
    "upsert_cls_telegraph_item",
    "search_cls_telegraph_items",
    "get_cls_telegraph_sync_state",
    "update_cls_telegraph_sync_state",
]
