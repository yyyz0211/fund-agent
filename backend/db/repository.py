"""`backend.services` 用到的持久化帮助函数。

每个函数都把 `Session` 作为第一个参数,由调用方控制事务边界 —
service 既可以传入测试用的内存 Session,也可以传通过
`get_session()` 拿到的真连接。

约定:
- "upsert" 指 insert-if-missing, update-if-present,一次事务搞定。
- 凡是返回行的函数,返回的都是纯 `dict`(而不是 ORM 实例),
  这样调用方可以直接 JSON 序列化。
- 写路径默认在内部自己 `session.commit()`,调用方不要重复提交;少数需要
  原子组合的 service 会显式传 `commit=False` 并自行控制事务。
"""
from sqlalchemy import Integer, and_, cast, delete, func, or_, select, update

from backend.db.models import (
    Briefing,
    ClsTelegraphItem,
    ClsTelegraphSyncState,
    Fund,
    FundInvestmentPlan,
    FundNav,
    FundPendingBuy,
    FundProfile,
    FundTransaction,
    FundWatchlistProfile,
    KnowledgeClassificationLog,
    KnowledgeClassificationState,
    KnowledgeDocument,
    KnowledgeFundMatch,
    KnowledgeReindexJob,
    KnowledgeRetrievalLog,
    KnowledgeSourceLink,
    MarketEvidence,
    MarketSnapshot,
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
    session.commit()
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
    session.commit()
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
    # 顺序:交易明细 → FundNav(行最多) → Fund/Profile → Watchlist,统一一次 commit。
    # delete 一条 SQL 不读 ORM,大表更快。
    session.execute(delete(FundTransaction).where(FundTransaction.fund_code == fund_code))
    session.execute(delete(FundInvestmentPlan).where(FundInvestmentPlan.fund_code == fund_code))
    session.execute(delete(FundPendingBuy).where(FundPendingBuy.fund_code == fund_code))
    session.execute(delete(FundNav).where(FundNav.fund_code == fund_code))
    session.execute(delete(FundProfile).where(FundProfile.fund_code == fund_code))
    session.execute(delete(Fund).where(Fund.fund_code == fund_code))
    session.delete(w)
    session.commit()
    return True


def update_watchlist_note(session, fund_code: str, note: str) -> dict | None:
    """更新自选行的自由 `note` 字段。如果该基金不在自选里,返回 None。"""
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return None
    w.note = note
    session.commit()
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
    session.commit()
    return _watchlist_to_dict(w)


def update_watchlist_preload(session, fund_code: str, *,
                             status: str | None = None,
                             commit: bool = True) -> dict | None:
    """后台预热任务专用更新入口。
    """
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return None
    if status is not None:
        w.preload_status = status
    if commit:
        session.commit()
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
        session.commit()
    return len(rows)


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
    session.commit()


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
    session.commit()
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
    session.commit()
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


def add_transaction(session, fund_code: str, attrs: dict, *, commit: bool = True) -> dict:
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
    if commit:
        session.commit()
    else:
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
    session.commit()
    return snap


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


def add_investment_plan(session, fund_code: str, attrs: dict, *,
                        commit: bool = True) -> dict:
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
    if commit:
        session.commit()
    else:
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
    session.commit()
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
    session.commit()
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


def add_pending_buy(session, fund_code: str, attrs: dict, *,
                    commit: bool = True) -> dict:
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
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(row)
    return _pending_buy_to_dict(row)


def update_pending_buy(session, fund_code: str, pending_id: int,
                       patch: dict, *, commit: bool = True) -> dict | None:
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
    if commit:
        session.commit()
    else:
        session.flush()
        session.refresh(row)
    return _pending_buy_to_dict(row)


# ---------------------------------------------------------------------------
# Briefing
# ---------------------------------------------------------------------------

def upsert_briefing(
    session,
    briefing_date: str,
    payload: dict,
    brief_type: str = "post_market",
) -> Briefing:
    """按 (briefing_date, brief_type) 联合唯一键 upsert 简报;payload 的字段写入 Briefing 各列。"""
    row = session.scalar(
        select(Briefing).where(
            Briefing.briefing_date == briefing_date,
            Briefing.brief_type == brief_type,
        )
    )
    # payload 显式携带 brief_type 时覆盖入参；否则用入参
    payload_eff = {**payload}
    payload_eff.setdefault("brief_type", brief_type)
    if row is None:
        row = Briefing(briefing_date=briefing_date, **payload_eff)
        session.add(row)
    else:
        for key, value in payload_eff.items():
            if hasattr(row, key):
                setattr(row, key, value)
    session.flush()
    return row


# ---------------------------------------------------------------------------
# MarketSnapshot
# ---------------------------------------------------------------------------

def upsert_market_snapshot(
    s,
    trade_date: str,
    snapshot_type: str,
    payload: dict,
) -> MarketSnapshot:
    """upsert market_snapshots 表，返回行。payload keys 对应模型 JSON 列。"""
    import json as _json

    json_keys = (
        "indices_json", "breadth_json", "industry_sectors_json",
        "concept_sectors_json", "industry_flows_json", "concept_flows_json",
        "themes_json", "breadth_indicators_json", "overseas_json",
        "announcements_json",
    )
    values = {"trade_date": trade_date, "snapshot_type": snapshot_type, "source": "akshare"}
    for key in json_keys:
        val = payload.get(key.replace("_json", ""))
        if isinstance(val, (list, dict)):
            values[key] = _json.dumps(val, ensure_ascii=False)
        else:
            values[key] = _json.dumps(val or [])
    values["as_of"] = payload.get("as_of", trade_date)

    row = s.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.trade_date == trade_date,
            MarketSnapshot.snapshot_type == snapshot_type,
        )
    )
    if row is None:
        row = MarketSnapshot(**values)
        s.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
    s.flush()
    return row


# ---------------------------------------------------------------------------
# MarketEvidence
# ---------------------------------------------------------------------------

def _evidence_to_dict(row: MarketEvidence) -> dict:
    """MarketEvidence 的可序列化投影。"""
    import json as _json
    symbols: list = []
    metrics: dict | None = None
    if row.symbols_json:
        try:
            parsed = _json.loads(row.symbols_json)
            if isinstance(parsed, list):
                symbols = parsed
        except (TypeError, ValueError):
            symbols = []
    if row.metrics_json:
        try:
            parsed = _json.loads(row.metrics_json)
            if isinstance(parsed, dict):
                metrics = parsed
        except (TypeError, ValueError):
            metrics = None
    return {
        "id": row.id,
        "trade_date": row.trade_date,
        "brief_type": row.brief_type,
        "category": row.category,
        "title": row.title,
        "summary": row.summary,
        "symbols": symbols,
        "metrics": metrics,
        "source": row.source,
        "source_url": row.source_url,
        "published_at": row.published_at,
        "reliability": row.reliability,
    }


def upsert_market_evidence(s, row: dict) -> bool:
    """按 `(trade_date, brief_type, source_url)` 去重插入。

    返回 True 表示新建，False 表示已存在。
    """
    import hashlib
    import json as _json
    from datetime import datetime

    symbols = row.get("symbols") or []
    metrics = row.get("metrics")
    if not isinstance(symbols, list):
        symbols = [str(symbols)]
    raw_hash = hashlib.sha256(
        f"{row['source_url']}|{row['title']}".encode()
    ).hexdigest()[:32]
    now = datetime.utcnow()
    payload = {
        "trade_date": row["trade_date"],
        "brief_type": row["brief_type"],
        "category": row["category"],
        "title": row["title"],
        "summary": row.get("summary"),
        "symbols_json": _json.dumps(symbols, ensure_ascii=False) if symbols else None,
        "metrics_json": _json.dumps(metrics, ensure_ascii=False) if metrics else None,
        "source": row.get("source") or "unknown",
        "source_url": row["source_url"],
        "published_at": row.get("published_at"),
        "reliability": row.get("reliability") or "official",
        "raw_hash": raw_hash,
        "fetched_at": now,
        "created_at": now,
        "updated_at": now,
    }
    existing = s.scalar(
        select(MarketEvidence).where(
            or_(
                and_(
                    MarketEvidence.trade_date == payload["trade_date"],
                    MarketEvidence.brief_type == payload["brief_type"],
                    MarketEvidence.source_url == payload["source_url"],
                ),
                MarketEvidence.raw_hash == payload["raw_hash"],
            )
        )
    )
    if existing is not None:
        return False
    s.add(MarketEvidence(**payload))
    s.flush()
    return True


def search_market_evidence(
    s,
    *,
    trade_date: str,
    category: str | None = None,
    query: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """按日期 / 类别 / 关键词查询 evidence；按 id 倒序（新→旧）。

    - `query` 为空字符串或 None 时不过滤关键词。
    - `category` 为空字符串或 None 时不过滤类别。
    - 结果以 `_evidence_to_dict` 投影返回。
    """
    stmt = select(MarketEvidence).where(MarketEvidence.trade_date == trade_date)
    if category:
        stmt = stmt.where(MarketEvidence.category == category)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            (MarketEvidence.title.like(like)) | (MarketEvidence.summary.like(like))
        )
    stmt = stmt.order_by(MarketEvidence.id.desc()).limit(max(1, int(limit)))
    rows = s.scalars(stmt).all()
    return [_evidence_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# ClsTelegraphItem / ClsTelegraphSyncState
# ---------------------------------------------------------------------------

def _json_loads(value, fallback):
    import json as _json
    if not value:
        return fallback
    try:
        parsed = _json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed


def _cls_telegraph_to_dict(row: ClsTelegraphItem) -> dict:
    """ClsTelegraphItem 的可序列化投影。"""
    subjects = _json_loads(row.subjects_json, [])
    symbols = _json_loads(row.symbols_json, [])
    raw_json = _json_loads(row.raw_json, {})
    return {
        "id": row.id,
        "cls_id": row.cls_id,
        "title": row.title,
        "brief": row.brief,
        "content": row.content,
        "category": row.category,
        "subjects": subjects if isinstance(subjects, list) else [],
        "symbols": symbols if isinstance(symbols, list) else [],
        "source_url": row.source_url,
        "ctime": row.ctime,
        "published_at": row.published_at,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "raw_json": raw_json if isinstance(raw_json, dict) else {},
    }


def upsert_cls_telegraph_item(s, row: dict) -> bool:
    """按 `cls_id` upsert 财联社电报。

    返回 True 表示新建,False 表示更新已有行。
    """
    import json as _json
    from datetime import datetime

    cls_id = str(row["cls_id"])
    subjects = row.get("subjects") or []
    symbols = row.get("symbols") or []
    raw_json = row.get("raw_json") or {}
    now = datetime.utcnow()
    payload = {
        "cls_id": cls_id,
        "title": row["title"],
        "brief": row.get("brief"),
        "content": row.get("content"),
        "category": row.get("category") or None,
        "subjects_json": _json.dumps(subjects, ensure_ascii=False) if subjects else None,
        "symbols_json": _json.dumps(symbols, ensure_ascii=False) if symbols else None,
        "source_url": row["source_url"],
        "ctime": int(row["ctime"]) if row.get("ctime") is not None else None,
        "published_at": row.get("published_at"),
        "raw_json": _json.dumps(raw_json, ensure_ascii=False) if raw_json else None,
        "fetched_at": now,
        "updated_at": now,
    }
    existing = s.scalar(select(ClsTelegraphItem).where(ClsTelegraphItem.cls_id == cls_id))
    if existing is None:
        s.add(ClsTelegraphItem(**payload, created_at=now))
        s.flush()
        return True
    for key, value in payload.items():
        setattr(existing, key, value)
    s.flush()
    return False


def search_cls_telegraph_items(
    s,
    *,
    limit: int = 50,
    category: str | None = None,
    since_id: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """查询财联社电报,默认按 `ctime/id` 新到旧排序。"""
    stmt = select(ClsTelegraphItem)
    if category:
        stmt = stmt.where(ClsTelegraphItem.category == category)
    if since_id:
        try:
            stmt = stmt.where(cast(ClsTelegraphItem.cls_id, Integer) > int(since_id))
        except (TypeError, ValueError):
            stmt = stmt.where(ClsTelegraphItem.cls_id > str(since_id))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                ClsTelegraphItem.title.like(like),
                ClsTelegraphItem.brief.like(like),
                ClsTelegraphItem.content.like(like),
            )
        )
    stmt = stmt.order_by(
        ClsTelegraphItem.ctime.desc().nullslast(),
        ClsTelegraphItem.id.desc(),
    ).limit(max(1, min(200, int(limit))))
    rows = s.scalars(stmt).all()
    return [_cls_telegraph_to_dict(row) for row in rows]


def _cls_state_to_dict(row: ClsTelegraphSyncState | None) -> dict:
    if row is None:
        return {
            "last_seen_ctime": None,
            "last_seen_cls_id": None,
            "last_success_at": None,
            "last_error": None,
        }
    return {
        "last_seen_ctime": row.last_seen_ctime,
        "last_seen_cls_id": row.last_seen_cls_id,
        "last_success_at": row.last_success_at,
        "last_error": row.last_error,
    }


def get_cls_telegraph_sync_state(s) -> dict:
    """读取财联社电报同步状态。无状态行时返回空状态。"""
    row = s.get(ClsTelegraphSyncState, "default")
    return _cls_state_to_dict(row)


def update_cls_telegraph_sync_state(
    s,
    *,
    last_seen_ctime: int | None = None,
    last_seen_cls_id: str | None = None,
    last_success_at: str | None = None,
    last_error: str | None = None,
) -> dict:
    """更新同步状态；传 None 的断点字段会保留原值。"""
    row = s.get(ClsTelegraphSyncState, "default")
    if row is None:
        row = ClsTelegraphSyncState(id="default")
        s.add(row)
    if last_seen_ctime is not None:
        row.last_seen_ctime = int(last_seen_ctime)
    if last_seen_cls_id is not None:
        row.last_seen_cls_id = str(last_seen_cls_id)
    if last_success_at is not None:
        row.last_success_at = last_success_at
    row.last_error = last_error
    s.flush()
    return _cls_state_to_dict(row)


# ---------------------------------------------------------------------------
# Knowledge Base / RAG
# ---------------------------------------------------------------------------

def _knowledge_document_to_dict(row: KnowledgeDocument) -> dict:
    """KnowledgeDocument 的可序列化投影。

    JSON 字段在 SQLite 中以字符串保存；这里统一解析成 list，避免 service
    层到处重复写容错解析。
    """
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_url": row.source_url,
        "title": row.title,
        "summary": row.summary,
        "content": row.content,
        "normalized_text": row.normalized_text,
        "primary_topic": row.primary_topic,
        "topic_title": row.topic_title,
        "topics": _json_loads(row.topics_json, []),
        "topic_names": _json_loads(row.topic_names_json, []),
        "fund_theme_tags": _json_loads(row.fund_theme_tags_json, []),
        "fund_type_tags": _json_loads(row.fund_type_tags_json, []),
        "markets": _json_loads(row.markets_json, []),
        "asset_classes": _json_loads(row.asset_classes_json, []),
        "impact_direction": row.impact_direction,
        "published_at": row.published_at,
        "effective_until": row.effective_until,
        "relevance_score": row.relevance_score,
        "classification_status": row.classification_status,
        "index_status": row.index_status,
        "embedding_model": row.embedding_model,
        "embedding_version": row.embedding_version,
        "index_attempts": row.index_attempts,
        "last_index_error": row.last_index_error,
        "next_index_retry_at": (
            row.next_index_retry_at.isoformat() if row.next_index_retry_at else None
        ),
        "content_hash": row.content_hash,
        "canonical_content_hash": row.canonical_content_hash,
        "raw_reason": row.raw_reason,
        "conflict_status": row.conflict_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _classification_state_to_dict(row: KnowledgeClassificationState) -> dict:
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "canonical_content_hash": row.canonical_content_hash,
        "latest_attempt_no": row.latest_attempt_no,
        "should_index": row.should_index,
        "relevance_score": row.relevance_score,
        "prompt_version": row.prompt_version,
        "status": row.status,
        "reason": row.reason,
        "document_id": row.document_id,
        "last_error_message": row.last_error_message,
        "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _source_link_to_dict(row: KnowledgeSourceLink) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_url": row.source_url,
        "is_primary": row.is_primary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def upsert_classification_state(s, payload: dict) -> dict:
    """按 `(source_type, source_id)` 更新候选的最新 LLM 准入状态。"""
    row = s.scalar(
        select(KnowledgeClassificationState).where(
            KnowledgeClassificationState.source_type == payload["source_type"],
            KnowledgeClassificationState.source_id == payload["source_id"],
        )
    )
    values = {
        "source_type": payload["source_type"],
        "source_id": payload["source_id"],
        "canonical_content_hash": payload.get("canonical_content_hash"),
        "latest_attempt_no": int(payload.get("latest_attempt_no") or 0),
        "should_index": payload.get("should_index"),
        "relevance_score": payload.get("relevance_score"),
        "prompt_version": payload.get("prompt_version") or "v1",
        "status": payload.get("status") or "pending",
        "reason": payload.get("reason"),
        "document_id": payload.get("document_id"),
        "last_error_message": payload.get("last_error_message"),
        "last_attempt_at": payload.get("last_attempt_at"),
        "next_retry_at": payload.get("next_retry_at"),
    }
    if row is None:
        row = KnowledgeClassificationState(**values)
        s.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    s.flush()
    return _classification_state_to_dict(row)


def append_classification_log(s, payload: dict) -> dict:
    """追加一次 LLM 准入尝试日志。"""
    row = KnowledgeClassificationLog(
        source_type=payload["source_type"],
        source_id=payload["source_id"],
        canonical_content_hash=payload.get("canonical_content_hash"),
        attempt_no=int(payload.get("attempt_no") or 1),
        prompt_version=payload.get("prompt_version") or "v1",
        status=payload.get("status") or "failed",
        should_index=payload.get("should_index"),
        relevance_score=payload.get("relevance_score"),
        reason=payload.get("reason"),
        raw_response_json=payload.get("raw_response_json"),
        error_message=payload.get("error_message"),
        latency_ms=payload.get("latency_ms"),
    )
    s.add(row)
    s.flush()
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "attempt_no": row.attempt_no,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def upsert_knowledge_document(s, payload: dict) -> tuple[dict, bool]:
    """按 `canonical_content_hash` 跨来源去重写入知识文档。

    返回 `(document, created)`；`created=False` 表示已存在同一知识。
    """
    existing = s.scalar(
        select(KnowledgeDocument).where(
            or_(
                KnowledgeDocument.canonical_content_hash == payload["canonical_content_hash"],
                and_(
                    KnowledgeDocument.source_type == payload["source_type"],
                    KnowledgeDocument.source_id == payload["source_id"],
                ),
            )
        )
    )
    values = {
        "source_type": payload["source_type"],
        "source_id": payload["source_id"],
        "source_url": payload.get("source_url") or "",
        "title": payload["title"],
        "summary": payload.get("summary"),
        "content": payload.get("content"),
        "normalized_text": payload["normalized_text"],
        "primary_topic": payload.get("primary_topic"),
        "topic_title": payload.get("topic_title"),
        "topics_json": payload.get("topics_json"),
        "topic_names_json": payload.get("topic_names_json"),
        "fund_theme_tags_json": payload.get("fund_theme_tags_json"),
        "fund_type_tags_json": payload.get("fund_type_tags_json"),
        "markets_json": payload.get("markets_json"),
        "asset_classes_json": payload.get("asset_classes_json"),
        "impact_direction": payload.get("impact_direction") or "unknown",
        "published_at": payload.get("published_at"),
        "effective_until": payload.get("effective_until"),
        "relevance_score": payload.get("relevance_score"),
        "classification_status": payload.get("classification_status") or "accepted",
        "index_status": payload.get("index_status") or "pending",
        "embedding_model": payload.get("embedding_model"),
        "embedding_version": payload.get("embedding_version"),
        "content_hash": payload["content_hash"],
        "canonical_content_hash": payload["canonical_content_hash"],
        "raw_reason": payload.get("raw_reason"),
        "supersedes_id": payload.get("supersedes_id"),
        "conflict_group_id": payload.get("conflict_group_id"),
        "conflict_status": payload.get("conflict_status") or "active",
    }
    if existing is None:
        row = KnowledgeDocument(**values)
        s.add(row)
        s.flush()
        return _knowledge_document_to_dict(row), True

    # 同一来源重复入库时刷新标准化内容；跨来源复用时保留主来源字段。
    if existing.source_type == values["source_type"] and existing.source_id == values["source_id"]:
        for key, value in values.items():
            setattr(existing, key, value)
        s.flush()
    return _knowledge_document_to_dict(existing), False


def upsert_knowledge_source_link(s, payload: dict) -> dict:
    """按 `(source_type, source_id)` 维护知识文档来源链接。"""
    row = s.scalar(
        select(KnowledgeSourceLink).where(
            KnowledgeSourceLink.source_type == payload["source_type"],
            KnowledgeSourceLink.source_id == payload["source_id"],
        )
    )
    values = {
        "document_id": int(payload["document_id"]),
        "source_type": payload["source_type"],
        "source_id": payload["source_id"],
        "source_url": payload.get("source_url"),
        "is_primary": bool(payload.get("is_primary", False)),
    }
    if row is None:
        row = KnowledgeSourceLink(**values)
        s.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    s.flush()
    return _source_link_to_dict(row)


def get_knowledge_document(s, document_id: int) -> dict | None:
    row = s.get(KnowledgeDocument, int(document_id))
    return _knowledge_document_to_dict(row) if row else None


def queue_status(
    s,
    *,
    source_type: str | None = None,
    classification_status: str | None = None,
    index_status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict:
    """返回知识准入 / 索引队列状态。

    rejected / failed 候选来自 classification state；accepted 且已写入
    document 的记录会附带 document/index 状态。
    """
    state_stmt = select(KnowledgeClassificationState)
    if source_type:
        state_stmt = state_stmt.where(KnowledgeClassificationState.source_type == source_type)
    if classification_status:
        state_stmt = state_stmt.where(KnowledgeClassificationState.status == classification_status)
    if since:
        state_stmt = state_stmt.where(KnowledgeClassificationState.created_at > since)
    state_rows = s.scalars(
        state_stmt.order_by(KnowledgeClassificationState.id.desc()).limit(max(1, int(limit)))
    ).all()

    by_classification: dict[str, int] = {}
    for status, count in s.execute(
        select(KnowledgeClassificationState.status, func.count())
        .group_by(KnowledgeClassificationState.status)
    ):
        by_classification[status] = int(count)

    doc_stmt = select(KnowledgeDocument)
    if index_status:
        doc_stmt = doc_stmt.where(KnowledgeDocument.index_status == index_status)
    by_index: dict[str, int] = {}
    for status, count in s.execute(
        select(KnowledgeDocument.index_status, func.count())
        .group_by(KnowledgeDocument.index_status)
    ):
        by_index[status] = int(count)
    docs_by_id = {
        row.id: row for row in s.scalars(doc_stmt).all()
    }

    items: list[dict] = []
    for row in state_rows:
        doc = docs_by_id.get(row.document_id) if row.document_id else None
        if index_status and doc is None:
            continue
        items.append({
            "document_id": doc.id if doc else None,
            "source_type": row.source_type,
            "source_id": row.source_id,
            "title": doc.title if doc else None,
            "classification_status": row.status,
            "index_status": doc.index_status if doc else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return {
        "counts": {
            "by_classification": by_classification,
            "by_index": by_index,
        },
        "items": items[:max(1, int(limit))],
    }


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


def _knowledge_fund_match_to_dict(row: KnowledgeFundMatch) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "fund_code": row.fund_code,
        "match_score": row.match_score,
        "matched_topics": _json_loads(row.matched_topics_json, []),
        "match_reason": row.match_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def upsert_knowledge_fund_match(s, payload: dict) -> dict:
    """按 `(document_id, fund_code)` upsert 知识-基金匹配关系。"""
    row = s.scalar(
        select(KnowledgeFundMatch).where(
            KnowledgeFundMatch.document_id == int(payload["document_id"]),
            KnowledgeFundMatch.fund_code == payload["fund_code"],
        )
    )
    values = {
        "document_id": int(payload["document_id"]),
        "fund_code": payload["fund_code"],
        "match_score": float(payload.get("match_score") or 0),
        "matched_topics_json": payload.get("matched_topics_json"),
        "match_reason": payload.get("match_reason"),
    }
    if row is None:
        row = KnowledgeFundMatch(**values)
        s.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    s.flush()
    return _knowledge_fund_match_to_dict(row)


def list_knowledge_reindex_jobs(s, limit: int = 20) -> list[KnowledgeReindexJob]:
    """返回最近 N 条知识库重建任务,按 id 倒序。"""
    return list(s.scalars(
        select(KnowledgeReindexJob)
        .order_by(KnowledgeReindexJob.id.desc())
        .limit(max(1, int(limit)))
    ).all())
