"""持仓盈亏(PnL)领域服务。

读自选池里 `is_holding=true` 的行,结合本地库最新 NAV 计算每只
基金的:

- `current_nav`:最近一次累计净值
- `invested`:`holding_share * cost_nav`(已投入本金)
- `market_value`:`holding_share * current_nav`(当前市值)
- `pnl_abs`:市值 - 投入
- `pnl_pct`:pnl_abs / invested(>0 浮盈,<0 浮亏)

字段缺失(例如只关注但没填份额 / 成本)的行**不抛错**,而是被
放进 `skipped` 列表,告诉调用方哪些行被跳过、为什么。
"""
from __future__ import annotations

from sqlalchemy import select

from backend.db import repository as repo
from backend.db.models import Fund, Watchlist
from backend.services.market import data_collector as dc


_REQUIRED_FIELDS = ("holding_share", "cost_nav")


def _daily_pnl_abs(
    *,
    holding_share: float,
    current_nav: float,
    daily_return: float | None,
) -> float | None:
    if daily_return is None or daily_return <= -1:
        return None
    previous_nav = current_nav / (1 + daily_return)
    return round(holding_share * (current_nav - previous_nav), 4)


def _row_to_pnl_item(row: Watchlist, fund_name: str | None,
                      current_nav: float, nav_date: str,
                      transaction_count: int,
                      daily_return: float | None) -> dict:
    """单行 -> 盈亏 dict。"""
    share = float(row.holding_share or 0.0)
    cost = float(row.cost_nav or 0.0)
    invested = share * cost
    market_value = share * current_nav
    pnl_abs = market_value - invested
    pnl_pct = (pnl_abs / invested) if invested > 0 else None
    daily_abs = _daily_pnl_abs(
        holding_share=share,
        current_nav=current_nav,
        daily_return=daily_return,
    )
    return {
        "fund_code": row.fund_code,
        "fund_name": fund_name,
        "is_focus": bool(row.is_focus),
        "buy_date": row.buy_date,
        "cost_nav": cost,
        "current_nav": current_nav,
        "nav_date": nav_date,
        "holding_share": share,
        "holding_amount": row.holding_amount,
        "invested": round(invested, 4),
        "market_value": round(market_value, 4),
        "pnl_abs": round(pnl_abs, 4),
        "pnl_pct": round(pnl_pct, 6) if pnl_pct is not None else None,
        "daily_return": daily_return,
        "daily_pnl_abs": daily_abs,
        "daily_pnl_pct": daily_return,
        "cost_nav_basis": row.cost_nav_basis or "legacy",
        "transaction_count": transaction_count,
    }


def calculate_pnl(
    fund_codes: list[str] | None = None,
    session=None,
) -> dict:
    """计算持仓盈亏。

    参数:
        fund_codes: 可选子集 —— 只算这些 fund_code;为 None 时算全部
            `is_holding=true` 的行。
        session: SQLAlchemy Session,测试可传 in-memory。

    返回:
        {
          "as_of": "2026-06-30",
          "source": "akshare",
          "items": [ {fund_code, fund_name, current_nav, pnl_abs, pnl_pct, ...}, ... ],
          "totals": { "invested": ..., "market_value": ..., "pnl_abs": ..., "pnl_pct": ... },
          "skipped": [ {fund_code, reason}, ... ],
        }

    一只基金没有 NAV 数据时,也会被跳进 `skipped` 列表(reason: "no nav data")。
    """
    from backend.db.session_scope import session_scope

    if session is None:
        with session_scope() as s:
            return _calculate_pnl_impl(fund_codes, s)
    return _calculate_pnl_impl(fund_codes, session)


def _calculate_pnl_impl(fund_codes, s):
    stmt = select(Watchlist).where(Watchlist.is_holding.is_(True))
    if fund_codes:
        stmt = stmt.where(Watchlist.fund_code.in_(list(fund_codes)))
    rows = list(s.scalars(stmt).all())

    items: list[dict] = []
    skipped: list[dict] = []

    # 一次性把当前会用到 fund_name / 最新 NAV / 交易笔数 拉出来,避免 N+1。
    codes = [r.fund_code for r in rows]
    names: dict[str, str | None] = {}
    latest: dict[str, dict] = {}
    tx_counts: dict[str, int] = {}
    if codes:
        name_rows = s.scalars(select(Fund).where(Fund.fund_code.in_(codes))).all()
        names = {f.fund_code: f.fund_name for f in name_rows}

        latest = repo.get_latest_navs_for_funds(s, codes)
        tx_counts = repo.count_transactions_for_funds(s, codes)

    for r in rows:
        if r.holding_share is None or r.cost_nav is None:
            missing = [
                name for name, val in zip(_REQUIRED_FIELDS,
                                          (r.holding_share, r.cost_nav))
                if val is None
            ]
            skipped.append({
                "fund_code": r.fund_code,
                "reason": f"missing fields: {','.join(missing)}",
            })
            continue
        if float(r.holding_share) <= 0 or float(r.cost_nav) <= 0:
            skipped.append({
                "fund_code": r.fund_code,
                "reason": "non-positive holding_share or cost_nav",
            })
            continue
        latest_nav = latest.get(r.fund_code)
        if (
            latest_nav is None
            or latest_nav.get("accumulated_nav") is None
        ):
            skipped.append({
                "fund_code": r.fund_code,
                "reason": "no nav data; call refresh_fund first",
            })
            continue
        current_nav = float(latest_nav["accumulated_nav"])
        nav_date = str(latest_nav["nav_date"])
        daily_return = latest_nav.get("daily_return")
        items.append(_row_to_pnl_item(
            r, names.get(r.fund_code), current_nav, nav_date,
            tx_counts.get(r.fund_code, 0),
            float(daily_return) if daily_return is not None else None,
        ))

    # 聚合
    invested_total = round(sum(i["invested"] for i in items), 4)
    market_total = round(sum(i["market_value"] for i in items), 4)
    pnl_total = round(market_total - invested_total, 4)
    pnl_pct_total = (pnl_total / invested_total) if invested_total > 0 else None

    as_of = max(
        (i["nav_date"] for i in items),
        default=dc.today_str(),
    )

    return {
        "as_of": as_of,
        "source": dc.SOURCE,
        "items": items,
        "totals": {
            "invested": invested_total,
            "market_value": market_total,
            "pnl_abs": pnl_total,
            "pnl_pct": round(pnl_pct_total, 6) if pnl_pct_total is not None else None,
            "count": len(items),
            },
            "skipped": skipped,
        }
