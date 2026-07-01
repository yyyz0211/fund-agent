"""多笔加仓的领域服务。

核心是 `recalc_holding` —— 读一只基金的全部 `FundTransaction`,
按 **加权平均成本** 公式重算 `holding_share` / `cost_nav` 并
回写到 `Watchlist` 表,供 `pnl_service.calculate_pnl` 直接读取。

加权平均公式(对每一笔 buy 累加):

    share_new = share_old + amount / nav
    cost_new  = (share_old * cost_old + amount) / share_new   # share_new > 0
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from backend.db.models import FundTransaction, Watchlist
from backend.db.session import get_session
from backend.db import repository as repo


# Watchlist 表里 holding/cost 写库的精度 —— 6 位小数够精确,不与 PnL
# 服务(round 4 位)冲突。
_Q = Decimal("0.000001")


def _round6(x: float) -> float:
    """浮点 → 6 位小数 Decimal 中转 → float,避免长尾累积误差。"""
    if x is None:
        return None  # type: ignore[return-value]
    return float(Decimal(str(x)).quantize(_Q, rounding=ROUND_HALF_UP))


def recalc_holding(fund_code: str, session=None) -> dict | None:
    """从 FundTransaction 表重算并回写 Watchlist.holding_share/cost_nav。

    行为:
    - 没有交易记录: 保留 Watchlist 现状(老数据兼容),basis 标 legacy。
    - 有交易记录: 用"现有 Watchlist 的 share/cost 作为初始仓位 + 逐笔
      buy 累加"的方式重算。回写后 cost_nav_basis = "transactions"。
    - 该基金不在自选里: 返回 None(调用方发 404)。

    返回最新的 watchlist dict(经 `_watchlist_to_dict` 序列化),
    或 None。
    """
    s = session or get_session()
    owns = session is None
    try:
        w = s.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
        if w is None:
            return None

        txs = repo.list_transactions(s, fund_code)
        if not txs:
            # 没交易记录:
            # - basis=legacy(从未进过交易表): 保留手工录入,不动。
            # - basis=transactions(曾被交易表接管后又删干净):
            #   原种子已经被合并/覆盖,无法还原;清成 None 让 PnL skip,
            #   否则 PnL 会用合并后的 share/cost 算出与用户意图不符的数。
            if w.cost_nav_basis == "transactions":
                w.holding_share = None
                w.cost_nav = None
                w.holding_amount = None
            elif w.cost_nav_basis is None:
                w.cost_nav_basis = "legacy"
            s.commit()
            return repo.get_watchlist_row(s, fund_code)

        # 初始仓位: 已被交易表接管 → 直接从交易表算,不与已经
        # 合并过的 holding 再次合并(否则会重复累加);首次接管 →
        # 优先用 Watchlist 现有字段(老数据兼容);否则从 0 起。
        if w.cost_nav_basis == "transactions":
            cur_share = 0.0
            cur_cost = 0.0
        else:
            cur_share = float(w.holding_share) if w.holding_share else 0.0
            cur_cost = float(w.cost_nav) if w.cost_nav else 0.0
        invested = cur_share * cur_cost

        for tx in txs:
            if tx["kind"] != "buy":
                # 当前只支持 buy;遇到未知 kind 跳过(防御性)
                continue
            amount = float(tx["amount"])
            nav = float(tx["nav"])
            if nav <= 0 or amount <= 0:
                continue
            delta = amount / nav
            new_share = cur_share + delta
            if new_share <= 0:
                # 数值上不可能(只加不卖),但保留防御
                continue
            invested += amount
            new_cost = invested / new_share
            cur_share = new_share
            cur_cost = new_cost

        w.holding_share = _round6(cur_share)
        w.cost_nav = _round6(cur_cost)
        w.holding_amount = _round6(invested)
        w.cost_nav_basis = "transactions"
        # 首次建仓日期 = 最早一笔 buy 的日期(若还没有 buy_date)
        if not w.buy_date and txs:
            w.buy_date = txs[0]["tx_date"]
        s.commit()
        return repo.get_watchlist_row(s, fund_code)
    finally:
        if owns:
            s.close()
