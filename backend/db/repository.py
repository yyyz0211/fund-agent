from sqlalchemy import select

from backend.db.models import Fund, Watchlist, FundNav


def _watchlist_to_dict(w: Watchlist) -> dict:
    return {"id": w.id, "fund_code": w.fund_code, "is_holding": w.is_holding,
            "is_focus": w.is_focus, "holding_amount": w.holding_amount,
            "holding_share": w.holding_share, "cost_nav": w.cost_nav,
            "buy_date": w.buy_date, "note": w.note}


def add_to_watchlist(session, fund_code: str, note: str | None = None) -> dict:
    existing = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if existing:
        return _watchlist_to_dict(existing)
    w = Watchlist(fund_code=fund_code, note=note)
    session.add(w)
    session.commit()
    return _watchlist_to_dict(w)


def remove_from_watchlist(session, fund_code: str) -> bool:
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return False
    session.delete(w)
    session.commit()
    return True


def update_watchlist_note(session, fund_code: str, note: str) -> dict | None:
    w = session.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
    if not w:
        return None
    w.note = note
    session.commit()
    return _watchlist_to_dict(w)


def get_watchlist(session) -> list[dict]:
    rows = session.scalars(select(Watchlist).order_by(Watchlist.id)).all()
    return [_watchlist_to_dict(w) for w in rows]


def upsert_fund(session, fund: dict) -> None:
    obj = session.get(Fund, fund["fund_code"])
    if obj is None:
        session.add(Fund(**fund))
    else:
        for k, v in fund.items():
            if k != "fund_code":
                setattr(obj, k, v)
    session.commit()


def upsert_navs(session, fund_code: str, rows: list[dict]) -> int:
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
    rows = session.scalars(
        select(FundNav.accumulated_nav)
        .where(FundNav.fund_code == fund_code)
        .order_by(FundNav.nav_date)).all()
    return [float(x) for x in rows if x is not None]