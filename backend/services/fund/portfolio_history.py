"""持仓组合的每日盈亏时间序列(确定性本地计算)。

基于自选池中 `is_holding=true` 的逐笔买入(`FundTransaction`)与本地日级
`FundNav`,按日期游走计算每日 `invested / market_value / pnl / pnl_pct`,
以及每只基金的当前明细。全部为确定性本地计算,不调 AkShare、不写库。

口径与 `pnl_service` 保持一致:
- 份额:逐笔 `amount / tx_date 当日 NAV` 累加。
- 市值:`份额 * 当日累计净值`(NAV 缺失日前向填充最近一个已知 NAV)。
- 投入:逐笔 `amount` 累加(fee 不从 amount 扣,沿用 recalc_holding 口径)。
- 累计盈亏:`market_value - invested`;投入为 0 当日 `pnl_pct=0.0`(非 None),
  让曲线连续。

`FundTransaction.kind` 目前只有 `"buy"`,本模块只按买入计算,不假装支持减仓。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from backend.db.models import Fund, FundNav, FundTransaction, Watchlist
from backend.services.market import data_collector as dc


def _to_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _resolve_fund_codes(session, fund_codes: list[str] | None) -> list[str]:
    """确定本次纳入计算的基金代码集合。

    `fund_codes` 为空 → 全部 `is_holding=true` 行;否则在传入代码里
    仅保留 `is_holding=true` 的(路由层已校验用户输入格式)。
    """
    stmt = select(Watchlist).where(Watchlist.is_holding.is_(True))
    if fund_codes:
        stmt = stmt.where(Watchlist.fund_code.in_(list(fund_codes)))
    rows = session.scalars(stmt).all()
    return [r.fund_code for r in rows]


def _load_fund_data(session, codes: list[str], start: date, end: date) -> dict:
    """预载窗口内的 NAV、全部买入交易、基金名。

    返回 {code: {"name": str|None, "txs": [...], "nav_by_date": {date: acc_nav}}}。
    NAV 只取 [start, end] 窗口内;交易取全量(首笔可能早于窗口,份额需累计)。
    """
    out: dict = {code: {"name": None, "txs": [], "nav_by_date": {}} for code in codes}
    if not codes:
        return out

    start_str = start.isoformat()
    end_str = end.isoformat()
    navs = session.scalars(
        select(FundNav)
        .where(FundNav.fund_code.in_(codes))
        .where(FundNav.nav_date >= start_str)
        .where(FundNav.nav_date <= end_str)
        .order_by(FundNav.nav_date)
    ).all()
    for row in navs:
        if row.fund_code in out and row.accumulated_nav is not None:
            out[row.fund_code]["nav_by_date"][_to_date(row.nav_date)] = float(row.accumulated_nav)

    txs = session.scalars(
        select(FundTransaction)
        .where(FundTransaction.fund_code.in_(codes))
        .where(FundTransaction.kind == "buy")
        .order_by(FundTransaction.tx_date, FundTransaction.tx_seq)
    ).all()
    for row in txs:
        if row.fund_code in out:
            out[row.fund_code]["txs"].append({
                "tx_date": _to_date(row.tx_date),
                "amount": float(row.amount),
                "nav": float(row.nav),
            })

    fund_rows = session.scalars(select(Fund).where(Fund.fund_code.in_(codes))).all()
    name_map = {f.fund_code: f.fund_name for f in fund_rows}
    for code, payload in out.items():
        payload["name"] = name_map.get(code)
    return out


def _cumulative_share_and_invested(txs: list[dict], upto: date) -> tuple[float, float]:
    """累计截至 `upto`(含)的份额与投入本金。

    份额用每笔的 `tx_date` 当日 NAV 折算;NAV<=0 的坏数据跳过该笔。
    """
    share = 0.0
    invested = 0.0
    for tx in txs:
        if tx["tx_date"] > upto:
            continue
        if tx["nav"] > 0:
            share += tx["amount"] / tx["nav"]
            invested += tx["amount"]
    return share, invested


def _nav_on_or_before(nav_by_date: dict, day: date) -> float | None:
    """前向填充:取 <= day 的最近一个已知 NAV;没有则 None。"""
    candidates = [d for d in nav_by_date if d <= day]
    if not candidates:
        return None
    return nav_by_date[max(candidates)]


def calculate_pnl_series(
    fund_codes: list[str] | None = None,
    start: str = "",
    end: str = "",
    session=None,
) -> dict:
    """计算持仓组合每日盈亏序列。

    返回可直接 JSON 序列化的 dict(不含 ORM 实例)。
    """
    from backend.db.session import get_session

    s = session or get_session()
    owns = session is None
    try:
        end_str = end or dc.today_str()
        if start:
            start_str = start
        else:
            start_str = (datetime.strptime(end_str, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
        start_d = _to_date(start_str)
        end_d = _to_date(end_str)

        codes = _resolve_fund_codes(s, fund_codes)
        data = _load_fund_data(s, codes, start_d, end_d)

        # 每只基金的最终明细(当前份额 / 市值 / 投入),用最后一个已知 NAV 估值。
        per_fund: list[dict] = []
        for code, payload in data.items():
            txs = payload["txs"]
            nav_by_date = payload["nav_by_date"]
            share, invested = _cumulative_share_and_invested(txs, end_d)
            if nav_by_date:
                last_nav = nav_by_date[max(nav_by_date.keys())]
                market = share * last_nav
            else:
                market = 0.0
            per_fund.append({
                "fund_code": code,
                "fund_name": payload["name"],
                "current_share": round(share, 6),
                "current_invested": round(invested, 4),
                "current_market_value": round(market, 4),
            })

        # 完全没有本地 NAV、却有买入记录的基金:无法估值,单列出来给前端提示,
        # 并从逐日游走中整体剔除(否则一只没数据的基金会把整段曲线拖成缺失)。
        uncovered_funds = [
            code for code, payload in data.items()
            if not payload["nav_by_date"] and payload["txs"]
        ]
        uncovered_set = set(uncovered_funds)

        # 按天游走 [start_d, end_d]:每天求各基金份额 * 前向填充 NAV 之和。
        dates_out: list[dict] = []
        cur = start_d
        while cur <= end_d:
            invested_total = 0.0
            market_total = 0.0
            missing_funds: list[str] = []
            has_position = False
            for code, payload in data.items():
                if code in uncovered_set:
                    continue
                txs = payload["txs"]
                first_tx = min((tx["tx_date"] for tx in txs), default=None)
                if first_tx is None or cur < first_tx:
                    continue  # 该基金当天还没买入
                has_position = True
                share, invested = _cumulative_share_and_invested(txs, cur)
                if share <= 0:
                    continue
                nav = _nav_on_or_before(payload["nav_by_date"], cur)
                if nav is None:
                    # 当天(及之前)完全没有 NAV,无法估值,标记缺失。
                    missing_funds.append(code)
                    invested_total += invested
                    continue
                invested_total += invested
                market_total += share * nav
            # 尚未有任何基金买入的日期不产生数据点,避免图表前段全是 0。
            if not has_position:
                cur += timedelta(days=1)
                continue
            pnl = market_total - invested_total
            pnl_pct = (pnl / invested_total) if invested_total > 0 else 0.0
            dates_out.append({
                "date": cur.isoformat(),
                "invested": round(invested_total, 4),
                "market_value": round(market_total, 4),
                "pnl": round(pnl, 4),
                "pnl_pct": round(pnl_pct, 6),
                "missing_funds": missing_funds,
            })
            cur += timedelta(days=1)

        summary_invested = round(sum(f["current_invested"] for f in per_fund), 4)
        summary_market = round(sum(f["current_market_value"] for f in per_fund), 4)
        summary = {
            "invested": summary_invested,
            "market_value": summary_market,
            "pnl_abs": 0.0,
            "pnl_pct": 0.0,
            "daily_points": len(dates_out),
        }
        if summary_invested > 0:
            summary["pnl_abs"] = round(summary_market - summary_invested, 4)
            summary["pnl_pct"] = round(summary["pnl_abs"] / summary_invested, 6)

        return {
            "start": start_str,
            "end": end_str,
            "as_of": dc.today_str(),
            "source": dc.SOURCE,
            "dates": dates_out,
            "per_fund": per_fund,
            "summary": summary,
            "uncovered_funds": uncovered_funds,
        }
    finally:
        if owns:
            s.close()
