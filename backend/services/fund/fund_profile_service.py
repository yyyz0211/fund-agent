"""基金体检画像缓存服务。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from backend.db import repository as repo
from backend.db.session import get_session
from backend.services.market import data_collector as dc


def _with_session(session):
    return session or get_session()


def refresh_profile(fund_code: str, session=None) -> dict:
    """刷新并持久化基金画像缓存。

    AkShare 字段是增强数据,允许局部缺失。collector 返回的
    `peer_candidates` 是 Python list,本层负责序列化为
    `FundProfile.peer_candidates_json`。
    """
    s = _with_session(session)
    owns = session is None
    try:
        payload = dc.fetch_fund_profile(fund_code)
        errors = payload.get("errors", [])
        missing_data = payload.get("missing_data", [])
        profile = repo.upsert_fund_profile(s, fund_code, {
            "scale": payload.get("scale"),
            "scale_date": payload.get("scale_date"),
            "peer_category": payload.get("peer_category"),
            "rank_total": payload.get("rank_total"),
            "rank_position": payload.get("rank_position"),
            "peer_candidates_json": json.dumps(
                payload.get("peer_candidates") or [],
                ensure_ascii=False,
            ),
            "top10_holding_pct": payload.get("top10_holding_pct"),
            "top_industry_pct": payload.get("top_industry_pct"),
            "manager_summary": payload.get("manager_summary"),
            "source": payload.get("source") or dc.SOURCE,
            "as_of": payload.get("as_of") or dc.today_str(),
            "raw_errors": json.dumps(errors, ensure_ascii=False),
        })
        return {
            "fund_code": fund_code,
            "profile": profile,
            "missing_data": missing_data,
            "errors": errors,
            "source": payload.get("source") or dc.SOURCE,
            "as_of": payload.get("as_of") or dc.today_str(),
        }
    finally:
        if owns:
            s.close()


def get_profile(fund_code: str, session=None) -> dict | None:
    """读取本地画像缓存,不触发外部刷新。"""
    s = _with_session(session)
    owns = session is None
    try:
        return repo.get_fund_profile(s, fund_code)
    finally:
        if owns:
            s.close()


def is_profile_fresh(fund_code: str, ttl_hours: int = 24, session=None) -> bool:
    """判断画像缓存是否在 TTL 内。"""
    profile = get_profile(fund_code, session=session)
    if not profile or not profile.get("updated_at"):
        return False
    try:
        updated_at = datetime.fromisoformat(profile["updated_at"])
    except ValueError:
        return False
    return datetime.now() - updated_at <= timedelta(hours=ttl_hours)
