"""Repositories: 按领域拆分的持久化帮助函数.

本目录包含:
- fund.py: 基金净值、持仓、交易相关
- watchlist.py: 自选、投资计划、待确认买入相关
- market.py: 市场快照、市场证据相关
- briefing.py: 简报相关
- knowledge.py: 知识库、RAG 相关
- jobs.py: 后台任务状态相关

每个模块从 backend.db.repository 重新导出兼容函数。
新代码应直接从这些模块导入,旧代码继续使用 backend.db.repository。
"""
from __future__ import annotations

from backend.db.repositories import fund, watchlist, market, briefing, knowledge, jobs

__all__ = [
    "fund",
    "watchlist",
    "market",
    "briefing",
    "knowledge",
    "jobs",
]
