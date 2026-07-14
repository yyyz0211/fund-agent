"""Watchlist repository: 自选、投资计划、待确认买入相关持久化."""
from __future__ import annotations

from backend.db.repository import (
    add_to_watchlist,
    add_to_watchlist_full,
    remove_from_watchlist,
    update_watchlist_note,
    get_watchlist,
    get_watchlist_row,
    update_watchlist,
    update_watchlist_preload,
    backfill_watchlist_fund_names,
    list_investment_plans,
    add_investment_plan,
    update_investment_plan,
    delete_investment_plan,
    list_pending_buys,
    get_pending_buy,
    add_pending_buy,
    update_pending_buy,
)

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
