from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select

from backend.db.models import KnowledgeDocument


@dataclass
class VectorItem:
    document_id: int
    text: str
    vector: list[float]
    metadata: dict


@dataclass
class VectorHit:
    document_id: int
    score: float
    metadata: dict


class EmbeddingProvider(Protocol):
    model: str
    version: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class VectorStoreAdapter(Protocol):
    def upsert(self, items: list[VectorItem | dict]) -> None:
        ...

    def search(self, query_vector: list[float], filters: dict, limit: int) -> list[VectorHit]:
        ...

    def delete(self, document_ids: list[int]) -> None:
        ...


class DeterministicEmbeddingProvider:
    """测试用 embedding provider。

    使用文本 hash 生成固定向量，保证单测离线、稳定、无需真实 embedding
    模型或外部服务。
    """
    model = "deterministic-test"
    version = "v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([round(byte / 255, 6) for byte in digest[:16]])
        return vectors


class InMemoryVectorStore:
    """测试和降级场景使用的内存向量库。"""

    def __init__(self):
        self.items: dict[int, VectorItem] = {}

    def upsert(self, items: list[VectorItem | dict]) -> None:
        for item in items:
            vector_item = item if isinstance(item, VectorItem) else VectorItem(**item)
            self.items[int(vector_item.document_id)] = vector_item

    def search(self, query_vector: list[float], filters: dict, limit: int) -> list[VectorHit]:
        hits: list[VectorHit] = []
        for item in self.items.values():
            if not _metadata_matches(item.metadata, filters):
                continue
            hits.append(VectorHit(
                document_id=item.document_id,
                score=_cosine_similarity(query_vector, item.vector),
                metadata=item.metadata,
            ))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:max(1, int(limit))]

    def delete(self, document_ids: list[int]) -> None:
        for document_id in document_ids:
            self.items.pop(int(document_id), None)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    norm_a = math.sqrt(sum(a[i] * a[i] for i in range(n)))
    norm_b = math.sqrt(sum(b[i] * b[i] for i in range(n)))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return round(dot / (norm_a * norm_b), 6)


def _metadata_matches(metadata: dict, filters: dict) -> bool:
    for key, expected in (filters or {}).items():
        if expected in (None, ""):
            continue
        actual = metadata.get(key)
        if isinstance(actual, list):
            if expected not in actual:
                return False
        elif actual != expected:
            return False
    return True


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _metadata_for_document(doc: KnowledgeDocument) -> dict:
    return {
        "document_id": doc.id,
        "source_type": doc.source_type,
        "source_id": doc.source_id,
        "primary_topic": doc.primary_topic,
        "topics": _json_list(doc.topic_names_json),
        "fund_theme_tags": _json_list(doc.fund_theme_tags_json),
        "fund_type_tags": _json_list(doc.fund_type_tags_json),
        "published_at": doc.published_at,
        "effective_until": doc.effective_until,
        "index_status": "indexed",
        "content_hash": doc.content_hash,
    }


def index_pending_documents(
    *,
    session,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStoreAdapter,
    limit: int,
) -> dict:
    """把 pending knowledge document 写入向量索引并更新状态。"""
    docs = session.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.index_status == "pending")
        .order_by(KnowledgeDocument.id)
        .limit(max(1, int(limit)))
    ).all()
    result = {"processed": len(docs), "indexed": 0, "failed": 0}
    if not docs:
        return result

    try:
        vectors = embedding_provider.embed([doc.normalized_text for doc in docs])
        items = [
            VectorItem(
                document_id=doc.id,
                text=doc.normalized_text,
                vector=vectors[idx],
                metadata=_metadata_for_document(doc),
            )
            for idx, doc in enumerate(docs)
        ]
        vector_store.upsert(items)
    except Exception:
        for doc in docs:
            doc.index_status = "failed"
        session.flush()
        result["failed"] = len(docs)
        return result

    for doc in docs:
        doc.index_status = "indexed"
        doc.embedding_model = embedding_provider.model
        doc.embedding_version = embedding_provider.version
    session.flush()
    result["indexed"] = len(docs)
    return result
