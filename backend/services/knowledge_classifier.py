from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from langchain_openai import ChatOpenAI

from backend.config.settings import get_settings
from backend.services.knowledge_schema import (
    KnowledgeCandidate,
    KnowledgeClassificationResult,
)


@dataclass
class ClassificationOutcome:
    status: str
    result: KnowledgeClassificationResult | None
    raw_response: str | None
    error_message: str | None
    latency_ms: int


def build_classification_prompt(
    candidate: KnowledgeCandidate,
    *,
    prompt_version: str,
) -> str:
    """构造知识准入 prompt。

    输出要求压成 strict JSON，是为了后续入库、索引和审计都能走确定性
    schema 校验，避免模型自由文本污染知识库状态。
    """
    return f"""
你是 fund-agent 的市场知识库准入分类器，prompt_version={prompt_version}。

任务：判断下面信息是否与股票、基金、ETF、指数、宏观、产业链或投资风险相关。
只做信息整理，不要输出买入、卖出、持有、加仓、减仓、申购、赎回等建议。

必须只返回 strict JSON object，不要 markdown，不要解释性前后缀。

候选信息：
source_type: {candidate.source_type}
source_id: {candidate.source_id}
source_url: {candidate.source_url or ""}
title: {candidate.title}
brief: {candidate.brief or ""}
content: {candidate.content or ""}
cls_subjects: {candidate.cls_subjects}
symbols: {candidate.symbols}
published_at: {candidate.published_at or ""}

JSON schema:
{{
  "should_index": true,
  "relevance_score": 0.0,
  "summary": "一句话摘要",
  "primary_topic": "主主题",
  "topics": [
    {{"name": "主题名", "weight": "high", "source": "cls_subject"}}
  ],
  "topic_title": "主题小标题",
  "fund_theme_tags": ["科技成长"],
  "fund_type_tags": ["混合型"],
  "markets": ["A股"],
  "asset_classes": ["基金"],
  "impact_direction": "positive|negative|neutral|mixed|unknown",
  "effective_ttl_days": 14,
  "reason": "入库或拒绝原因",
  "confidence": "high|medium|low"
}}
""".strip()


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_classification_response(raw: str) -> KnowledgeClassificationResult:
    text = _strip_json_fence(raw)
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError("strict JSON object required")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"strict JSON parse failed: {exc}") from exc
    try:
        return KnowledgeClassificationResult.model_validate(payload)
    except Exception as exc:
        raise ValueError(f"strict JSON schema validation failed: {exc}") from exc


def _build_default_model(settings: Any | None = None):
    settings = settings or get_settings()
    api_key = settings.deepseek_api_key
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for knowledge classification")
    model_name = (
        settings.knowledge_classification_model
        or settings.briefing_llm_model
        or settings.deepseek_model
    )
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=settings.deepseek_base_url,
        temperature=0,
    )


def classify_candidate(
    candidate: dict | KnowledgeCandidate,
    *,
    model=None,
    settings: Any | None = None,
) -> ClassificationOutcome:
    started = time.monotonic()
    raw_response: str | None = None
    try:
        parsed_candidate = (
            candidate if isinstance(candidate, KnowledgeCandidate)
            else KnowledgeCandidate.model_validate(candidate)
        )
        settings = settings or get_settings()
        prompt = build_classification_prompt(
            parsed_candidate,
            prompt_version=settings.knowledge_classification_prompt_version,
        )
        active_model = model or _build_default_model(settings)
        response = active_model.invoke(prompt)
        raw_response = str(getattr(response, "content", response))
        result = parse_classification_response(raw_response)
        status = "accepted" if result.should_index else "rejected"
        return ClassificationOutcome(
            status=status,
            result=result,
            raw_response=raw_response,
            error_message=None,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 - 分类管线需要把失败转为可记录状态
        return ClassificationOutcome(
            status="failed",
            result=None,
            raw_response=raw_response,
            error_message=str(exc),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
