from __future__ import annotations

import json

from sqlalchemy import select

from backend.db.repositories import fund as fund_repo
from backend.db.models import Fund, FundProfile, FundWatchlistProfile, Watchlist
from backend.db.session_scope import session_scope


THEME_KEYWORDS = [
    (("AI", "人工智能", "算力", "半导体", "芯片"), "人工智能"),
    (("新能源", "电池", "光伏", "储能", "锂电"), "新能源"),
    (("医药", "创新药", "医疗", "中药", "CXO"), "医药"),
    (("消费", "白酒", "食品", "饮料", "家电"), "消费"),
    (("军工", "航空航天", "国防"), "军工"),
    (("港股", "恒生", "中概", "海外"), "港股/海外"),
]


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def infer_theme_tags(
    fund_name: str,
    fund_type: str | None,
    peer_category: str | None,
    note: str | None,
) -> tuple[list[str], list[str]]:
    """从基金名称、类型、同类分类和备注推导基金主题标签。"""
    text = " ".join([
        str(fund_name or ""),
        str(fund_type or ""),
        str(peer_category or ""),
        str(note or ""),
    ])
    tags: list[str] = []
    basis: list[str] = []

    for keywords, theme in THEME_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            tags.append(theme)
            if any(keyword in str(fund_name or "") for keyword in keywords):
                basis.append("fund_name")
            if any(keyword in str(note or "") for keyword in keywords):
                basis.append("note")

    if peer_category:
        tags.append(peer_category)
        basis.append("peer_category")
    if fund_type:
        basis.append("fund_type")

    return _unique(tags), _unique(basis)


def _priority(row: Watchlist) -> str:
    if row.is_holding:
        return "holding"
    if row.is_focus:
        return "focus"
    return "watching"


def _holding_weights(rows: list[Watchlist]) -> dict[str, float]:
    amounts = {
        row.fund_code: float(row.holding_amount or 0)
        for row in rows
        if row.is_holding and float(row.holding_amount or 0) > 0
    }
    total = sum(amounts.values())
    if total <= 0:
        return {}
    return {code: round(amount / total, 6) for code, amount in amounts.items()}


def refresh_fund_watchlist_profiles(*, session=None) -> dict:
    """刷新当前自选池基金画像。

    调用方注入 session 时,只在调用方事务内 flush;否则为本次刷新开
    `session_scope()` short-tx。该函数内部不调用 commit/rollback/close。
    """
    if session is not None:
        return _recompute_profiles(session=session)
    with session_scope() as s:
        return _recompute_profiles(session=s)


def _recompute_profiles(*, session) -> dict:
    watchlist_rows = session.scalars(select(Watchlist).order_by(Watchlist.id)).all()
    weights = _holding_weights(watchlist_rows)
    target_codes = {row.fund_code for row in watchlist_rows}
    written = 0
    for row in watchlist_rows:
        fund = session.get(Fund, row.fund_code)
        profile = session.get(FundProfile, row.fund_code)
        fund_name = row.fund_name or (fund.fund_name if fund else None) or row.fund_code
        fund_type = fund.fund_type if fund else None
        peer_category = profile.peer_category if profile else None
        theme_tags, match_basis = infer_theme_tags(
            fund_name,
            fund_type,
            peer_category,
            row.note,
        )
        fund_repo.upsert_fund_watchlist_profile(session, {
            "fund_code": row.fund_code,
            "fund_name": fund_name,
            "priority": _priority(row),
            "holding_weight": weights.get(row.fund_code, 0.0),
            "fund_type": fund_type,
            "peer_category": peer_category,
            "theme_tags_json": json.dumps(theme_tags, ensure_ascii=False),
            "risk_tags_json": json.dumps([], ensure_ascii=False),
            "match_basis_json": json.dumps(match_basis, ensure_ascii=False),
            "profile_status": "ready" if theme_tags else "partial",
        })
        written += 1
    stale_profiles = session.scalars(select(FundWatchlistProfile)).all()
    deleted = 0
    for profile in stale_profiles:
        if profile.fund_code not in target_codes:
            session.delete(profile)
            deleted += 1
    session.flush()
    return {"profiles_written": written, "profiles_deleted": deleted}
