"""Fund repository: 基金净值、持仓、交易相关持久化."""
from __future__ import annotations

# Re-export from legacy repository.py for compatibility
from backend.db.repository import (
    upsert_fund,
    upsert_fund_profile,
    get_fund_profile,
    upsert_navs,
    get_accumulated_navs,
    get_latest_navs_for_funds,
    get_nav_by_date,
    get_next_nav_date_after,
    list_transactions,
    count_transactions,
    count_transactions_for_funds,
    get_transaction,
    next_tx_seq,
    add_transaction,
    delete_transaction,
    upsert_fund_watchlist_profile,
)

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
