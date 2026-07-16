"""Briefing collectors: 快照与证据收集。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.config import settings as app_settings
from backend.services.fund import fund_service
from backend.services.market import data_collector as dc
from backend.services.market import market_evidence_service
from backend.services.market import market_service
from backend.services.watchlist import watchlist_service

collect_and_run_for_brief_type = market_evidence_service.collect_and_run_for_brief_type
search_evidence = market_evidence_service.search_evidence

# Wave 1: 数据质量维度候选池
_DATA_DIMENSIONS = (
    "indices",
    "breadth",
    "industry_sectors",
    "industry_flows",
    "concept_sectors",
    "concept_flows",
    "overseas",
    "themes",
    "announcements",
    "policy_evidence",
    "announcement_evidence",
    "macro_evidence",
)


def compute_data_quality(snapshot: dict, evidence: list[dict]) -> dict:
    """根据 snapshot + evidence 计算 data_quality / confidence / missing_data。

    规则:
    - 所有 indices / breadth / industry_sectors / overseas / evidence≥1 齐 + collect_errors 空 → complete / high
    - 只有 indices + sectors,evidence=0,overseas 空 → partial / medium
    - 只有 market_snapshot.indices,其他缺 → market_only / low
    - snapshot 整体为空 → failed / low
    """
    market_snapshot = snapshot.get("market_snapshot") or []
    breadth = snapshot.get("market_breadth") or {}
    sectors = snapshot.get("industry_sectors") or []
    overseas_keys_present = bool(breadth)
    errors = snapshot.get("errors") or []
    evidence_count = len(evidence or [])
    collect_meta = snapshot.get("collect_meta") or {}
    data_sources = collect_meta.get("data_sources_last_updated") or {}

    has_indices = bool(market_snapshot)
    has_sectors = bool(sectors)
    has_overseas = isinstance(snapshot.get("industry_sectors"), list)  # placeholder
    missing: list[str] = []
    failed_modules: list[dict] = []

    if not has_indices:
        missing.append("indices")
    if not breadth:
        missing.append("breadth")
    if not has_sectors:
        missing.append("industry_sectors")
    # evidence by category
    by_cat: dict[str, int] = {}
    for e in evidence or []:
        cat = e.get("category")
        if cat:
            by_cat[cat] = by_cat.get(cat, 0) + 1
    if by_cat.get("policy", 0) == 0:
        missing.append("policy_evidence")
    if by_cat.get("announcement", 0) == 0:
        missing.append("announcement_evidence")
    if by_cat.get("macro", 0) == 0:
        missing.append("macro_evidence")

    # 单项采集错误记入 failed_modules
    for err in errors:
        failed_modules.append({
            "module": "watchlist_metrics",
            "fund_code": err.get("fund_code"),
            "reason": err.get("message", "未知错误"),
        })

    if not market_snapshot and not sectors and not evidence_count and errors:
        return {
            "data_quality": "failed",
            "confidence": "low",
            "missing_data": list(_DATA_DIMENSIONS),
            "failed_modules": failed_modules,
            "data_sources_last_updated": data_sources,
        }

    if has_indices and has_sectors and evidence_count > 0 and not errors:
        quality = "complete"
        confidence = "high"
    elif has_indices and (has_sectors or breadth) and not errors:
        quality = "partial"
        confidence = "medium"
    elif has_indices:
        quality = "market_only"
        confidence = "low"
    else:
        quality = "failed"
        confidence = "low"

    return {
        "data_quality": quality,
        "confidence": confidence,
        "missing_data": missing,
        "failed_modules": failed_modules,
        "data_sources_last_updated": data_sources,
    }


settings = app_settings.get_settings()


def _get_settings():
    return app_settings.get_settings()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _lookup_fund_name(fund_code: str, session) -> str:
    """从本地 Fund 表读名字; 表里没有时回空串。

    briefing_service 用,避免每行 metrics 都重复查 (N+1)。
    不传 session 时直接返回空串(测试场景)。
    """
    if session is None:
        return ""
    try:
        from backend.db.models import Fund
        from sqlalchemy import select
        name = session.scalar(
            select(Fund.fund_name).where(Fund.fund_code == fund_code)
        )
        return name or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 数据收集
# ---------------------------------------------------------------------------

def collect_watchlist_snapshot(*, fund_codes: list[str] | None = None,
                                session=None) -> dict:
    """拉指数 + 自选池 metrics。

    Args:
        fund_codes: 可选，只处理这些基金；None → 全自选池。
        session: 可选，外部传入 session 用于测试。

    Returns:
        dict，含 keys:
        - market_snapshot: list[dict]  指数行
        - watchlist_changes: list[dict]  每只基金的周期收益
        - errors: list[dict]  单项错误记录
        - collect_meta: dict  {max_funds_applied, total_watchlist, warnings}
    """
    warnings: list[str] = []
    errors: list[dict] = []
    watchlist_changes: list[dict] = []

    # 1) market snapshot
    try:
        market_result = _collect_market_snapshot()
    except Exception as exc:
        market_result = {"indices": [], "error": str(exc)}

    # 2) 自选池
    rows = watchlist_service.list_watchlist(session=session)
    if fund_codes is not None:
        rows = [r for r in rows if r["fund_code"] in set(fund_codes)]

    max_funds = getattr(settings, "briefing_max_watchlist_funds", 30)
    total_watchlist = len(rows)
    if total_watchlist > max_funds:
        rows = rows[:max_funds]
        warnings.append(f"自选池共 {total_watchlist} 只，已截断至前 {max_funds} 只。")

    # 3) 每只基金 metrics
    for row in rows:
        fund_code = row["fund_code"]
        # watchlist.fund_name 由 watchlist repository 投影返回,
        # 启动时 init_db() 自动从 funds.fund_name 回填, 这里只需 .get 兜底。
        # 极端情况下(用户 sync 进 watchlist 但 fund 表还没数据)再走一次 inline 查找,
        # 避免简报里出现 fund_code 占位。
        fund_name = row.get("fund_name") or _lookup_fund_name(fund_code, session)
        try:
            metrics_1d = fund_service.get_metrics(fund_code, period="1d", session=session)
            metrics_1w = fund_service.get_metrics(fund_code, period="1w", session=session)
            metrics_1m = fund_service.get_metrics(fund_code, period="1m", session=session)
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "fund_code": fund_code,
                "stage": "collect",
                "message": str(exc),
            })
            continue
        watchlist_changes.append({
            "fund_code": fund_code,
            "fund_name": fund_name,
            "period_returns": {
                "1d": _safe_get(metrics_1d, "period_return"),
                "1w": _safe_get(metrics_1w, "period_return"),
                "1m": _safe_get(metrics_1m, "period_return"),
            },
            "source": "akshare",
            "as_of": _today(),
        })

    # 4) 市场宽度（涨跌家数 / 涨跌停 / 成交额）
    try:
        breadth = _collect_market_breadth()
    except Exception:  # noqa: BLE001
        breadth = {}

    # 5) 板块涨跌快照
    try:
        sector_snapshot = _collect_sector_snapshot()
    except Exception:  # noqa: BLE001
        sector_snapshot = []

    # 6) 行业板块资金流向
    try:
        industry_flows = dc.fetch_industry_flows()
    except Exception:  # noqa: BLE001
        industry_flows = []

    # 7) 概念板块涨跌幅
    try:
        concept_sectors = dc.fetch_concept_sectors()
    except Exception:  # noqa: BLE001
        concept_sectors = []

    # 8) 概念板块资金流向
    try:
        concept_flows = dc.fetch_concept_flows()
    except Exception:  # noqa: BLE001
        concept_flows = []

    # 9) 各数据源最后更新时间（统一用当前时间）
    now_iso = datetime.now().isoformat(timespec="seconds")

    return {
        "market_snapshot": market_result.get("indices", []),
        "market_breadth": breadth,
        "industry_sectors": sector_snapshot,
        "industry_flows": industry_flows,
        "concept_sectors": concept_sectors,
        "concept_flows": concept_flows,
        "sector_snapshot": sector_snapshot,
        "watchlist_changes": watchlist_changes,
        "errors": errors,
        "collect_meta": {
            "total_watchlist": total_watchlist,
            "max_funds_applied": max_funds if total_watchlist > max_funds else None,
            "warnings": warnings,
            "data_sources_last_updated": {
                "market_snapshot": now_iso,
                "market_breadth": now_iso,
                "industry_sectors": now_iso,
                "concept_sectors": now_iso,
            },
        },
    }


def _collect_market_snapshot():
    """拉最新交易日指数，返回 {indices, source, as_of} 或 {error}。"""
    return market_service.get_indices()


def _collect_market_breadth() -> dict:
    """拉市场宽度（涨跌家数/涨跌停/成交额）。"""
    return dc.fetch_market_breadth()


def _collect_sector_snapshot() -> list[dict]:
    """拉行业板块涨跌幅 top/bottom。"""
    return dc.fetch_sector_snapshot()


def _safe_get(d: Any, key: str, default=None) -> Any:
    if isinstance(d, dict):
        return d.get(key, default)
    return default


__all__ = [
    "collect_and_run_for_brief_type",
    "collect_watchlist_snapshot",
    "compute_data_quality",
    "search_evidence",
]
