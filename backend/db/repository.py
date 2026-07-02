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
from sqlalchemy import delete, func, select

from backend.db.models import Fund, FundNav, FundTransaction, Watchlist


def _watchlist_to_dict(w: Watchlist) -> dict:
    """把 Watchlist 的 ORM 行投影成一个可序列化的 dict。

    时间字段显式转 ISO 字符串,避免 JSON 序列化在 `datetime` 上踩坑;
    DB 里用 `func.now()` 写入的本地时间统一到 UTC ISO 便于前端直接显示。
    """
    return {
        "id": w.id,
        "fund_code": w.fund_code,
        "is_holding": w.is_holding,
        "is_focus": w.is_focus,
        "holding_amount": w.holding_amount,
        "holding_share": w.holding_share,
        "cost_nav": w.cost_nav,
        "buy_date": w.buy_date,
        "note": w.note,
        "cost_nav_basis": w.cost_nav_basis,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


# 允许通过 PATCH 写入的字段白名单 —— 不在白名单里的会被忽略,
# 防止 API 误传 `fund_code`/`id`/`created_at` 等敏感列。
_WATCHLIST_PATCH_FIELDS = {
    "note", "is_holding", "is_focus",
    "holding_amount", "holding_share", "cost_nav", "buy_date",
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
    # 顺序:交易明细 → FundNav(行最多) → Fund → Watchlist,统一一次 commit。
    # delete 一条 SQL 不读 ORM,大表更快。
    session.execute(delete(FundTransaction).where(FundTransaction.fund_code == fund_code))
    session.execute(delete(FundNav).where(FundNav.fund_code == fund_code))
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
