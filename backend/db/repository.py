"""`backend.services` 用到的持久化帮助函数。

每个函数都把 `Session` 作为第一个参数,由调用方控制事务边界 —
service 既可以传入测试用的内存 Session,也可以传通过
`get_session()` 拿到的真连接。

约定:
- "upsert" 指 insert-if-missing, update-if-present,一次事务搞定。
- 凡是返回行的函数,返回的都是纯 `dict`(而不是 ORM 实例),
  这样调用方可以直接 JSON 序列化。
- 写路径都在内部自己 `session.commit()`,调用方不要重复提交。
"""
from sqlalchemy import select

from backend.db.models import Fund, Watchlist, FundNav


def _watchlist_to_dict(w: Watchlist) -> dict:
    """把 Watchlist 的 ORM 行投影成一个可序列化的 dict。"""
    return {"id": w.id, "fund_code": w.fund_code, "is_holding": w.is_holding,
            "is_focus": w.is_focus, "holding_amount": w.holding_amount,
            "holding_share": w.holding_share, "cost_nav": w.cost_nav,
            "buy_date": w.buy_date, "note": w.note}


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


def remove_from_watchlist(session, fund_code: str) -> bool:
    """从自选里删除一只基金。返回是否真的删除了一行。"""
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return False
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