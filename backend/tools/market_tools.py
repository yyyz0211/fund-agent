"""市场数据 LangChain 工具。薄包装 market_service。

Wave 1: 新增三个 evidence / briefing 相关工具
- get_market_snapshot_auto: 读取最新 MarketSnapshot,缺失则触发采集
- search_market_evidence: 查当日证据（政策/公告/宏观/行业热点）
- get_market_briefing: 取最新 Briefing + 数据质量元数据
"""
from datetime import datetime

import httpx

from langchain_core.tools import tool

from backend.config.settings import get_settings
from backend.services import cls_telegraph_client
from backend.services import market_service as msvc
from backend.services import market_intel_service
from backend.services import market_evidence_service
from backend.services import briefing_service


@tool
def get_market_indices() -> dict:
    """获取最新一个交易日的主要市场指数（来自本地库，需先 refresh_market）。"""
    return msvc.get_indices()


@tool
def refresh_market() -> dict:
    """联网拉取主要市场指数当日行情并入本地库。返回 {inserted, source, as_of}。"""
    return msvc.refresh_market()


@tool
def get_market_snapshot_auto(trade_date: str = "", brief_type: str = "post_market") -> dict:
    """读取 MarketSnapshot (指数/板块/宽度等); 不存在则触发 `collect_market_intel`。

    Args:
        trade_date: YYYY-MM-DD,留空取今天
        brief_type: 'morning' | 'post_market',默认 'post_market'

    Returns:
        含 indices / breadth / industry_sectors / overseas / themes / as_of / source 的 dict。
        失败时含 `{error}` 键,不要伪造数字。
    """
    td = trade_date.strip() or datetime.now().strftime("%Y-%m-%d")
    try:
        return market_intel_service.get_market_snapshot(
            trade_date=td, snapshot_type=brief_type or "post_market",
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "trade_date": td, "snapshot_type": brief_type}


@tool
def search_market_evidence(
    query: str = "",
    category: str = "",
    trade_date: str = "",
    limit: int = 20,
) -> dict:
    """按关键词/类别/日期查当日市场证据。

    Args:
        query: 关键词,匹配 title/summary。空=不限
        category: policy / announcement / overseas_disclosure / macro / sector / news。空=不限
        trade_date: YYYY-MM-DD,空=今天
        limit: 最多返回条数,默认 20

    Returns:
        {count, groups: {<category>: [rows...]}, items: [rows...]} 的 dict;
        每条含 id / trade_date / category / title / summary / source / source_url /
        published_at / reliability。无证据返回 {count:0, groups:{}, items:[]}。

    注意: 用户问"为什么涨/跌 / 有什么催化"时,**先用此工具拉证据再下结论**;
    工具没有返回时,只能如实说"本地证据不足",不得编造。
    """
    td = trade_date.strip() or datetime.now().strftime("%Y-%m-%d")
    try:
        rows = market_evidence_service.search_evidence(
            trade_date=td,
            category=(category or "").strip() or None,
            query=(query or "").strip() or None,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "trade_date": td}
    groups: dict = {}
    for r in rows:
        groups.setdefault(r["category"], []).append(r)
    return {"count": len(rows), "groups": groups, "items": rows, "trade_date": td}


@tool
def search_cls_telegraph(
    keyword: str = "",
    category: str = "",
    limit: int = 10,
) -> dict:
    """实时搜索财联社电报。

    Args:
        keyword: 搜索关键词。空字符串直接返回空结果。
        category: 财联社分类: fund / watch / announcement / hk_us / red / remind。空=不限
        limit: 最多返回条数,受 CLS_MAX_SEARCH_LIMIT 限制。

    Returns:
        {count, items, error}。每条 item 含 title / summary / published_at /
        source / source_url / symbols / metrics。回答时必须附 source_url。
    """
    settings = get_settings()
    if not settings.cls_search_enabled:
        return {"count": 0, "items": [], "error": "CLS search disabled"}
    kw = (keyword or "").strip()
    if not kw:
        return {"count": 0, "items": [], "error": ""}
    effective_limit = max(1, min(int(limit or settings.cls_max_search_limit), settings.cls_max_search_limit))
    try:
        with httpx.Client(follow_redirects=True, timeout=settings.cls_timeout_seconds) as client:
            rows = cls_telegraph_client.search_telegraph(
                client=client,
                keyword=kw,
                category=(category or "").strip(),
                limit=effective_limit,
                timeout_seconds=settings.cls_timeout_seconds,
                app_version=settings.cls_app_version,
            )
        return {"count": len(rows), "items": rows, "error": ""}
    except Exception as exc:  # noqa: BLE001
        return {"count": 0, "items": [], "error": str(exc)}


@tool
def get_market_briefing(brief_date: str = "") -> dict:
    """读取最新(或指定日期) Briefing markdown + 数据质量。

    Returns:
        包含 briefing.markdown / sections / data_quality / confidence /
        missing_data / evidence_count / source / as_of 的 dict。无 briefing 返回 {briefing: None}。

        引用时**必须带上** source + as_of + data_quality;data_quality=market_only
        或 partial 时简短告知"部分数据缺失",不要把"缺失"陈述为事实。
    """
    try:
        snap = briefing_service.read_briefing(brief_date or None)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    if snap is None:
        return {"briefing": None}
    return {"briefing": snap}


MARKET_TOOLS = [
    get_market_indices,
    refresh_market,
    get_market_snapshot_auto,
    search_market_evidence,
    search_cls_telegraph,
    get_market_briefing,
]
