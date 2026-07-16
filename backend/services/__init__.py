"""领域服务.

本模块作为兼容层,从各领域子模块重新导出:
- fund/: 基金净值、持仓、PnL
- watchlist/: 自选、交易、投资计划
- market/: 市场数据、证据采集
- knowledge/: 知识库、RAG、向量检索
- briefing/: 简报生成
- shared/: 跨领域共享工具

新代码建议直接从 `backend.services.fund` 等子模块导入。
"""
from __future__ import annotations

from importlib import import_module
import sys

from backend.services import fund
from backend.services import watchlist
from backend.services import market
from backend.services import knowledge
from backend.services import briefing
from backend.services import shared


_LEGACY_MODULE_ALIASES = {
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
    "watchlist_preload_jobs": "watchlist.watchlist_preload_jobs",
    "watchlist_service": "watchlist.watchlist_service",
}


def _install_legacy_module_aliases() -> None:
    """让迁移窗口内的新旧 service import 指向同一个模块对象。"""
    package = sys.modules[__name__]
    for legacy_name, current_name in _LEGACY_MODULE_ALIASES.items():
        module = import_module(f"{__name__}.{current_name}")
        setattr(package, legacy_name, module)
        sys.modules[f"{__name__}.{legacy_name}"] = module


_install_legacy_module_aliases()

__all__ = [
    "fund",
    "watchlist",
    "market",
    "knowledge",
    "briefing",
    "shared",
    *_LEGACY_MODULE_ALIASES,
]
