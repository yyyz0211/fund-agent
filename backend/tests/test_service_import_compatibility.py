"""领域模块移动期间的旧 service import 兼容契约。"""
from __future__ import annotations

import importlib

import pytest


LEGACY_MODULES = {
    "briefing_service": "briefing.briefing_service",
    "module_briefing": "briefing.module_briefing",
    "fund_code_parser": "fund.fund_code_parser",
    "fund_profile_service": "fund.fund_profile_service",
    "fund_service": "fund.fund_service",
    "pnl_service": "fund.pnl_service",
    "portfolio_history": "fund.portfolio_history",
    "what_if_service": "fund.what_if_service",
    "cls_telegraph_client": "knowledge.cls_telegraph_client",
    "cls_telegraph_sync_service": "knowledge.cls_telegraph_sync_service",
    "knowledge_classifier": "knowledge.knowledge_classifier",
    "knowledge_embedding": "knowledge.knowledge_embedding",
    "knowledge_fund_profile_service": "knowledge.knowledge_fund_profile_service",
    "knowledge_ingestion_service": "knowledge.knowledge_ingestion_service",
    "knowledge_match_service": "knowledge.knowledge_match_service",
    "knowledge_normalizer": "knowledge.knowledge_normalizer",
    "knowledge_pgvector": "knowledge.knowledge_pgvector",
    "knowledge_reindex_jobs": "knowledge.knowledge_reindex_jobs",
    "knowledge_schema": "knowledge.knowledge_schema",
    "knowledge_search_service": "knowledge.knowledge_search_service",
    "knowledge_vector": "knowledge.knowledge_vector",
    "data_collector": "market.data_collector",
    "market_evidence_ingestion": "market.market_evidence_ingestion",
    "market_evidence_service": "market.market_evidence_service",
    "market_intel_service": "market.market_intel_service",
    "market_service": "market.market_service",
    "scheduled_refresh": "market.scheduled_refresh",
    "diagnosis_refresh_jobs": "shared.diagnosis_refresh_jobs",
    "diagnosis_rules": "shared.diagnosis_rules",
    "diagnosis_service": "shared.diagnosis_service",
    "metric_service": "shared.metric_service",
    "process_singleflight": "shared.process_singleflight",
    "transaction_service": "watchlist.transaction_service",
    "transaction_service": "watchlist.transaction_service",
    "watchlist_preload_jobs": "watchlist.watchlist_preload_jobs",
    "watchlist_service": "watchlist.watchlist_service",
}


@pytest.mark.parametrize(("legacy_name", "new_name"), LEGACY_MODULES.items())
def test_legacy_service_module_is_alias_of_domain_module(legacy_name, new_name):
    legacy = importlib.import_module(f"backend.services.{legacy_name}")
    current = importlib.import_module(f"backend.services.{new_name}")

    assert legacy is current


def test_patching_legacy_module_updates_domain_module(monkeypatch):
    legacy = importlib.import_module("backend.services.data_collector")
    current = importlib.import_module("backend.services.market.data_collector")
    replacement = object()

    monkeypatch.setattr(legacy, "fetch_sector_snapshot", replacement)

    assert current.fetch_sector_snapshot is replacement
