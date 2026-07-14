"""市场数据 LangChain 工具。薄包装 market_service。

Wave 1: 新增三个 evidence / briefing 相关工具
- get_market_snapshot_auto: 读取最新 MarketSnapshot,缺失则触发采集
- search_market_evidence: 查当日证据（政策/公告/宏观/行业热点）
- get_market_briefing: 取最新 Briefing + 数据质量元数据
"""
from datetime import datetime

import httpx

from langchain_core.tools import tool
from sqlalchemy import select

from backend.config.settings import get_settings
from backend.db.models import Briefing
from backend.db.session import get_session
from backend.services.knowledge import cls_telegraph_client
from backend.services.market import market_service as msvc
from backend.services.market import market_intel_service
from backend.services.market import market_evidence_service
from backend.services.briefing import briefing_service


_CLS_TELEGRAPH_PUBLIC_KEYS = (
    "title",
    "summary",
    "published_at",
    "source",
    "source_url",
    "symbols",
    "metrics",
)


def _limit(value: int, *, default: int = 5, max_value: int = 20) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, max_value))


def _safe_list(value) -> list:
    return value if isinstance(value, list) else []


def _flow_key(row: dict) -> str:
    return str(row.get("name") or row.get("sector") or row.get("board_name") or "")


def _merge_flows(sectors: list[dict], flows: list[dict]) -> list[dict]:
    flow_map = {_flow_key(row): row for row in flows if _flow_key(row)}
    merged: list[dict] = []
    for row in sectors:
        item = dict(row)
        if "net_flow" not in item:
            item["net_flow"] = flow_map.get(_flow_key(row), {}).get("net_flow")
        merged.append(item)
    return merged


def _top_rows(rows: list[dict], *, limit: int, sort: str = "change_pct") -> list[dict]:
    key = "net_flow" if sort == "flow" else "change_pct"
    return sorted(
        rows,
        key=lambda row: abs(float(row.get(key) or 0)),
        reverse=True,
    )[:limit]


def _public_cls_telegraph_item(row: dict) -> dict:
    return {key: row.get(key) for key in _CLS_TELEGRAPH_PUBLIC_KEYS if key in row}


@tool
def get_market_indices() -> dict:
    """获取最新一个交易日的主要市场指数（来自本地库，需先 refresh_market）。"""
    return msvc.get_indices()


@tool
def refresh_market() -> dict:
    """联网拉取主要市场指数当日行情并入本地库。返回 {inserted, source, as_of}。"""
    return msvc.refresh_market()


@tool
def get_market_snapshot_auto(
    date: str = "",
    snapshot_type: str = "post_market",
    limit: int = 5,
    trade_date: str = "",
    brief_type: str = "",
) -> dict:
    """读取 MarketSnapshot (指数/板块/宽度等); 不存在则触发 `collect_market_intel`。

    Args:
        date/trade_date: YYYY-MM-DD；trade_date 是新版别名，留空取今天
        snapshot_type/brief_type: morning / pre_market / post_market；brief_type 是新版别名
        limit: 返回各类明细的最大条数

    Returns:
        含 indices / breadth / industry_sectors / overseas / themes / as_of / source 的 dict。
        失败时含 `{error}` 键,不要伪造数字。
    """
    td = (trade_date or date).strip() or datetime.now().strftime("%Y-%m-%d")
    resolved_type = (brief_type or snapshot_type or "post_market").strip()
    lim = _limit(limit)
    try:
        snapshot = market_intel_service.get_market_snapshot(
            trade_date=td, snapshot_type=resolved_type,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "trade_date": td, "snapshot_type": resolved_type}

    industry = _merge_flows(
        _safe_list(snapshot.get("industry_sectors")),
        _safe_list(snapshot.get("industry_flows")),
    )
    concept = _merge_flows(
        _safe_list(snapshot.get("concept_sectors")),
        _safe_list(snapshot.get("concept_flows")),
    )
    return {
        "trade_date": snapshot.get("trade_date") or td,
        "snapshot_type": snapshot.get("snapshot_type") or resolved_type,
        "indices": _safe_list(snapshot.get("indices"))[:lim],
        "breadth": snapshot.get("breadth") if isinstance(snapshot.get("breadth"), dict) else {},
        "top_industry_sectors": _top_rows(industry, limit=lim),
        "top_concept_sectors": _top_rows(concept, limit=lim),
        "overseas": _safe_list(snapshot.get("overseas"))[:lim],
        "announcements": _safe_list(snapshot.get("announcements"))[:lim],
        "errors": _safe_list(snapshot.get("errors")),
        "source": snapshot.get("source") or "akshare",
        "as_of": snapshot.get("as_of") or snapshot.get("trade_date") or td,
    }


@tool
def get_sector_heatmap(
    kind: str = "industry",
    sort: str = "change_pct",
    limit: int = 10,
    date: str = "",
    snapshot_type: str = "post_market",
) -> dict:
    """获取行业/概念板块强弱和资金流；只描述行情，不单独证明催化原因。"""
    normalized_kind = "concept" if kind == "concept" else "industry"
    normalized_sort = "flow" if sort == "flow" else "change_pct"
    snapshot = market_intel_service.get_market_snapshot(
        trade_date=date or None,
        snapshot_type=snapshot_type,
    )
    sector_key = "concept_sectors" if normalized_kind == "concept" else "industry_sectors"
    flow_key = "concept_flows" if normalized_kind == "concept" else "industry_flows"
    rows = _merge_flows(
        _safe_list(snapshot.get(sector_key)),
        _safe_list(snapshot.get(flow_key)),
    )
    return {
        "kind": normalized_kind,
        "sort": normalized_sort,
        "trade_date": snapshot.get("trade_date") or date or "",
        "snapshot_type": snapshot.get("snapshot_type") or snapshot_type,
        "rows": _top_rows(rows, limit=_limit(limit, default=10), sort=normalized_sort),
        "source": snapshot.get("source") or "akshare",
        "as_of": snapshot.get("as_of") or snapshot.get("trade_date") or date or "",
        "missing_evidence_note": "该工具只返回行情强弱与资金流，不包含新闻/政策催化证据。",
    }


@tool
def get_latest_market_brief() -> dict:
    """获取最近一篇本地市场/基金简报。"""
    session = get_session()
    try:
        row = session.scalar(
            select(Briefing).order_by(Briefing.briefing_date.desc()).limit(1)
        )
        if row is None:
            return {
                "error": "本地暂无市场简报，请先运行 briefing 生成或刷新。",
                "source": "local",
                "as_of": "",
            }
        return {
            "briefing_date": row.briefing_date,
            "title": row.title,
            "markdown": row.markdown,
            "source": row.source or "local",
            "as_of": row.as_of or row.briefing_date,
        }
    finally:
        session.close()


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
                max_attempts=int(getattr(settings, "cls_max_attempts", 1)),
                retry_base_seconds=float(getattr(settings, "cls_retry_base_seconds", 1.0)),
            )
        items = [_public_cls_telegraph_item(row) for row in rows]
        return {"count": len(items), "items": items, "error": ""}
    except Exception as exc:  # noqa: BLE001
        return {"count": 0, "items": [], "error": str(exc)}


@tool
def get_market_briefing(brief_date: str = "", brief_type: str = "post_market") -> dict:
    """读取最新(或指定日期) Briefing markdown + 数据质量。

    Returns:
        包含 briefing.markdown / sections / data_quality / confidence /
        missing_data / evidence_count / source / as_of 的 dict。无 briefing 返回 {briefing: None}。

        引用时**必须带上** source + as_of + data_quality;data_quality=market_only
        或 partial 时简短告知"部分数据缺失",不要把"缺失"陈述为事实。
    """
    try:
        snap = briefing_service.read_briefing(
            brief_date or None,
            brief_type=brief_type or "post_market",
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    if snap is None:
        return {"briefing": None}
    return {"briefing": snap}


MARKET_TOOLS = [
    get_market_indices,
    refresh_market,
    get_market_snapshot_auto,
    get_sector_heatmap,
    get_latest_market_brief,
    search_market_evidence,
    search_cls_telegraph,
    get_market_briefing,
]
