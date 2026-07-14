"""
Briefing domain: 简报生成相关服务.

本目录包含:
- briefing_service.py - 简报服务
- module_briefing.py - 模块简报
- collectors.py - 数据收集器
- persistence.py - 持久化
- jobs.py - 后台任务
- composer.py - 组合器
- modules.py - 模块定义
- types.py - 类型定义
"""
from __future__ import annotations

from backend.services.briefing import briefing_service
from backend.services.market import data_collector as dc
from backend.services.fund import fund_service
from backend.services.watchlist import watchlist_service
from backend.config import settings as app_settings
from backend.services.market import market_evidence_service

__all__ = [
    "briefing_service",
    "dc",
    "fund_service",
    "watchlist_service",
    "app_settings",
    "market_evidence_service",
]
