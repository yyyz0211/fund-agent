"""Briefing collectors: 快照与证据收集.

证据收集逻辑位于:
- market_evidence_service.collect_and_run_for_brief_type()
- briefing_service.collect_watchlist_snapshot()
- briefing_service._collect_market_snapshot()

本模块提供简报专用的快捷封装。
"""
from __future__ import annotations

# Re-export from legacy locations for compatibility
from backend.services.market.market_evidence_service import (
    collect_and_run_for_brief_type,
    search_evidence,
)

__all__ = [
    "collect_and_run_for_brief_type",
    "search_evidence",
]
