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
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
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
