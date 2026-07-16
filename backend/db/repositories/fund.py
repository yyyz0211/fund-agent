"""Fund repository: 基金净值、画像、交易相关持久化。"""
from __future__ import annotations

from sqlalchemy import and_, func, select

from backend.db.models import (
    Fund,
    FundNav,
    FundProfile,
    FundTransaction,
    FundWatchlistProfile,
)
from backend.db.repositories._serialization import json_loads as _json_loads


def _profile_to_dict(p: FundProfile) -> dict:
    """FundProfile 的可序列化投影。"""
    return {
        "fund_code": p.fund_code,
        "scale": p.scale,
        "scale_date": p.scale_date,
        "peer_category": p.peer_category,
        "rank_total": p.rank_total,
        "rank_position": p.rank_position,
        "peer_candidates_json": p.peer_candidates_json,
        "top10_holding_pct": p.top10_holding_pct,
        "top_industry_pct": p.top_industry_pct,
        "manager_summary": p.manager_summary,
        "source": p.source,
        "as_of": p.as_of,
        "raw_errors": p.raw_errors,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }

def upsert_fund(session, fund: dict) -> None:
    """按 `fund_code` 插入或更新 `Fund`。

    更新时,除 `fund_code` 之外的每个字段都会被覆盖到已有行上。
    要更新哪些字段由调用方决定(只放想改的列即可)。
    """
    obj = session.get(Fund, fund["fund_code"])
    if obj is None:
        session.add(Fund(**fund))
    else:
        for k, v in fund.items():
            if k != "fund_code":
                setattr(obj, k, v)
    session.flush()


_FUND_PROFILE_FIELDS = {
    "scale",
    "scale_date",
    "peer_category",
    "rank_total",
    "rank_position",
    "peer_candidates_json",
    "top10_holding_pct",
    "top_industry_pct",
    "manager_summary",
    "source",
    "as_of",
    "raw_errors",
}


def upsert_fund_profile(session, fund_code: str, attrs: dict) -> dict:
    """按 fund_code upsert 画像缓存,只更新传入字段。"""
    data = {k: v for k, v in (attrs or {}).items() if k in _FUND_PROFILE_FIELDS}
    obj = session.get(FundProfile, fund_code)
    if obj is None:
        obj = FundProfile(fund_code=fund_code, **data)
        session.add(obj)
    else:
        for k, v in data.items():
            setattr(obj, k, v)
    session.flush()
    return _profile_to_dict(obj)


def get_fund_profile(session, fund_code: str) -> dict | None:
    """读取单只基金画像缓存;不存在返回 None。"""
    obj = session.get(FundProfile, fund_code)
    return _profile_to_dict(obj) if obj else None


def upsert_navs(session, fund_code: str, rows: list[dict]) -> int:
    """把基金净值批量 upsert。

    只插入 `(fund_code, nav_date)` 还不存在的那部分。返回值是真正
    新插入的行数 — 重复日期会被跳过,而不是覆盖(同一天重新拉取
    是 no-op)。
    """
    existing = set(session.scalars(
        select(FundNav.nav_date).where(FundNav.fund_code == fund_code)).all())
    inserted = 0
    for r in rows:
        if r["nav_date"] in existing:
            continue
        session.add(FundNav(fund_code=fund_code, **r))
        inserted += 1
    session.flush()
    return inserted


def get_accumulated_navs(session, fund_code: str) -> list[float]:
    """取该基金的累计净值序列,按日期从早到晚排列。

    `None` 值会被丢掉(来源未公布累计净值的行)—— 下游指标函数
    要求一段连续的数值序列。
    """
    rows = session.scalars(
        select(FundNav.accumulated_nav)
        .where(FundNav.fund_code == fund_code)
        .order_by(FundNav.nav_date)).all()
    return [float(x) for x in rows if x is not None]


def _tx_to_dict(tx: FundTransaction) -> dict:
    """FundTransaction 的序列化函数。"""
    return {
        "id": tx.id,
        "fund_code": tx.fund_code,
        "tx_date": tx.tx_date,
        "tx_seq": tx.tx_seq,
        "kind": tx.kind,
        "amount": tx.amount,
        "nav": tx.nav,
        "share": tx.share,
        "fee": tx.fee,
        "note": tx.note,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
    }


def list_transactions(session, fund_code: str) -> list[dict]:
    """按 fund_code 列出所有交易,按日期早到晚、再按 seq 升序。"""
    rows = session.scalars(
        select(FundTransaction)
        .where(FundTransaction.fund_code == fund_code)
        .order_by(FundTransaction.tx_date, FundTransaction.tx_seq, FundTransaction.id)
    ).all()
    return [_tx_to_dict(t) for t in rows]


def count_transactions(session, fund_code: str) -> int:
    """单只基金的交易条数,供 watchlist 列表返回 `transaction_count` 用。"""
    return session.scalar(
        select(func.count())
        .select_from(FundTransaction)
        .where(FundTransaction.fund_code == fund_code)
    ) or 0


def count_transactions_for_funds(session, fund_codes: list[str]) -> dict[str, int]:
    """批量返回每只基金的交易条数;未出现的 fund_code 默认 0。"""
    codes = list(dict.fromkeys(c for c in fund_codes if c))
    counts = {code: 0 for code in codes}
    if not codes:
        return counts
    rows = session.execute(
        select(FundTransaction.fund_code, func.count())
        .where(FundTransaction.fund_code.in_(codes))
        .group_by(FundTransaction.fund_code)
    ).all()
    for code, count in rows:
        counts[str(code)] = int(count or 0)
    return counts


def _nav_to_dict(row: FundNav) -> dict:
    """FundNav 最新点序列化函数。"""
    return {
        "fund_code": row.fund_code,
        "nav_date": row.nav_date,
        "accumulated_nav": row.accumulated_nav,
        "daily_return": row.daily_return,
        "source": row.source,
        "as_of": row.source_updated_at,
    }


def get_latest_navs_for_funds(session, fund_codes: list[str]) -> dict[str, dict]:
    """批量取每只基金最新 NAV,无 NAV 的基金不出现在结果中。"""
    codes = list(dict.fromkeys(c for c in fund_codes if c))
    if not codes:
        return {}
    latest_dates = (
        select(
            FundNav.fund_code.label("fund_code"),
            func.max(FundNav.nav_date).label("nav_date"),
        )
        .where(FundNav.fund_code.in_(codes))
        .group_by(FundNav.fund_code)
        .subquery()
    )
    rows = session.scalars(
        select(FundNav)
        .join(
            latest_dates,
            and_(
                FundNav.fund_code == latest_dates.c.fund_code,
                FundNav.nav_date == latest_dates.c.nav_date,
            ),
        )
    ).all()
    return {row.fund_code: _nav_to_dict(row) for row in rows}


def get_nav_by_date(session, fund_code: str, nav_date: str) -> dict | None:
    """按基金代码和净值日精确读取 NAV。"""
    row = session.scalar(
        select(FundNav)
        .where(FundNav.fund_code == fund_code)
        .where(FundNav.nav_date == nav_date)
    )
    return _nav_to_dict(row) if row else None


def get_next_nav_date_after(session, fund_code: str, nav_date: str) -> str | None:
    """取 `nav_date` 之后的第一条本地 NAV 日期,用于 T 日预计确认。"""
    return session.scalar(
        select(FundNav.nav_date)
        .where(FundNav.fund_code == fund_code)
        .where(FundNav.nav_date > nav_date)
        .order_by(FundNav.nav_date)
        .limit(1)
    )


def get_transaction(session, tx_id: int) -> dict | None:
    """按主键取单笔交易,不在则 None。"""
    tx = session.get(FundTransaction, tx_id)
    return _tx_to_dict(tx) if tx else None


def next_tx_seq(session, fund_code: str, tx_date: str) -> int:
    """同日下一笔的 seq:返回当前同日最大 seq + 1,默认 0。"""
    current = session.scalar(
        select(func.coalesce(func.max(FundTransaction.tx_seq), -1))
        .where(FundTransaction.fund_code == fund_code)
        .where(FundTransaction.tx_date == tx_date)
    )
    return int(current) + 1


def add_transaction(session, fund_code: str, attrs: dict) -> dict:
    """插入一笔交易并返回序列化结果。

    `attrs` 允许的字段:`tx_date`、`amount`、`nav`、`fee`、`note`、
    `kind`。`tx_seq` 自动取下一个可用序号;`share` 在本层按
    `amount / nav` 算出,调用方不必传。
    """
    tx_seq = next_tx_seq(session, fund_code, attrs["tx_date"])
    amount = float(attrs["amount"])
    nav = float(attrs["nav"])
    share = amount / nav if nav > 0 else None
    tx = FundTransaction(
        fund_code=fund_code,
        tx_date=attrs["tx_date"],
        tx_seq=tx_seq,
        kind=attrs.get("kind", "buy"),
        amount=amount,
        nav=nav,
        share=share,
        fee=float(attrs["fee"]) if attrs.get("fee") is not None else None,
        note=attrs.get("note"),
    )
    session.add(tx)
    session.flush()
    session.refresh(tx)
    return _tx_to_dict(tx)


def delete_transaction(session, tx_id: int) -> dict | None:
    """按主键删除交易,返回删除前的序列化结果,不存在则 None。"""
    tx = session.get(FundTransaction, tx_id)
    if tx is None:
        return None
    snap = _tx_to_dict(tx)
    session.delete(tx)
    session.flush()
    return snap

def _fund_watchlist_profile_to_dict(row: FundWatchlistProfile) -> dict:
    return {
        "fund_code": row.fund_code,
        "fund_name": row.fund_name,
        "priority": row.priority,
        "holding_weight": row.holding_weight,
        "fund_type": row.fund_type,
        "peer_category": row.peer_category,
        "theme_tags": _json_loads(row.theme_tags_json, []),
        "risk_tags": _json_loads(row.risk_tags_json, []),
        "match_basis": _json_loads(row.match_basis_json, []),
        "manual_overrides": _json_loads(row.manual_overrides_json, {}),
        "profile_status": row.profile_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def upsert_fund_watchlist_profile(s, payload: dict) -> dict:
    """按 `fund_code` upsert 自选基金画像。"""
    row = s.get(FundWatchlistProfile, payload["fund_code"])
    values = {
        "fund_code": payload["fund_code"],
        "fund_name": payload.get("fund_name"),
        "priority": payload.get("priority") or "watching",
        "holding_weight": payload.get("holding_weight"),
        "fund_type": payload.get("fund_type"),
        "peer_category": payload.get("peer_category"),
        "theme_tags_json": payload.get("theme_tags_json"),
        "risk_tags_json": payload.get("risk_tags_json"),
        "match_basis_json": payload.get("match_basis_json"),
        "manual_overrides_json": payload.get("manual_overrides_json"),
        "profile_status": payload.get("profile_status") or "ready",
    }
    if row is None:
        row = FundWatchlistProfile(**values)
        s.add(row)
    else:
        # 用户手动覆盖标签后，自动刷新不能清空 overrides。
        if values["manual_overrides_json"] is None:
            values["manual_overrides_json"] = row.manual_overrides_json
        for key, value in values.items():
            setattr(row, key, value)
    s.flush()
    return _fund_watchlist_profile_to_dict(row)


__all__ = [
    "upsert_fund",
    "upsert_fund_profile",
    "get_fund_profile",
    "upsert_navs",
    "get_accumulated_navs",
    "get_latest_navs_for_funds",
    "get_nav_by_date",
    "get_next_nav_date_after",
    "list_transactions",
    "count_transactions",
    "count_transactions_for_funds",
    "get_transaction",
    "next_tx_seq",
    "add_transaction",
    "delete_transaction",
    "upsert_fund_watchlist_profile",
]
