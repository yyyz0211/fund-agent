"""Watchlist repository: 自选、投资计划、待确认买入相关持久化。"""
from __future__ import annotations

from sqlalchemy import delete, select, update

from backend.db.models import (
    Fund,
    FundInvestmentPlan,
    FundNav,
    FundPendingBuy,
    FundProfile,
    FundTransaction,
    Watchlist,
)


def _watchlist_to_dict(w: Watchlist) -> dict:
    """把 Watchlist 的 ORM 行投影成一个可序列化的 dict。

    时间字段显式转 ISO 字符串,避免 JSON 序列化在 `datetime` 上踩坑;
    DB 里用 `func.now()` 写入的本地时间统一到 UTC ISO 便于前端直接显示。
    """
    return {
        "id": w.id,
        "fund_code": w.fund_code,
        "fund_name": w.fund_name,
        "is_holding": w.is_holding,
        "is_focus": w.is_focus,
        "holding_amount": w.holding_amount,
        "holding_share": w.holding_share,
        "cost_nav": w.cost_nav,
        "buy_date": w.buy_date,
        "preload_status": w.preload_status,
        "note": w.note,
        "cost_nav_basis": w.cost_nav_basis,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }

def _investment_plan_to_dict(plan: FundInvestmentPlan) -> dict:
    """FundInvestmentPlan 的可序列化投影。"""
    return {
        "id": plan.id,
        "fund_code": plan.fund_code,
        "amount": plan.amount,
        "frequency": plan.frequency,
        "day_rule": plan.day_rule,
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "status": plan.status,
        "note": plan.note,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


def _pending_buy_to_dict(row: FundPendingBuy) -> dict:
    """FundPendingBuy 的可序列化投影。"""
    return {
        "id": row.id,
        "fund_code": row.fund_code,
        "request_date": row.request_date,
        "amount": row.amount,
        "fee": row.fee,
        "note": row.note,
        "status": row.status,
        "nav_date": row.nav_date,
        "nav": row.nav,
        "share": row.share,
        "transaction_id": row.transaction_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# 允许通过 PATCH 写入的字段白名单 —— 不在白名单里的会被忽略,
# 防止 API 误传 `fund_code`/`id`/`created_at` 等敏感列。
_WATCHLIST_PATCH_FIELDS = {
    "note", "is_holding", "is_focus",
    "holding_amount", "holding_share", "cost_nav", "buy_date",
    "fund_name",
}


def _patch_to_set(patch: dict) -> dict:
    """把入参 dict 收敛到 ORM 列集合,丢掉未知 key。"""
    return {k: v for k, v in patch.items() if k in _WATCHLIST_PATCH_FIELDS}


def add_to_watchlist(session, fund_code: str, note: str | None = None) -> dict:
    """把基金加入自选,如果已存在则直接返回已有行。

    幂等:同一 `fund_code` 第二次调用,返回的是第一次创建的那一行
    (新传入的 `note` 会被忽略 —— 想改 note 请用
    `update_watchlist_note`)。
    """
    existing = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if existing:
        return _watchlist_to_dict(existing)
    w = Watchlist(fund_code=fund_code, note=note)
    session.add(w)
    session.flush()
    return _watchlist_to_dict(w)


def add_to_watchlist_full(session, fund_code: str, attrs: dict) -> dict:
    """加入自选池并初始化全部字段(给 POST /api/watchlist 用)。

    与 `add_to_watchlist` 的区别:`attrs` 接受白名单内的全部列,
    首次写入时落到新行;基金已存在则返回已有行,**不会**用 attrs
    覆盖已有值 —— 想改字段请走 PATCH。
    """
    existing = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if existing:
        return _watchlist_to_dict(existing)
    init = {k: v for k, v in (attrs or {}).items() if k in _WATCHLIST_PATCH_FIELDS}
    w = Watchlist(fund_code=fund_code, **init)
    session.add(w)
    session.flush()
    return _watchlist_to_dict(w)


def remove_from_watchlist(session, fund_code: str) -> bool:
    """从自选里删除一只基金,级联清理该基金缓存。

    删一行 Watchlist,并把同 `fund_code` 的 Fund(基础信息)和
    FundNav(净值快照)也一并删掉 —— 不留"幽灵数据":
    删了自选再点回这条基金,应触发"立即拉取"按钮,而不是把早已
    作废的净值/基础信息当成本地真相显示出来。

    注意:`MarketData` 表存的是市场指数(如沪深300),它的主键是
    `symbol + market_date` 而非 `fund_code`,不应被波及。

    返回是否真的删了一行 Watchlist;不在池中返回 False。
    """
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return False
    # 顺序:交易明细 → FundNav(行最多) → Fund/Profile → Watchlist,统一一次 flush。
    # delete 一条 SQL 不读 ORM,大表更快。
    session.execute(delete(FundTransaction).where(FundTransaction.fund_code == fund_code))
    session.execute(delete(FundInvestmentPlan).where(FundInvestmentPlan.fund_code == fund_code))
    session.execute(delete(FundPendingBuy).where(FundPendingBuy.fund_code == fund_code))
    session.execute(delete(FundNav).where(FundNav.fund_code == fund_code))
    session.execute(delete(FundProfile).where(FundProfile.fund_code == fund_code))
    session.execute(delete(Fund).where(Fund.fund_code == fund_code))
    session.delete(w)
    session.flush()
    return True


def update_watchlist_note(session, fund_code: str, note: str) -> dict | None:
    """更新自选行的自由 `note` 字段。如果该基金不在自选里,返回 None。"""
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return None
    w.note = note
    session.flush()
    return _watchlist_to_dict(w)


def get_watchlist(session) -> list[dict]:
    """列出全部自选行,按插入顺序(id 升序)排序。"""
    rows = session.scalars(select(Watchlist).order_by(Watchlist.id)).all()
    return [_watchlist_to_dict(w) for w in rows]


def get_watchlist_row(session, fund_code: str) -> dict | None:
    """按 `fund_code` 查单条,不在池中返回 None。"""
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    return _watchlist_to_dict(w) if w else None


def update_watchlist(session, fund_code: str, patch: dict) -> dict | None:
    """按 `fund_code` 更新自选行。

    只 patch 白名单内的字段(`_WATCHLIST_PATCH_FIELDS`),
    其他字段保持不变。该基金不在自选里时返回 None。
    """
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return None
    for k, v in _patch_to_set(patch).items():
        setattr(w, k, v)
    session.flush()
    return _watchlist_to_dict(w)


def update_watchlist_preload(session, fund_code: str, *,
                             status: str | None = None) -> dict | None:
    """后台预热任务专用更新入口。
    """
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return None
    if status is not None:
        w.preload_status = status
    session.flush()
    return _watchlist_to_dict(w)


def backfill_watchlist_fund_names(session) -> int:
    """从本地 `funds.fund_name` 回填 `watchlist.fund_name`。

    修复: 之前 Watchlist 表没有 fund_name 字段, briefing 显示空字符串。
    加列后老行 fund_name=NULL, 跑一次此函数把它们从 Fund 表回填过来。

    行为:
    - 仅更新 fund_name IS NULL 的行, 不覆盖用户手动输入。
    - 幂等: 可重复运行。
    - 返回回填的行数 (供监控)。
    """
    rows = session.execute(
        update(Watchlist)
        .where(Watchlist.fund_name.is_(None))
        .where(Watchlist.fund_code.in_(
            select(Fund.fund_code).where(Fund.fund_name.is_not(None))
        ))
        .values(fund_name=select(Fund.fund_name)
                 .where(Fund.fund_code == Watchlist.fund_code)
                 .scalar_subquery())
        .returning(Watchlist.fund_code)
    ).all()
    if rows:
        session.flush()
    return len(rows)

_INVESTMENT_PLAN_PATCH_FIELDS = {
    "amount", "frequency", "day_rule", "start_date", "end_date", "status", "note",
}


def list_investment_plans(session, fund_code: str) -> list[dict]:
    """按创建顺序列出某只基金的定投计划。"""
    rows = session.scalars(
        select(FundInvestmentPlan)
        .where(FundInvestmentPlan.fund_code == fund_code)
        .order_by(FundInvestmentPlan.id)
    ).all()
    return [_investment_plan_to_dict(plan) for plan in rows]


def add_investment_plan(session, fund_code: str, attrs: dict) -> dict:
    """新增一条定投计划规则。"""
    plan = FundInvestmentPlan(
        fund_code=fund_code,
        amount=float(attrs["amount"]),
        frequency=attrs["frequency"],
        day_rule=attrs["day_rule"],
        start_date=attrs["start_date"],
        end_date=attrs.get("end_date"),
        status=attrs.get("status") or "active",
        note=attrs.get("note"),
    )
    session.add(plan)
    session.flush()
    session.refresh(plan)
    return _investment_plan_to_dict(plan)


def update_investment_plan(session, fund_code: str, plan_id: int,
                           patch: dict) -> dict | None:
    """更新一条定投计划;fund_code 不匹配时视为不存在。"""
    plan = session.scalar(
        select(FundInvestmentPlan)
        .where(FundInvestmentPlan.id == plan_id)
        .where(FundInvestmentPlan.fund_code == fund_code)
    )
    if plan is None:
        return None
    for key, value in (patch or {}).items():
        if key in _INVESTMENT_PLAN_PATCH_FIELDS:
            setattr(plan, key, value)
    session.flush()
    return _investment_plan_to_dict(plan)


def delete_investment_plan(session, fund_code: str, plan_id: int) -> dict | None:
    """删除一条定投计划,返回删除前快照。"""
    plan = session.scalar(
        select(FundInvestmentPlan)
        .where(FundInvestmentPlan.id == plan_id)
        .where(FundInvestmentPlan.fund_code == fund_code)
    )
    if plan is None:
        return None
    snap = _investment_plan_to_dict(plan)
    session.delete(plan)
    session.flush()
    return snap


def list_pending_buys(session, fund_code: str) -> list[dict]:
    """按创建顺序列出某只基金的待确认申购记录。"""
    rows = session.scalars(
        select(FundPendingBuy)
        .where(FundPendingBuy.fund_code == fund_code)
        .order_by(FundPendingBuy.id)
    ).all()
    return [_pending_buy_to_dict(row) for row in rows]


def get_pending_buy(session, fund_code: str, pending_id: int) -> dict | None:
    """按 fund_code + id 读取一条待确认申购。"""
    row = session.scalar(
        select(FundPendingBuy)
        .where(FundPendingBuy.id == pending_id)
        .where(FundPendingBuy.fund_code == fund_code)
    )
    return _pending_buy_to_dict(row) if row else None


def add_pending_buy(session, fund_code: str, attrs: dict) -> dict:
    """新增一条待确认申购记录。"""
    row = FundPendingBuy(
        fund_code=fund_code,
        request_date=attrs["request_date"],
        amount=float(attrs["amount"]),
        fee=float(attrs["fee"]) if attrs.get("fee") is not None else None,
        note=attrs.get("note"),
        status="pending",
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return _pending_buy_to_dict(row)


def update_pending_buy(session, fund_code: str, pending_id: int,
                       patch: dict) -> dict | None:
    """更新待确认申购;fund_code 不匹配时视为不存在。"""
    row = session.scalar(
        select(FundPendingBuy)
        .where(FundPendingBuy.id == pending_id)
        .where(FundPendingBuy.fund_code == fund_code)
    )
    if row is None:
        return None
    for key in ("status", "nav_date", "nav", "share", "transaction_id"):
        if key in patch:
            setattr(row, key, patch[key])
    session.flush()
    session.refresh(row)
    return _pending_buy_to_dict(row)


__all__ = [
    "add_to_watchlist",
    "add_to_watchlist_full",
    "remove_from_watchlist",
    "update_watchlist_note",
    "get_watchlist",
    "get_watchlist_row",
    "update_watchlist",
    "update_watchlist_preload",
    "backfill_watchlist_fund_names",
    "list_investment_plans",
    "add_investment_plan",
    "update_investment_plan",
    "delete_investment_plan",
    "list_pending_buys",
    "get_pending_buy",
    "add_pending_buy",
    "update_pending_buy",
]
