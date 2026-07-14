"""Knowledge repository: 知识库、RAG 相关持久化."""
from __future__ import annotations

from backend.db.repository import (
    upsert_classification_state,
    append_classification_log,
    upsert_knowledge_document,
    upsert_knowledge_source_link,
    get_knowledge_document,
    queue_status,
    upsert_knowledge_fund_match,
    list_knowledge_reindex_jobs,
    upsert_cls_telegraph_item,
    search_cls_telegraph_items,
    get_cls_telegraph_sync_state,
    update_cls_telegraph_sync_state,
)

__all__ = [
    "upsert_classification_state",
    "append_classification_log",
    "upsert_knowledge_document",
    "upsert_knowledge_source_link",
    "get_knowledge_document",
    "queue_status",
    "upsert_knowledge_fund_match",
    "list_knowledge_reindex_jobs",
    "upsert_cls_telegraph_item",
    "search_cls_telegraph_items",
    "get_cls_telegraph_sync_state",
    "update_cls_telegraph_sync_state",
]
