# 基金自选池 RAG 知识库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first shippable RAG knowledge base slice: LLM-filtered market knowledge ingestion, semantic/structured retrieval, and fund-watchlist profile matching.

**Architecture:** Keep source-of-truth rows in existing source tables (`cls_telegraph_items`, `market_evidence`) and store only accepted, normalized knowledge in new knowledge tables. Use injected LLM, embedding, and vector-store adapters so tests stay offline and the vector backend can move from local Qdrant/Chroma to pgvector later. Phase 1 builds ingestion, classification, indexing, and search; Phase 2 adds fund-watchlist profiles and fund-aware reranking.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, SQLite, Pydantic, LangChain OpenAI-compatible model wrapper, optional Qdrant local adapter, pytest.

## Global Constraints

- This plan covers spec Phase 1 + Phase 2 only. Daily briefing integration, lifecycle governance UI, and long-text chunk expansion require separate follow-up plans.
- Raw source rows are never deleted by RAG ingestion.
- No stock watchlist or individual stock holding system is introduced.
- No fund real-position lookthrough is required.
- LLM classification must return strict JSON and must be fully mockable in tests.
- Tests must not call live LLM, embedding, network, or vector services.
- `fund_code` filter returns HTTP 400 until fund matching is enabled in Task 8.
- Vector backend access must go through `VectorStoreAdapter`; service code must not depend directly on Qdrant or Chroma.
- RAG output must include source and published time and must not produce buy/sell/hold/add/reduce-position advice.

---

## File Structure

Create:

- `backend/services/knowledge_schema.py` — Pydantic schemas and enum constants for classification, topics, search results, and queue status.
- `backend/services/knowledge_normalizer.py` — deterministic text cleanup, canonical hash, TTL, and normalized-text builders.
- `backend/services/knowledge_classifier.py` — LLM classification wrapper with strict JSON parsing and retry-safe result objects.
- `backend/services/knowledge_ingestion_service.py` — source candidate loading and accepted/rejected classification orchestration.
- `backend/services/knowledge_vector.py` — embedding provider and vector-store adapter interfaces plus offline test adapters.
- `backend/services/knowledge_search_service.py` — hybrid search, scoring, fallback modes, and queue/status helpers.
- `backend/services/knowledge_fund_profile_service.py` — fund-watchlist profile generation.
- `backend/services/knowledge_match_service.py` — knowledge-to-fund match scoring and refresh.
- `backend/api/routes/knowledge.py` — `/api/knowledge/*` routes.
- `backend/tests/test_knowledge_models.py`
- `backend/tests/test_knowledge_normalizer.py`
- `backend/tests/test_knowledge_classifier.py`
- `backend/tests/test_knowledge_ingestion.py`
- `backend/tests/test_knowledge_vector.py`
- `backend/tests/test_knowledge_search_route.py`
- `backend/tests/test_knowledge_fund_profiles.py`
- `backend/tests/test_knowledge_fund_matches.py`

Modify:

- `backend/db/models.py` — add knowledge tables.
- `backend/db/repository.py` — add persistence and query helpers.
- `backend/db/init_db.py` — ensure SQLite create/alter path handles new tables and indexes.
- `backend/config/settings.py` — add knowledge settings.
- `backend/.env.example` and `.env.example` — document knowledge settings.
- `backend/api/app.py` — register knowledge router.
- `backend/scheduler.py` — add optional knowledge ingestion/index interval jobs.
- `backend/tools/market_tools.py` — expose `search_market_knowledge`.
- `backend/tests/test_settings.py`
- `backend/tests/test_scheduler.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_api_app.py`

---

### Task 1: Knowledge Schema And Repository Foundation

**Files:**
- Modify: `backend/db/models.py`
- Modify: `backend/db/repository.py`
- Modify: `backend/db/init_db.py`
- Modify: `backend/config/settings.py`
- Modify: `backend/.env.example`
- Modify: `.env.example`
- Create: `backend/tests/test_knowledge_models.py`
- Modify: `backend/tests/test_settings.py`

**Interfaces:**
- Produces ORM tables: `KnowledgeDocument`, `KnowledgeSourceLink`, `KnowledgeClassificationState`, `KnowledgeClassificationLog`, `KnowledgeChunk`, `FundWatchlistProfile`, `KnowledgeFundMatch`, `KnowledgeRetrievalLog`.
- Produces repository functions:
  - `upsert_classification_state(session, payload: dict) -> dict`
  - `append_classification_log(session, payload: dict) -> dict`
  - `upsert_knowledge_document(session, payload: dict) -> tuple[dict, bool]`
  - `upsert_knowledge_source_link(session, payload: dict) -> dict`
  - `get_knowledge_document(session, document_id: int) -> dict | None`
  - `queue_status(session, *, source_type: str | None, classification_status: str | None, index_status: str | None, since: str | None, limit: int) -> dict`
- Consumes existing SQLAlchemy `Base`, `init_db()`, `get_settings()`.

- [ ] **Step 1: Write failing table-creation tests**

Add to `backend/tests/test_knowledge_models.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from backend.db.init_db import init_db
from backend.db.models import (
    KnowledgeClassificationLog,
    KnowledgeClassificationState,
    KnowledgeDocument,
    KnowledgeSourceLink,
)


def test_init_db_creates_knowledge_tables():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    tables = set(inspect(eng).get_table_names())

    assert {
        "knowledge_documents",
        "knowledge_source_links",
        "knowledge_classification_state",
        "knowledge_classification_log",
        "knowledge_chunks",
        "fund_watchlist_profiles",
        "knowledge_fund_matches",
        "knowledge_retrieval_logs",
    }.issubset(tables)


def test_canonical_content_hash_dedupes_across_sources():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    with Session(eng) as s:
        doc = KnowledgeDocument(
            source_type="cls_telegraph",
            source_id="cls-1",
            source_url="https://www.cls.cn/detail/1",
            title="AI news",
            summary="summary",
            content="content",
            normalized_text="标题：AI news\n摘要：summary",
            primary_topic="人工智能",
            topic_title="人工智能",
            topics_json="[]",
            topic_names_json='["人工智能"]',
            fund_theme_tags_json='["科技成长"]',
            fund_type_tags_json='["混合型"]',
            markets_json='["A股"]',
            asset_classes_json='["基金"]',
            impact_direction="unknown",
            published_at="2026-07-09 10:00:00",
            effective_until="2026-07-23 10:00:00",
            relevance_score=0.8,
            classification_status="accepted",
            index_status="pending",
            embedding_model=None,
            content_hash="full-hash-1",
            canonical_content_hash="canonical-1",
            raw_reason="accepted",
        )
        s.add(doc)
        s.flush()
        s.add(KnowledgeSourceLink(
            document_id=doc.id,
            source_type="cls_telegraph",
            source_id="cls-1",
            source_url="https://www.cls.cn/detail/1",
            is_primary=True,
        ))
        s.add(KnowledgeSourceLink(
            document_id=doc.id,
            source_type="market_evidence",
            source_id="ev-1",
            source_url="https://www.cls.cn/detail/1",
            is_primary=False,
        ))
        s.commit()

        links = s.scalars(select(KnowledgeSourceLink).where(
            KnowledgeSourceLink.document_id == doc.id
        )).all()
        assert {link.source_type for link in links} == {"cls_telegraph", "market_evidence"}


def test_classification_log_allows_multiple_attempts():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    with Session(eng) as s:
        s.add(KnowledgeClassificationState(
            source_type="cls_telegraph",
            source_id="cls-1",
            canonical_content_hash="canonical-1",
            latest_attempt_no=2,
            should_index=True,
            relevance_score=0.8,
            prompt_version="v1",
            status="accepted",
            reason="accepted",
        ))
        s.add(KnowledgeClassificationLog(
            source_type="cls_telegraph",
            source_id="cls-1",
            canonical_content_hash="canonical-1",
            attempt_no=1,
            prompt_version="v1",
            status="failed",
            should_index=False,
            relevance_score=None,
            reason=None,
            raw_response_json=None,
            error_message="bad json",
            latency_ms=10,
        ))
        s.add(KnowledgeClassificationLog(
            source_type="cls_telegraph",
            source_id="cls-1",
            canonical_content_hash="canonical-1",
            attempt_no=2,
            prompt_version="v1",
            status="accepted",
            should_index=True,
            relevance_score=0.8,
            reason="accepted",
            raw_response_json='{"should_index": true}',
            error_message=None,
            latency_ms=12,
        ))
        s.commit()

        assert s.scalar(select(KnowledgeClassificationState).where(
            KnowledgeClassificationState.source_id == "cls-1"
        )).latest_attempt_no == 2
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_models.py -q
```

Expected: fails with import errors for missing ORM classes.

- [ ] **Step 3: Add ORM models**

Add the knowledge models to `backend/db/models.py`. Use `String` columns for JSON payloads, matching existing project style:

```python
class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_knowledge_source_identity"),
        UniqueConstraint("content_hash", name="uq_knowledge_content_hash"),
        UniqueConstraint("canonical_content_hash", name="uq_knowledge_canonical_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    source_url: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(String)
    normalized_text: Mapped[str] = mapped_column(String)
    primary_topic: Mapped[str | None] = mapped_column(String(64), index=True)
    topic_title: Mapped[str | None] = mapped_column(String(128))
    topics_json: Mapped[str | None] = mapped_column(String)
    topic_names_json: Mapped[str | None] = mapped_column(String)
    fund_theme_tags_json: Mapped[str | None] = mapped_column(String)
    fund_type_tags_json: Mapped[str | None] = mapped_column(String)
    markets_json: Mapped[str | None] = mapped_column(String)
    asset_classes_json: Mapped[str | None] = mapped_column(String)
    impact_direction: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    published_at: Mapped[str | None] = mapped_column(String, index=True)
    effective_until: Mapped[str | None] = mapped_column(String, index=True)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    classification_status: Mapped[str] = mapped_column(String(16), default="accepted", index=True)
    index_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    embedding_version: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    canonical_content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_reason: Mapped[str | None] = mapped_column(String)
    supersedes_id: Mapped[int | None] = mapped_column(Integer)
    conflict_group_id: Mapped[str | None] = mapped_column(String(64))
    conflict_status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

Add the remaining concrete ORM classes in the same file with these fields:

- `KnowledgeSourceLink`: `id`, `document_id`, `source_type`, `source_id`, `source_url`, `is_primary`, `created_at`.
- `KnowledgeClassificationState`: `id`, `source_type`, `source_id`, `canonical_content_hash`, `latest_attempt_no`, `should_index`, `relevance_score`, `prompt_version`, `status`, `reason`, `document_id`, `last_error_message`, `created_at`, `updated_at`.
- `KnowledgeClassificationLog`: `id`, `source_type`, `source_id`, `canonical_content_hash`, `attempt_no`, `prompt_version`, `status`, `should_index`, `relevance_score`, `reason`, `raw_response_json`, `error_message`, `latency_ms`, `created_at`.
- `KnowledgeChunk`: `id`, `document_id`, `chunk_index`, `chunk_text`, `content_hash`, `index_status`, `created_at`, `updated_at`.
- `FundWatchlistProfile`: `fund_code`, `fund_name`, `priority`, `holding_weight`, `fund_type`, `peer_category`, `theme_tags_json`, `risk_tags_json`, `match_basis_json`, `manual_overrides_json`, `profile_status`, `created_at`, `updated_at`.
- `KnowledgeFundMatch`: `id`, `document_id`, `fund_code`, `match_score`, `matched_topics_json`, `match_reason`, `created_at`.
- `KnowledgeRetrievalLog`: `id`, `query`, `filters_json`, `retrieval_mode`, `result_count`, `latency_ms`, `created_at`.

Use exact unique constraints from the spec:

```python
UniqueConstraint("source_type", "source_id", name="uq_knowledge_source_link_source")
UniqueConstraint("document_id", "source_type", "source_id", name="uq_knowledge_source_link_doc_source")
UniqueConstraint("source_type", "source_id", name="uq_knowledge_classification_state_source")
UniqueConstraint("source_type", "source_id", "prompt_version", "attempt_no", name="uq_knowledge_classification_log_attempt")
UniqueConstraint("document_id", "fund_code", name="uq_knowledge_fund_match_doc_fund")
```

- [ ] **Step 4: Add settings**

Add to `backend/config/settings.py`:

```python
    knowledge_rag_enabled: bool = True
    knowledge_vector_backend: str = "qdrant"
    knowledge_embedding_model: str | None = None
    knowledge_embedding_version: str | None = None
    knowledge_classification_model: str | None = None
    knowledge_classification_prompt_version: str = "v1"
    knowledge_classification_batch_size: int = 10
    knowledge_index_batch_size: int = 20
    knowledge_default_ttl_days: int = 14
    knowledge_include_pending_fallback: bool = True
    knowledge_max_search_limit: int = 50
    knowledge_max_queue_status_limit: int = 200
    scheduler_knowledge_enabled: bool = True
    scheduler_knowledge_interval_minutes: int = 6
```

Add environment examples to both env files:

```text
KNOWLEDGE_RAG_ENABLED=true
KNOWLEDGE_VECTOR_BACKEND=qdrant
KNOWLEDGE_EMBEDDING_MODEL=
KNOWLEDGE_EMBEDDING_VERSION=
KNOWLEDGE_CLASSIFICATION_MODEL=
KNOWLEDGE_CLASSIFICATION_PROMPT_VERSION=v1
KNOWLEDGE_CLASSIFICATION_BATCH_SIZE=10
KNOWLEDGE_INDEX_BATCH_SIZE=20
KNOWLEDGE_DEFAULT_TTL_DAYS=14
KNOWLEDGE_INCLUDE_PENDING_FALLBACK=true
KNOWLEDGE_MAX_SEARCH_LIMIT=50
KNOWLEDGE_MAX_QUEUE_STATUS_LIMIT=200
SCHEDULER_KNOWLEDGE_ENABLED=true
SCHEDULER_KNOWLEDGE_INTERVAL_MINUTES=6
```

- [ ] **Step 5: Add repository helpers**

Add projection helpers and upserts to `backend/db/repository.py`. Use JSON string parsing style from `_evidence_to_dict`.

Required functions:

- `upsert_classification_state(s, payload: dict) -> dict`
- `append_classification_log(s, payload: dict) -> dict`
- `upsert_knowledge_document(s, payload: dict) -> tuple[dict, bool]`
- `upsert_knowledge_source_link(s, payload: dict) -> dict`
- `get_knowledge_document(s, document_id: int) -> dict | None`
- `queue_status(s, *, source_type: str | None = None, classification_status: str | None = None, index_status: str | None = None, since: str | None = None, limit: int = 50) -> dict`

`upsert_knowledge_document` must use `canonical_content_hash` as the cross-source dedupe key. If an existing document is found by `canonical_content_hash`, update source-link data but return `(existing_dict, False)`.

- [ ] **Step 6: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_models.py backend/tests/test_settings.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add backend/db/models.py backend/db/repository.py backend/db/init_db.py backend/config/settings.py backend/.env.example .env.example backend/tests/test_knowledge_models.py backend/tests/test_settings.py
git commit -m "feat: add knowledge base schema"
```

---

### Task 2: Knowledge Normalization And Classification Schemas

**Files:**
- Create: `backend/services/knowledge_schema.py`
- Create: `backend/services/knowledge_normalizer.py`
- Create: `backend/tests/test_knowledge_normalizer.py`

**Interfaces:**
- Produces:
  - `TopicTag`
  - `KnowledgeClassificationResult`
  - `KnowledgeCandidate`
  - `KnowledgeSearchItem`
  - `canonical_content_hash(candidate: dict) -> str`
  - `content_hash(normalized_text: str) -> str`
  - `topic_names(topics: list[TopicTag]) -> list[str]`
  - `effective_until(published_at: str | None, source_type: str, ttl_days: int | None, default_ttl_days: int) -> tuple[str | None, int, bool]`
  - `build_normalized_text(candidate: dict, classification: KnowledgeClassificationResult) -> str`
- Consumes no database or network.

- [ ] **Step 1: Write failing normalization tests**

Add to `backend/tests/test_knowledge_normalizer.py`:

```python
from __future__ import annotations

from backend.services.knowledge_normalizer import (
    build_normalized_text,
    canonical_content_hash,
    effective_until,
    topic_names,
)
from backend.services.knowledge_schema import KnowledgeClassificationResult, TopicTag


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
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_normalizer.py -q
```

Expected: fails with missing modules.

- [ ] **Step 3: Add schemas**

Create `backend/services/knowledge_schema.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TopicWeight = Literal["high", "medium", "low"]
TopicSource = Literal["cls_subject", "llm"]
ImpactDirection = Literal["positive", "negative", "neutral", "mixed", "unknown"]
Confidence = Literal["high", "medium", "low"]
RetrievalMode = Literal["hybrid", "vector_only", "structured_fallback"]


class TopicTag(BaseModel):
    name: str
    weight: TopicWeight = "medium"
    source: TopicSource = "llm"


class KnowledgeCandidate(BaseModel):
    source_type: str
    source_id: str
    source_url: str | None = None
    title: str
    brief: str | None = None
    content: str | None = None
    cls_subjects: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    published_at: str | None = None


class KnowledgeClassificationResult(BaseModel):
    should_index: bool
    relevance_score: float | None = None
    summary: str | None = None
    primary_topic: str | None = None
    topics: list[TopicTag] = Field(default_factory=list)
    topic_title: str | None = None
    fund_theme_tags: list[str] = Field(default_factory=list)
    fund_type_tags: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)
    asset_classes: list[str] = Field(default_factory=list)
    impact_direction: ImpactDirection = "unknown"
    effective_ttl_days: int | None = None
    reason: str
    confidence: Confidence = "medium"
```

- [ ] **Step 4: Add deterministic normalizer functions**

Create `backend/services/knowledge_normalizer.py` with these behaviors:

```python
def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())
```

Use `hashlib.sha256` for hashes. `canonical_content_hash` must not include `source_type` or `source_id`; use normalized title plus first 200 characters of content/brief and a date bucket from `published_at[:10]`.

TTL bounds:

```python
TTL_BOUNDS = {
    "cls_telegraph": (7, 30),
    "market_evidence": (7, 30),
    "announcement": (90, 365),
    "policy": (180, 730),
    "macro_data": (90, 365),
}
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_normalizer.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/knowledge_schema.py backend/services/knowledge_normalizer.py backend/tests/test_knowledge_normalizer.py
git commit -m "feat: add knowledge normalization helpers"
```

---

### Task 3: LLM Classification Service

**Files:**
- Create: `backend/services/knowledge_classifier.py`
- Create: `backend/tests/test_knowledge_classifier.py`

**Interfaces:**
- Consumes `KnowledgeCandidate`, `KnowledgeClassificationResult`.
- Produces:
  - `ClassificationOutcome`
  - `build_classification_prompt(candidate: KnowledgeCandidate, *, prompt_version: str) -> str`
  - `parse_classification_response(raw: str) -> KnowledgeClassificationResult`
  - `classify_candidate(candidate: dict, *, model=None, settings=None) -> ClassificationOutcome`

- [ ] **Step 1: Write failing classifier tests**

Add to `backend/tests/test_knowledge_classifier.py`:

```python
from __future__ import annotations

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


def test_parse_classification_response_accepts_strict_json():
    result = parse_classification_response("""
    {
      "should_index": true,
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
      "confidence": "high"
    }
    """)

    assert result.should_index is True
    assert result.topics[0].name == "人工智能"


def test_parse_classification_response_rejects_non_json():
    with pytest.raises(ValueError, match="strict JSON"):
        parse_classification_response("这条新闻和市场有关")


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
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_classifier.py -q
```

Expected: fails with missing classifier module.

- [ ] **Step 3: Implement classifier**

Create `backend/services/knowledge_classifier.py`. The service must:

- Build a prompt that asks for strict JSON only.
- Parse only JSON objects.
- Strip markdown fences if the model returns ```json fences.
- Return `ClassificationOutcome(status="failed", error_message="<parse or model error>")` instead of raising for model/parse failures.

Use this outcome type:

```python
from dataclasses import dataclass


@dataclass
class ClassificationOutcome:
    status: str
    result: KnowledgeClassificationResult | None
    raw_response: str | None
    error_message: str | None
    latency_ms: int
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_classifier.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/knowledge_classifier.py backend/tests/test_knowledge_classifier.py
git commit -m "feat: add knowledge classifier service"
```

---

### Task 4: Knowledge Ingestion From CLS And Market Evidence

**Files:**
- Create: `backend/services/knowledge_ingestion_service.py`
- Create: `backend/tests/test_knowledge_ingestion.py`

**Interfaces:**
- Consumes repository helpers from Task 1 and classifier from Task 3.
- Produces:
  - `candidate_from_cls(row: dict) -> dict`
  - `candidate_from_market_evidence(row: dict) -> dict`
  - `ingest_candidates(candidates: list[dict], *, classifier, session) -> dict`
  - `ingest_recent_knowledge(*, limit: int = 50, session=None, classifier=None) -> dict`

- [ ] **Step 1: Write failing ingestion tests**

Add to `backend/tests/test_knowledge_ingestion.py`:

```python
from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.db.init_db import init_db
from backend.db.models import KnowledgeClassificationState, KnowledgeDocument
from backend.services.knowledge_ingestion_service import ingest_candidates
from backend.services.knowledge_schema import KnowledgeClassificationResult, TopicTag


class StaticClassifier:
    def __init__(self, result):
        self.result = result

    def classify(self, candidate):
        from backend.services.knowledge_classifier import ClassificationOutcome
        return ClassificationOutcome(
            status="accepted" if self.result.should_index else "rejected",
            result=self.result,
            raw_response=self.result.model_dump_json(),
            error_message=None,
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


def test_ingest_candidates_creates_document_for_accepted_item():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    candidate = {
        "source_type": "cls_telegraph",
        "source_id": "cls-1",
        "source_url": "https://www.cls.cn/detail/1",
        "title": "AI消息",
        "content": "AI消息",
        "published_at": "2026-07-09 10:00:00",
    }

    with Session(eng) as s:
        result = ingest_candidates([candidate], classifier=StaticClassifier(accepted_result()), session=s)

        assert result["accepted"] == 1
        doc = s.scalar(select(KnowledgeDocument))
        assert doc.title == "AI消息"
        assert doc.index_status == "pending"
        state = s.scalar(select(KnowledgeClassificationState))
        assert state.status == "accepted"
        assert state.document_id == doc.id


def test_ingest_candidates_logs_rejected_without_document():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    rejected = accepted_result().model_copy(update={"should_index": False, "reason": "not market related"})

    with Session(eng) as s:
        result = ingest_candidates([{
            "source_type": "cls_telegraph",
            "source_id": "cls-2",
            "title": "无关消息",
            "content": "无关消息",
        }], classifier=StaticClassifier(rejected), session=s)

        assert result["rejected"] == 1
        assert s.scalar(select(KnowledgeDocument)) is None
        assert s.scalar(select(KnowledgeClassificationState)).status == "rejected"


def test_ingest_candidates_dedupes_cross_source_items():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    candidates = [
        {"source_type": "cls_telegraph", "source_id": "cls-1", "source_url": "u1", "title": "AI消息", "content": "同一内容", "published_at": "2026-07-09 10:00:00"},
        {"source_type": "market_evidence", "source_id": "ev-1", "source_url": "u1", "title": "AI消息", "content": "同一内容", "published_at": "2026-07-09 10:02:00"},
    ]

    with Session(eng) as s:
        result = ingest_candidates(candidates, classifier=StaticClassifier(accepted_result()), session=s)

        assert result["accepted"] == 2
        assert result["documents_created"] == 1
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_ingestion.py -q
```

Expected: fails with missing ingestion service.

- [ ] **Step 3: Implement ingestion service**

Create `backend/services/knowledge_ingestion_service.py`.

Rules:

- One candidate produces exactly one `KnowledgeClassificationState`.
- Accepted candidates create or reuse a `KnowledgeDocument`.
- Reused documents get an additional `KnowledgeSourceLink`.
- Rejected candidates do not create `KnowledgeDocument`.
- Failed classifier outcomes create state/log records with `status="failed"`.

Service result shape:

```python
{
    "processed": 0,
    "accepted": 0,
    "rejected": 0,
    "failed": 0,
    "documents_created": 0,
    "documents_reused": 0,
}
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_ingestion.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/knowledge_ingestion_service.py backend/tests/test_knowledge_ingestion.py
git commit -m "feat: ingest classified market knowledge"
```

---

### Task 5: Embedding And Vector Index Adapter

**Files:**
- Create: `backend/services/knowledge_vector.py`
- Create: `backend/tests/test_knowledge_vector.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Consumes pending `KnowledgeDocument` rows.
- Produces:
  - `EmbeddingProvider.embed(texts: list[str]) -> list[list[float]]`
  - `VectorStoreAdapter.upsert(items: list[VectorItem]) -> None`
  - `VectorStoreAdapter.search(query_vector: list[float], filters: dict, limit: int) -> list[VectorHit]`
  - `VectorStoreAdapter.delete(document_ids: list[int]) -> None`
  - `index_pending_documents(*, session, embedding_provider, vector_store, limit: int) -> dict`

- [ ] **Step 1: Write failing vector tests**

Add to `backend/tests/test_knowledge_vector.py`:

```python
from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.db.init_db import init_db
from backend.db.models import KnowledgeDocument
from backend.services.knowledge_vector import (
    DeterministicEmbeddingProvider,
    InMemoryVectorStore,
    index_pending_documents,
)


def add_doc(session):
    doc = KnowledgeDocument(
        source_type="cls_telegraph",
        source_id="cls-1",
        source_url="u1",
        title="AI消息",
        summary="summary",
        content="content",
        normalized_text="标题：AI消息\n摘要：summary",
        primary_topic="人工智能",
        topic_title="人工智能",
        topics_json="[]",
        topic_names_json='["人工智能"]',
        fund_theme_tags_json='["科技成长"]',
        fund_type_tags_json='["混合型"]',
        markets_json='["A股"]',
        asset_classes_json='["基金"]',
        impact_direction="negative",
        published_at="2026-07-09 10:00:00",
        effective_until="2026-07-23 10:00:00",
        relevance_score=0.8,
        classification_status="accepted",
        index_status="pending",
        embedding_model=None,
        embedding_version=None,
        content_hash="hash-1",
        canonical_content_hash="canonical-1",
        raw_reason="accepted",
    )
    session.add(doc)
    session.commit()
    return doc.id


def test_index_pending_documents_marks_indexed():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    store = InMemoryVectorStore()

    with Session(eng) as s:
        doc_id = add_doc(s)
        result = index_pending_documents(
            session=s,
            embedding_provider=DeterministicEmbeddingProvider(),
            vector_store=store,
            limit=10,
        )

        assert result["indexed"] == 1
        assert s.get(KnowledgeDocument, doc_id).index_status == "indexed"
        assert store.items[doc_id].metadata["topics"] == ["人工智能"]


def test_vector_search_respects_metadata_filter():
    store = InMemoryVectorStore()
    provider = DeterministicEmbeddingProvider()
    query = provider.embed(["人工智能"])[0]
    store.upsert([
        {
            "document_id": 1,
            "text": "人工智能",
            "vector": provider.embed(["人工智能"])[0],
            "metadata": {"topics": ["人工智能"]},
        },
        {
            "document_id": 2,
            "text": "消费",
            "vector": provider.embed(["消费"])[0],
            "metadata": {"topics": ["消费"]},
        },
    ])

    hits = store.search(query, {"topics": "人工智能"}, limit=5)

    assert [hit.document_id for hit in hits] == [1]
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_vector.py -q
```

Expected: fails with missing vector module.

- [ ] **Step 3: Add vector abstractions and offline adapters**

Create `backend/services/knowledge_vector.py`.

Required test adapters:

```python
class DeterministicEmbeddingProvider:
    model = "deterministic-test"
    version = "v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([round(byte / 255, 6) for byte in digest[:16]])
        return vectors


class InMemoryVectorStore:
    def __init__(self):
        self.items: dict[int, VectorItem] = {}
```

Use a deterministic hash-based vector for tests. Use cosine similarity in `InMemoryVectorStore.search`.

- [ ] **Step 4: Add optional Qdrant dependency**

Add to `backend/requirements.txt`:

```text
qdrant-client>=1.9,<2.0
```

The Qdrant implementation must be lazy-imported inside the adapter factory so tests and non-vector code do not import it unless `knowledge_vector_backend == "qdrant"`.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_vector.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/knowledge_vector.py backend/tests/test_knowledge_vector.py backend/requirements.txt
git commit -m "feat: add knowledge vector indexing"
```

---

### Task 6: Knowledge Search API And Queue Status

**Files:**
- Create: `backend/services/knowledge_search_service.py`
- Create: `backend/api/routes/knowledge.py`
- Modify: `backend/api/app.py`
- Create: `backend/tests/test_knowledge_search_route.py`
- Modify: `backend/tests/test_api_app.py`

**Interfaces:**
- Consumes vector adapter from Task 5 and repository helpers from Task 1.
- Produces:
  - `search_knowledge(query: str, *, fund_code=None, topic=None, source_type=None, date_from=None, date_to=None, limit=10, include_pending=False, session=None, vector_store=None, embedding_provider=None, fund_matching_enabled=False) -> dict`
- `get_queue_status(source_type: str | None = None, classification_status: str | None = None, index_status: str | None = None, since: str | None = None, limit: int = 50, session=None) -> dict`
  - FastAPI routes under `/api/knowledge`.

- [ ] **Step 1: Write failing route tests**

Add to `backend/tests/test_knowledge_search_route.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.app import app


def test_knowledge_search_rejects_fund_code_before_fund_matching(monkeypatch):
    client = TestClient(app)

    response = client.get("/api/knowledge/search", params={
        "query": "人工智能",
        "fund_code": "000000",
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "fund_code filter requires knowledge fund matching"


def test_knowledge_queue_status_route_shape(monkeypatch):
    from backend.api.routes import knowledge as route

    monkeypatch.setattr(route.knowledge_search_service, "get_queue_status", lambda **kwargs: {
        "counts": {"by_classification": {}, "by_index": {}},
        "items": [],
    })
    client = TestClient(app)

    response = client.get("/api/knowledge/queue-status")

    assert response.status_code == 200
    assert response.json()["counts"] == {"by_classification": {}, "by_index": {}}
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_search_route.py -q
```

Expected: fails because the route is not registered.

- [ ] **Step 3: Implement search service**

Create `backend/services/knowledge_search_service.py`.

Phase 1 behavior:

- If `fund_code` is provided and `fund_matching_enabled=False`, raise `ValueError("fund_code filter requires knowledge fund matching")`.
- If vector store search raises, return `retrieval_mode="structured_fallback"` and include `coverage_warning`.
- If vector store is absent, use structured fallback over `knowledge_documents` by title, summary, topic names, and metadata.
- Always write a `knowledge_retrieval_logs` row with query, filters, mode, result count, and latency.

Use score clamp from the spec:

```python
final_score = min(1.0, semantic_score * 0.30 + freshness_score * 0.20 + fund_match_score * 0.30 + relevance_score * 0.20 + direct_match_bonus)
```

- [ ] **Step 4: Implement FastAPI routes**

Create `backend/api/routes/knowledge.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.services import knowledge_search_service

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/search")
def search_knowledge(
    query: str = Query(default=""),
    fund_code: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    include_pending: bool = Query(default=False),
    session: Session = Depends(get_session),
):
    try:
        return knowledge_search_service.search_knowledge(
            query=query,
            fund_code=fund_code,
            topic=topic,
            source_type=source_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            include_pending=include_pending,
            session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/queue-status")
def queue_status(
    source_type: str | None = Query(default=None),
    classification_status: str | None = Query(default=None),
    index_status: str | None = Query(default=None),
    since: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    return knowledge_search_service.get_queue_status(
        source_type=source_type,
        classification_status=classification_status,
        index_status=index_status,
        since=since,
        limit=limit,
        session=session,
    )
```

Register the router in `backend/api/app.py`:

```python
from backend.api.routes import knowledge as knowledge_routes
app.include_router(knowledge_routes.router)
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_search_route.py backend/tests/test_api_app.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/knowledge_search_service.py backend/api/routes/knowledge.py backend/api/app.py backend/tests/test_knowledge_search_route.py backend/tests/test_api_app.py
git commit -m "feat: expose knowledge search api"
```

---

### Task 7: Fund Watchlist Profile Generation

**Files:**
- Create: `backend/services/knowledge_fund_profile_service.py`
- Create: `backend/tests/test_knowledge_fund_profiles.py`

**Interfaces:**
- Consumes `Watchlist`, `Fund`, `FundProfile`.
- Produces:
  - `infer_theme_tags(fund_name: str, fund_type: str | None, peer_category: str | None, note: str | None) -> tuple[list[str], list[str]]`
  - `refresh_fund_watchlist_profiles(*, session) -> dict`
  - repository helper `upsert_fund_watchlist_profile(session, payload: dict) -> dict`

- [ ] **Step 1: Write failing profile tests**

Add to `backend/tests/test_knowledge_fund_profiles.py`:

```python
from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.db.init_db import init_db
from backend.db.models import Fund, FundProfile, FundWatchlistProfile, Watchlist
from backend.services.knowledge_fund_profile_service import (
    infer_theme_tags,
    refresh_fund_watchlist_profiles,
)


def test_infer_theme_tags_from_fund_name_and_peer_category():
    tags, basis = infer_theme_tags(
        "人工智能主题混合",
        "混合型",
        "科技成长",
        None,
    )

    assert "人工智能" in tags
    assert "科技成长" in tags
    assert "fund_name" in basis
    assert "peer_category" in basis


def test_refresh_profiles_uses_holding_weight():
    eng = create_engine("sqlite:///:memory:")
    init_db(eng)
    with Session(eng) as s:
        s.add_all([
            Fund(fund_code="000001", fund_name="人工智能主题混合", fund_type="混合型"),
            FundProfile(fund_code="000001", peer_category="科技成长"),
            Watchlist(fund_code="000001", fund_name="人工智能主题混合", is_holding=True, holding_amount=3000.0),
            Fund(fund_code="000002", fund_name="消费主题混合", fund_type="混合型"),
            Watchlist(fund_code="000002", fund_name="消费主题混合", is_holding=True, holding_amount=1000.0),
        ])
        s.commit()

        result = refresh_fund_watchlist_profiles(session=s)

        assert result["profiles_written"] == 2
        profile = s.scalar(select(FundWatchlistProfile).where(
            FundWatchlistProfile.fund_code == "000001"
        ))
        assert profile.priority == "holding"
        assert profile.holding_weight == 0.75
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_fund_profiles.py -q
```

Expected: fails with missing service/helper.

- [ ] **Step 3: Add manual override field to model if missing**

Ensure `FundWatchlistProfile` includes:

```python
manual_overrides_json: Mapped[str | None] = mapped_column(String)
```

Automatic refresh must merge manual overrides after inferred tags:

```python
final_theme_tags = unique(inferred_theme_tags + manual_override_theme_tags)
```

- [ ] **Step 4: Implement deterministic profile service**

Use a compact theme map aligned with existing `module_briefing._THEME_KEYWORD_MAP`:

```python
THEME_KEYWORDS = [
    (("AI", "人工智能", "算力", "半导体", "芯片"), "人工智能"),
    (("新能源", "电池", "光伏", "储能", "锂电"), "新能源"),
    (("医药", "创新药", "医疗", "中药", "CXO"), "医药"),
    (("消费", "白酒", "食品", "饮料", "家电"), "消费"),
    (("军工", "航空航天", "国防"), "军工"),
    (("港股", "恒生", "中概", "海外"), "港股/海外"),
]
```

Set `priority`:

```python
priority = "holding" if row.is_holding else "focus" if row.is_focus else "watching"
```

Normalize holding weights across `is_holding=True` rows with positive `holding_amount`.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_fund_profiles.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/db/models.py backend/db/repository.py backend/services/knowledge_fund_profile_service.py backend/tests/test_knowledge_fund_profiles.py
git commit -m "feat: build fund watchlist profiles"
```

---

### Task 8: Knowledge-Fund Matching And Fund-Aware Search

**Files:**
- Create: `backend/services/knowledge_match_service.py`
- Create: `backend/tests/test_knowledge_fund_matches.py`
- Modify: `backend/services/knowledge_search_service.py`
- Modify: `backend/tests/test_knowledge_search_route.py`

**Interfaces:**
- Consumes `knowledge_documents` and `fund_watchlist_profiles`.
- Produces:
  - `calculate_match_score(document: dict, profile: dict) -> tuple[float, list[str], str]`
  - `refresh_knowledge_fund_matches(*, session, document_limit: int | None = None) -> dict`
  - `search_knowledge(query: str, *, fund_code: str | None = None, fund_matching_enabled: bool = True, session=None, **filters) -> dict` with `fund_code` support.

- [ ] **Step 1: Write failing match tests**

Add to `backend/tests/test_knowledge_fund_matches.py`:

```python
from __future__ import annotations

from backend.services.knowledge_match_service import calculate_match_score


def test_calculate_match_score_prioritizes_holding_primary_topic():
    document = {
        "primary_topic": "人工智能",
        "topic_names": ["人工智能", "半导体"],
        "fund_theme_tags": ["科技成长", "人工智能"],
        "fund_type_tags": ["混合型"],
    }
    profile = {
        "fund_code": "000001",
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
        {"primary_topic": "人工智能", "topic_names": ["人工智能"], "fund_theme_tags": ["科技成长"], "fund_type_tags": []},
        {"fund_code": "000002", "priority": "watching", "holding_weight": 0, "theme_tags": ["消费"], "fund_type": "债券型"},
    )

    assert score == 0
    assert topics == []
    assert reason == ""
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_fund_matches.py -q
```

Expected: fails with missing match service.

- [ ] **Step 3: Implement match scoring**

Use spec weights:

```python
score = 0.0
if profile["priority"] == "holding" and topic_hit:
    score += 0.40
elif profile["priority"] == "focus" and topic_hit:
    score += 0.20
if document["primary_topic"] in profile["theme_tags"]:
    score += 0.15
if set(document["fund_theme_tags"]) & set(profile["theme_tags"]):
    score += 0.15
if document["fund_type_tags"] and profile["fund_type"] in document["fund_type_tags"]:
    score += 0.05
score += min(1.0, float(profile.get("holding_weight") or 0)) * 0.05
score = min(1.0, round(score, 4))
```

Weak matches below `0.10` must still be stored but should receive lower search weight.

- [ ] **Step 4: Update search service for fund matching**

When `fund_matching_enabled=True`:

- `fund_code` filters to documents with a `knowledge_fund_matches` row for that fund.
- `fund_match_score` uses the stored match score.
- Each item includes `matched_funds`, `matched_topics`, and `match_reason`.

Update route tests to assert `fund_code` no longer returns 400 when the service is called with fund matching enabled through monkeypatch.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_knowledge_fund_matches.py backend/tests/test_knowledge_search_route.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/knowledge_match_service.py backend/services/knowledge_search_service.py backend/tests/test_knowledge_fund_matches.py backend/tests/test_knowledge_search_route.py
git commit -m "feat: rank knowledge by fund profile matches"
```

---

### Task 9: Scheduler And Manual Processing Hooks

**Files:**
- Modify: `backend/scheduler.py`
- Modify: `backend/api/routes/knowledge.py`
- Modify: `backend/tests/test_scheduler.py`
- Modify: `backend/tests/test_knowledge_search_route.py`

**Interfaces:**
- Consumes `knowledge_ingestion_service.ingest_recent_knowledge`, `knowledge_vector.index_pending_documents`, `knowledge_fund_profile_service.refresh_fund_watchlist_profiles`, `knowledge_match_service.refresh_knowledge_fund_matches`.
- Produces:
  - `POST /api/knowledge/reindex`
  - scheduled job id `knowledge_ingest_index`

- [ ] **Step 1: Write failing scheduler and reindex tests**

Add to `backend/tests/test_knowledge_search_route.py`:

```python
def test_reindex_requires_local_trigger():
    from fastapi.testclient import TestClient
    from backend.api.app import app

    response = TestClient(app).post("/api/knowledge/reindex")

    assert response.status_code == 403
    assert response.json()["detail"] == "Requires X-Local-Trigger header"
```

Add to `backend/tests/test_scheduler.py`:

```python
def test_scheduler_registers_knowledge_job(monkeypatch):
    from backend import scheduler as sched

    jobs = []

    class FakeScheduler:
        def add_job(self, func, trigger, id, **kwargs):
            jobs.append(id)
        def start(self):
            pass

    monkeypatch.setattr(sched, "_scheduler", None)
    monkeypatch.setattr(sched, "_build_scheduler", lambda: FakeScheduler())

    started = sched.start_scheduler(enabled=True)

    assert started is not None
    assert "knowledge_ingest_index" in jobs
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_scheduler.py backend/tests/test_knowledge_search_route.py -q
```

Expected: fails because route/job does not exist.

- [ ] **Step 3: Add reindex endpoint**

Add to `backend/api/routes/knowledge.py`:

```python
@router.post("/reindex")
def reindex_knowledge(_trigger: str | None = Header(default=None, alias="X-Local-Trigger"), session: Session = Depends(get_session)):
    if _trigger is None:
        raise HTTPException(status_code=403, detail="Requires X-Local-Trigger header")
    return knowledge_search_service.run_knowledge_pipeline_once(session=session)
```

`run_knowledge_pipeline_once` should call ingestion, indexing, profile refresh, and match refresh in order and return per-step counts.

- [ ] **Step 4: Register scheduler job**

In `backend/scheduler.py`, when `settings.scheduler_knowledge_enabled` is true:

```python
from backend.services import knowledge_search_service

scheduler.add_job(
    lambda: knowledge_search_service.run_knowledge_pipeline_once(),
    trigger=_interval_trigger(int(getattr(settings, "scheduler_knowledge_interval_minutes", 6)), timezone),
    id="knowledge_ingest_index",
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300,
    jitter=60,
)
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_scheduler.py backend/tests/test_knowledge_search_route.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/scheduler.py backend/api/routes/knowledge.py backend/services/knowledge_search_service.py backend/tests/test_scheduler.py backend/tests/test_knowledge_search_route.py
git commit -m "feat: schedule knowledge ingestion pipeline"
```

---

### Task 10: LangChain Tool And Regression Verification

**Files:**
- Modify: `backend/tools/market_tools.py`
- Modify: `backend/tests/test_tools.py`
- Modify: `backend/tests/test_api_market.py`

**Interfaces:**
- Consumes `/api/knowledge/search` service layer through direct service calls.
- Produces LangChain tool `search_market_knowledge`.

- [ ] **Step 1: Write failing tool test**

Add to `backend/tests/test_tools.py`:

```python
def test_search_market_knowledge_tool_forwards_filters(monkeypatch):
    from backend.tools import market_tools

    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return {"count": 0, "retrieval_mode": "structured_fallback", "items": []}

    monkeypatch.setattr(market_tools.knowledge_search_service, "search_knowledge", fake_search)

    result = market_tools.search_market_knowledge.invoke({
        "query": "人工智能",
        "fund_code": "000001",
        "topic": "人工智能",
        "limit": 5,
    })

    assert result["count"] == 0
    assert captured["query"] == "人工智能"
    assert captured["fund_code"] == "000001"
    assert captured["topic"] == "人工智能"
    assert captured["limit"] == 5
```

- [ ] **Step 2: Run failing test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_tools.py::test_search_market_knowledge_tool_forwards_filters -q
```

Expected: fails because tool does not exist.

- [ ] **Step 3: Add tool**

In `backend/tools/market_tools.py`, import the service:

```python
from backend.services import knowledge_search_service
```

Add:

```python
@tool
def search_market_knowledge(query: str, fund_code: str = "", topic: str = "", limit: int = 8) -> dict:
    """检索市场知识库，返回带来源、发布时间、匹配原因的证据。只用于信息整理，不输出投资建议。"""
    return knowledge_search_service.search_knowledge(
        query=query,
        fund_code=fund_code or None,
        topic=topic or None,
        limit=limit,
        fund_matching_enabled=True,
    )
```

Add the tool to `MARKET_TOOLS`.

- [ ] **Step 4: Run tool and backend regression tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_tools.py backend/tests/test_knowledge_models.py backend/tests/test_knowledge_normalizer.py backend/tests/test_knowledge_classifier.py backend/tests/test_knowledge_ingestion.py backend/tests/test_knowledge_vector.py backend/tests/test_knowledge_search_route.py backend/tests/test_knowledge_fund_profiles.py backend/tests/test_knowledge_fund_matches.py -q
```

Expected: pass.

- [ ] **Step 5: Run full backend suite**

Run:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/tools/market_tools.py backend/tests/test_tools.py
git commit -m "feat: expose market knowledge search tool"
```

---

## Final Verification

Run:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: all backend tests pass.

Run a local API smoke after starting the backend:

```bash
curl "http://127.0.0.1:8000/api/knowledge/queue-status"
curl "http://127.0.0.1:8000/api/knowledge/search?query=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD&limit=5"
```

Expected:

- `queue-status` returns `counts` and `items`.
- `search` returns `count`, `retrieval_mode`, and `items`.
- If no knowledge has been ingested, `count` may be `0`; response shape must still be stable.

## Spec Coverage

- LLM 入库准入：Tasks 2-4.
- 财联社 `subjects/tag` 主题化：Tasks 2 and 4.
- 来源无关跨来源去重：Tasks 1 and 4.
- `knowledge_documents` / `knowledge_source_links` / classification state/log：Task 1.
- 增量写入和索引状态：Tasks 4-5.
- metadata filter 和结构化兜底：Task 6.
- 基金自选池画像：Task 7.
- `knowledge_fund_matches` 和 fund-aware ranking：Task 8.
- 调度和手动处理入口：Task 9.
- QA/Agent Tool 接入：Task 10.
- Phase 3 每日简报接入、Phase 4 生命周期治理面板、Phase 5 长文本 chunk 启用：out of this execution plan by design; each needs a separate plan after Phase 1+2 verification.
