"""市场数据 LangChain 工具。

这里保持薄包装原则:LLM 不能直接访问数据库/API,只能通过这些受控 tool
读取已经结构化过的市场数据。
"""
from __future__ import annotations

from langchain_core.tools import tool
from sqlalchemy import select

from backend.db.models import Briefing
from backend.db.session import get_session
from backend.services import market_evidence_service as mev
from backend.services import market_intel_service as mintel
from backend.services import market_service as msvc


def _limit(value: int, *, default: int = 5, max_value: int = 20) -> int:
    try:
        parsed = int(value)
    except Exception:
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
        name = _flow_key(row)
        flow = flow_map.get(name, {})
        item = dict(row)
        if "net_flow" not in item:
            item["net_flow"] = flow.get("net_flow")
        merged.append(item)
    return merged


def _sort_rows(rows: list[dict], sort: str) -> list[dict]:
    if sort == "flow":
        return sorted(
            rows,
            key=lambda row: abs(float(row.get("net_flow") or 0)),
            reverse=True,
        )
    return sorted(
        rows,
        key=lambda row: abs(float(row.get("change_pct") or 0)),
        reverse=True,
    )


def _top_rows(rows: list[dict], *, limit: int, sort: str = "change_pct") -> list[dict]:
    return _sort_rows(rows, sort)[:limit]


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
) -> dict:
    """获取市场情报快照，适合回答"今天大盘/市场怎么样"。

    `date` 为空时使用今天；`snapshot_type` 支持 `morning` / `post_market`。
    返回会裁剪 top 行业/概念/公告，避免把过大的市场快照塞给 LLM。
    """
    lim = _limit(limit)
    snapshot = mintel.get_market_snapshot(
        trade_date=date or None,
        snapshot_type=snapshot_type,
    )
    industry = _merge_flows(
        _safe_list(snapshot.get("industry_sectors")),
        _safe_list(snapshot.get("industry_flows")),
    )
    concept = _merge_flows(
        _safe_list(snapshot.get("concept_sectors")),
        _safe_list(snapshot.get("concept_flows")),
    )
    return {
        "trade_date": snapshot.get("trade_date") or date or "",
        "snapshot_type": snapshot.get("snapshot_type") or snapshot_type,
        "indices": _safe_list(snapshot.get("indices"))[:lim],
        "breadth": snapshot.get("breadth") if isinstance(snapshot.get("breadth"), dict) else {},
        "top_industry_sectors": _top_rows(industry, limit=lim),
        "top_concept_sectors": _top_rows(concept, limit=lim),
        "overseas": _safe_list(snapshot.get("overseas"))[:lim],
        "announcements": _safe_list(snapshot.get("announcements"))[:lim],
        "errors": _safe_list(snapshot.get("errors")),
        "source": snapshot.get("source") or "akshare",
        "as_of": snapshot.get("as_of") or snapshot.get("trade_date") or date or "",
    }


@tool
def get_sector_heatmap(
    kind: str = "industry",
    sort: str = "change_pct",
    limit: int = 10,
    date: str = "",
    snapshot_type: str = "post_market",
) -> dict:
    """获取行业/概念板块强弱和资金流，适合回答"某板块今天怎么样"。

    `kind ∈ {"industry","concept"}`；`sort ∈ {"change_pct","flow"}`。
    若没有可验证的新闻/政策证据，只能说明行情表现，不能编造涨跌原因。
    """
    normalized_kind = "concept" if kind == "concept" else "industry"
    normalized_sort = "flow" if sort == "flow" else "change_pct"
    lim = _limit(limit, default=10)
    snapshot = mintel.get_market_snapshot(
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
        "rows": _top_rows(rows, limit=lim, sort=normalized_sort),
        "source": snapshot.get("source") or "akshare",
        "as_of": snapshot.get("as_of") or snapshot.get("trade_date") or date or "",
        "missing_evidence_note": "该工具只返回行情强弱与资金流，不包含新闻/政策催化证据。",
    }


@tool
def get_latest_market_brief() -> dict:
    """获取最近一篇本地市场/基金简报，适合回答"今日简报/市场总结"。"""
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
    query: str,
    date: str = "",
    category: str = "",
    limit: int = 5,
) -> dict:
    """搜索本地市场证据，适合回答"为什么涨/跌/政策催化是什么"。

    返回的 evidence 每条都带 source/source_url/published_at。没有结果时,
    必须说明本地证据不足，不能确认催化原因。
    """
    rows = mev.search_evidence(
        query=query,
        trade_date=date,
        category=category,
        limit=_limit(limit, default=5),
    )
    return {
        "query": query,
        "trade_date": date,
        "category": category,
        "evidence": rows,
        "source": "local_market_evidence",
        "as_of": rows[0]["published_at"] if rows else date,
        "missing_evidence_note": (
            "" if rows else "本地证据不足，不能确认催化原因；只能描述已采集到的行情事实。"
        ),
    }


MARKET_TOOLS = [
    get_market_indices,
    refresh_market,
    get_market_snapshot_auto,
    get_sector_heatmap,
    get_latest_market_brief,
    search_market_evidence,
]
