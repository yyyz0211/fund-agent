from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from backend.services.knowledge import knowledge_schema
from backend.services.knowledge.knowledge_schema import TopicTag, KnowledgeClassificationResult


TTL_BOUNDS = {
    "cls_telegraph": (7, 30),
    "market_evidence": (7, 30),
    "announcement": (90, 365),
    "policy": (180, 730),
    "macro_data": (90, 365),
}

SOURCE_LABELS = {
    "cls_telegraph": "财联社电报",
    "market_evidence": "市场证据",
    "announcement": "公告",
    "policy": "政策",
    "macro_data": "宏观数据",
}


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _date_bucket(published_at: str | None) -> str:
    text = _clean_text(published_at)
    return text[:10] if len(text) >= 10 else ""


def canonical_content_hash(candidate: dict) -> str:
    """生成来源无关的内容指纹。

    这里故意不包含 `source_type` / `source_id`，否则同一条财联社内容
    从原始电报表和 evidence 精选层各入一次时无法去重。
    """
    title = _clean_text(candidate.get("title")).lower()
    body = _clean_text(
        candidate.get("content")
        or candidate.get("brief")
        or candidate.get("summary")
    ).lower()[:200]
    bucket = _date_bucket(candidate.get("published_at"))
    return _sha256_hex(f"{title}|{body}|{bucket}")[:32]


def content_hash(normalized_text: str) -> str:
    return _sha256_hex(_clean_text(normalized_text))[:32]


def topic_names(topics: list[TopicTag]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        name = _clean_text(topic.name)
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _parse_time(value: str | None) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def effective_until(
    published_at: str | None,
    source_type: str,
    ttl_days: int | None,
    default_ttl_days: int,
) -> tuple[str | None, int, bool]:
    """计算知识有效期，并按来源类型约束 TTL 上下限。"""
    effective_ttl = int(ttl_days or default_ttl_days)
    clamped = False
    bounds = TTL_BOUNDS.get(source_type)
    if bounds:
        lower, upper = bounds
        bounded = max(lower, min(upper, effective_ttl))
        clamped = bounded != effective_ttl
        effective_ttl = bounded

    base = _parse_time(published_at)
    if base is None:
        return None, effective_ttl, clamped
    return (
        (base + timedelta(days=effective_ttl)).strftime("%Y-%m-%d %H:%M:%S"),
        effective_ttl,
        clamped,
    )


def _join(values: list[str]) -> str:
    cleaned = [_clean_text(v) for v in values if _clean_text(v)]
    return " / ".join(cleaned)


def build_normalized_text(
    candidate: dict,
    classification: KnowledgeClassificationResult,
) -> str:
    """构造用于 embedding 的稳定文本模板。"""
    topics = topic_names(classification.topics)
    source_type = _clean_text(candidate.get("source_type"))
    source_label = SOURCE_LABELS.get(source_type, source_type or "未知来源")
    return "\n".join([
        f"标题：{_clean_text(candidate.get('title'))}",
        f"摘要：{_clean_text(classification.summary)}",
        f"正文：{_clean_text(candidate.get('content') or candidate.get('brief'))}",
        f"主题：{_join(topics)}",
        f"基金主题：{_join(classification.fund_theme_tags)}",
        f"基金类型：{_join(classification.fund_type_tags)}",
        f"市场：{_join(classification.markets)}",
        f"发布时间：{_clean_text(candidate.get('published_at'))}",
        f"来源：{source_label}",
    ])
