from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

from backend.db.init_db import PgVectorSchemaError, validate_pgvector_schema
from backend.exceptions import InputValidationError
from backend.services.knowledge.knowledge_vector import VectorHit, VectorItem


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".12g") for value in values) + "]"


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


class PgVectorStore:
    """绑定调用方 Session 的 pgvector 持久索引 adapter。"""

    def __init__(self, session, *, model: str, version: str, dimensions: int) -> None:
        self.session = session
        self.model = model
        self.version = version
        self.dimensions = int(dimensions)

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.dimensions:
            raise InputValidationError(
                "vector dimension mismatch: "
                f"expected={self.dimensions}, actual={len(vector)}",
                field="vector",
                details={"expected": self.dimensions, "actual": len(vector)},
            )

    def upsert(self, items: list[VectorItem | dict]) -> None:
        statement = text("""
            INSERT INTO knowledge_embeddings (
                document_id, embedding, embedding_model, embedding_version,
                content_hash, created_at, updated_at
            ) VALUES (
                :document_id, CAST(:embedding AS vector), :embedding_model,
                :embedding_version, :content_hash, NOW(), NOW()
            )
            ON CONFLICT (document_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                embedding_model = EXCLUDED.embedding_model,
                embedding_version = EXCLUDED.embedding_version,
                content_hash = EXCLUDED.content_hash,
                updated_at = NOW()
        """)
        for item in items:
            vector_item = item if isinstance(item, VectorItem) else VectorItem(**item)
            self._validate_vector(vector_item.vector)
            content_hash = str(vector_item.metadata.get("content_hash") or "")
            if not content_hash:
                raise InputValidationError(
                    "vector item metadata.content_hash is required",
                    field="metadata.content_hash",
                )
            self.session.execute(statement, {
                "document_id": int(vector_item.document_id),
                "embedding": _vector_literal(vector_item.vector),
                "embedding_model": self.model,
                "embedding_version": self.version,
                "content_hash": content_hash,
            })

    def search(
        self,
        query_vector: list[float],
        filters: dict,
        limit: int,
    ) -> list[VectorHit]:
        self._validate_vector(query_vector)
        where = [
            "kd.classification_status = 'accepted'",
            "(kd.effective_until IS NULL OR kd.effective_until >= :now_text)",
            "ke.embedding_model = :embedding_model",
            "ke.embedding_version = :embedding_version",
            "ke.content_hash = kd.content_hash",
        ]
        params: dict[str, Any] = {
            "query_vector": _vector_literal(query_vector),
            "now_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "embedding_model": self.model,
            "embedding_version": self.version,
            "limit": max(1, int(limit)),
        }
        if filters.get("source_type"):
            where.append("kd.source_type = :source_type")
            params["source_type"] = filters["source_type"]
        if filters.get("topic"):
            where.append("kd.topic_names_json LIKE :topic")
            params["topic"] = f'%"{filters["topic"]}"%'
        if filters.get("date_from"):
            where.append("kd.published_at >= :date_from")
            params["date_from"] = filters["date_from"]
        if filters.get("date_to"):
            where.append("kd.published_at <= :date_to")
            params["date_to"] = filters["date_to"]

        statement = text(f"""
            SELECT
                kd.id AS document_id,
                1 - (ke.embedding <=> CAST(:query_vector AS vector)) AS score,
                kd.source_type,
                kd.source_id,
                kd.primary_topic,
                kd.topic_names_json,
                kd.fund_theme_tags_json,
                kd.fund_type_tags_json,
                kd.published_at,
                kd.effective_until,
                kd.index_status
            FROM knowledge_embeddings AS ke
            JOIN knowledge_documents AS kd ON kd.id = ke.document_id
            WHERE {' AND '.join(where)}
            ORDER BY ke.embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
        """)
        rows = self.session.execute(statement, params).mappings().all()
        return [VectorHit(
            document_id=int(row["document_id"]),
            score=float(row["score"]),
            metadata={
                "source_type": row.get("source_type"),
                "source_id": row.get("source_id"),
                "primary_topic": row.get("primary_topic"),
                "topics": _json_list(row.get("topic_names_json")),
                "fund_theme_tags": _json_list(row.get("fund_theme_tags_json")),
                "fund_type_tags": _json_list(row.get("fund_type_tags_json")),
                "published_at": row.get("published_at"),
                "effective_until": row.get("effective_until"),
                "index_status": row.get("index_status"),
            },
        ) for row in rows]

    def delete(self, document_ids: list[int]) -> None:
        if not document_ids:
            return
        self.session.execute(
            text("DELETE FROM knowledge_embeddings WHERE document_id = ANY(:document_ids)"),
            {"document_ids": [int(value) for value in document_ids]},
        )


def build_vector_store(session, settings: Any):
    if not bool(getattr(settings, "knowledge_rag_enabled", True)):
        return None
    if getattr(settings, "knowledge_vector_backend", "auto") == "structured":
        return None
    model = getattr(settings, "knowledge_embedding_model", None)
    version = getattr(settings, "knowledge_embedding_version", None)
    dimensions = getattr(settings, "knowledge_embedding_dimensions", None)
    if not model or not version or not dimensions:
        return None
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    return PgVectorStore(
        session,
        model=str(model),
        version=str(version),
        dimensions=int(dimensions),
    )


def database_health_snapshot(engine) -> dict[str, Any]:
    """Check the local SQL connection without contacting external services."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "dialect": engine.dialect.name}
    except Exception as exc:
        return {
            "status": "degraded",
            "dialect": getattr(getattr(engine, "dialect", None), "name", "unknown"),
            "error": type(exc).__name__,
        }


def knowledge_vector_health_snapshot(engine, settings: Any) -> dict[str, Any]:
    """Describe local vector readiness without constructing an embedding client."""
    backend = str(getattr(settings, "knowledge_vector_backend", "auto"))
    if backend == "structured" or not bool(getattr(settings, "knowledge_rag_enabled", True)):
        return {"status": "disabled", "backend": backend}

    required = (
        "knowledge_embedding_base_url",
        "knowledge_embedding_api_key",
        "knowledge_embedding_model",
        "knowledge_embedding_version",
        "knowledge_embedding_dimensions",
    )
    missing = [name for name in required if not getattr(settings, name, None)]
    dialect = getattr(getattr(engine, "dialect", None), "name", "unknown")
    reason = None
    if missing:
        reason = "missing_embedding_config"
    elif dialect != "postgresql":
        reason = "postgresql_required"
    else:
        try:
            with engine.connect() as conn:
                validate_pgvector_schema(
                    conn,
                    int(getattr(settings, "knowledge_embedding_dimensions")),
                )
        except PgVectorSchemaError as exc:
            if exc.table_missing:
                reason = "knowledge_embeddings_missing"
            elif exc.missing_columns:
                reason = "incomplete_schema"
            elif exc.database_dimension is not None:
                reason = "dimension_mismatch"
            else:
                reason = "invalid_schema"
            schema_error = exc
        except Exception as exc:
            reason = f"schema_check_failed:{type(exc).__name__}"

    if reason is not None:
        status = "degraded" if backend == "pgvector" else "structured_fallback"
        snapshot: dict[str, Any] = {
            "status": status,
            "backend": backend,
            "dialect": dialect,
            "reason": reason,
        }
        if missing:
            snapshot["missing"] = missing
        if reason == "dimension_mismatch":
            snapshot["configured_dimensions"] = int(
                getattr(settings, "knowledge_embedding_dimensions")
            )
            snapshot["database_dimensions"] = schema_error.database_dimension
        if reason == "incomplete_schema":
            snapshot["missing_columns"] = sorted(schema_error.missing_columns)
        return snapshot
    return {"status": "ready", "backend": "pgvector", "dialect": dialect}
