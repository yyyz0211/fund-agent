from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import or_, select

from backend.db.repositories import knowledge as knowledge_repo
from backend.db.models import FundWatchlistProfile, KnowledgeDocument, KnowledgeFundMatch
from backend.db.session_scope import session_scope


def _as_set(values) -> set[str]:
    return {str(value).strip() for value in (values or []) if str(value).strip()}


def calculate_match_score(document: dict, profile: dict) -> tuple[float, list[str], str]:
    """计算知识文档与单只自选基金画像的匹配分。"""
    doc_topics = _as_set(document.get("topic_names"))
    doc_theme_tags = _as_set(document.get("fund_theme_tags"))
    doc_type_tags = _as_set(document.get("fund_type_tags"))
    profile_tags = _as_set(profile.get("theme_tags"))
    primary_topic = str(document.get("primary_topic") or "").strip()
    fund_type = str(profile.get("fund_type") or "").strip()

    matched_topics = sorted((doc_topics | doc_theme_tags) & profile_tags)
    topic_hit = bool(matched_topics)
    score = 0.0
    priority = profile.get("priority")
    if priority == "holding" and topic_hit:
        score += 0.40
    elif priority == "focus" and topic_hit:
        score += 0.20

    if primary_topic and primary_topic in profile_tags:
        score += 0.15
        if primary_topic not in matched_topics:
            matched_topics.append(primary_topic)

    if doc_theme_tags & profile_tags:
        score += 0.15

    if fund_type and fund_type in doc_type_tags:
        score += 0.05

    if topic_hit:
        score += min(1.0, float(profile.get("holding_weight") or 0)) * 0.05

    score = min(1.0, round(score, 4))
    if score <= 0:
        return 0.0, [], ""

    fund_name = profile.get("fund_name") or profile.get("fund_code") or "自选基金"
    label = "持仓基金" if priority == "holding" else "关注基金" if priority == "focus" else "自选基金"
    reason = f"命中{label}“{fund_name}”的主题：{'、'.join(matched_topics)}。"
    return score, matched_topics, reason


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _document_dict(row: KnowledgeDocument) -> dict:
    return {
        "id": row.id,
        "primary_topic": row.primary_topic,
        "topic_names": _json_list(row.topic_names_json),
        "fund_theme_tags": _json_list(row.fund_theme_tags_json),
        "fund_type_tags": _json_list(row.fund_type_tags_json),
    }


def _profile_dict(row: FundWatchlistProfile) -> dict:
    return {
        "fund_code": row.fund_code,
        "fund_name": row.fund_name,
        "priority": row.priority,
        "holding_weight": row.holding_weight or 0,
        "theme_tags": _json_list(row.theme_tags_json),
        "fund_type": row.fund_type,
    }


def refresh_knowledge_fund_matches(*, session=None, document_limit: int | None = None) -> dict:
    """刷新知识文档与当前基金自选池画像的匹配关系。

    调用方注入 session 时,只在调用方事务内 flush;否则为本次刷新开
    `session_scope()` short-tx。该函数内部不调用 commit/rollback/close。
    """
    if session is not None:
        return _compute_and_upsert_matches(
            session=session, document_limit=document_limit,
        )
    with session_scope() as s:
        return _compute_and_upsert_matches(
            session=s, document_limit=document_limit,
        )


def _compute_and_upsert_matches(*, session, document_limit: int | None) -> dict:
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.classification_status == "accepted",
        or_(
            KnowledgeDocument.effective_until.is_(None),
            KnowledgeDocument.effective_until >= now_text,
        ),
    )
    if document_limit:
        stmt = stmt.limit(max(1, int(document_limit)))
    docs = session.scalars(stmt).all()
    profiles = session.scalars(select(FundWatchlistProfile)).all()
    written = 0
    target_keys: set[tuple[int, str]] = set()
    for doc in docs:
        doc_dict = _document_dict(doc)
        for profile in profiles:
            score, topics, reason = calculate_match_score(doc_dict, _profile_dict(profile))
            if score <= 0:
                continue
            knowledge_repo.upsert_knowledge_fund_match(session, {
                "document_id": doc.id,
                "fund_code": profile.fund_code,
                "match_score": score,
                "matched_topics_json": json.dumps(topics, ensure_ascii=False),
                "match_reason": reason,
            })
            target_keys.add((int(doc.id), profile.fund_code))
            written += 1
    existing_matches = session.scalars(select(KnowledgeFundMatch)).all()
    deleted = 0
    for match in existing_matches:
        if (int(match.document_id), match.fund_code) not in target_keys:
            session.delete(match)
            deleted += 1
    session.flush()
    return {"matches_written": written, "matches_deleted": deleted}
