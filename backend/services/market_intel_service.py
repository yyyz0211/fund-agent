"""市场情报编排服务。

编排: 采集全量市场情报 → upsert MarketSnapshot → 返回 dict。
单项失败不影响整体，降级展示。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any

from backend.db.models import MarketSnapshot
from backend.db.session import get_session
from backend.db.repository import upsert_market_snapshot
from backend.services import data_collector as dc
from backend.services import market_service


_lock = Lock()
_active_job_id: str | None = None
_async_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-intel")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _safe(d: Any, key: str, default=None) -> Any:
    if isinstance(d, dict):
        return d.get(key, default)
    return default


# 字段名常量,避免 stale_fields 的拼写漂移
_STALE_FIELDS = (
    "industry_sectors", "concept_sectors", "industry_flows",
    "concept_flows", "themes", "overseas", "announcements",
)


def _compute_stale_fields(
    industry_sectors, concept_sectors, industry_flows, concept_flows,
    themes, overseas, announcements,
) -> dict[str, bool]:
    """根据 list 字段是否非空生成 staleness 标记。

    DB 命中路径复用同一份逻辑,避免 collection path 计算了 stale 标记但
    read path 漏掉,导致前端在缓存命中时永远看不到"网络问题"提示。
    """
    values = {
        "industry_sectors": industry_sectors,
        "concept_sectors": concept_sectors,
        "industry_flows": industry_flows,
        "concept_flows": concept_flows,
        "themes": themes,
        "overseas": overseas,
        "announcements": announcements,
    }
    return {k: not (isinstance(v, list) and v) for k, v in values.items()}


def collect_market_intel(
    trade_date: str | None = None,
    snapshot_type: str = "post_market",
    session=None,
) -> dict:
    """采集全量市场情报，upsert MarketSnapshot，返回 dict。

    单项失败记录到 errors 列表，整体继续。
    """
    td = trade_date or _today()
    errors: list[dict] = []

    def _collect_field(name: str, fn, *args, **kwargs) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            errors.append({"field": name, "error": str(exc)})
            return None

    # 串行采集 (max_workers=1)
    # 历史原因: 之前用 max_workers=6 并行, 在 akshare 1.18 + libmini_racer 0.14 下
    #   触发 `FATAL:address_pool_manager.cc(67) Check failed: !pool->IsInitialized()`,
    #   uvicorn worker 进程崩, Next.js proxy 收到 ECONNRESET。
    # 现在 `data_collector.AKSHARE_LOCK` 已经在 fetch_* 入口全局串行化 akshare,
    #   外层再并行没意义, 反而让 race 风险窗口变大。统一改成 1 路串行。
    with ThreadPoolExecutor(max_workers=1) as ex:
        f_indices = ex.submit(market_service.get_indices)
        f_breadth = ex.submit(dc.fetch_market_breadth)
        f_industry = ex.submit(dc.fetch_sector_snapshot)
        f_industry_flows = ex.submit(dc.fetch_industry_flows)
        f_concept = ex.submit(dc.fetch_concept_sectors)
        f_concept_flows = ex.submit(dc.fetch_concept_flows)
        f_themes = ex.submit(dc.fetch_theme_boards)
        f_breadth_indicators = ex.submit(dc.fetch_breadth_indicators)
        f_overseas = ex.submit(dc.fetch_overseas_markets)
        f_announcements = ex.submit(dc.fetch_announcements)

        indices = _collect_field("indices", lambda: f_indices.result())
        breadth = _collect_field("breadth", lambda: f_breadth.result())
        industry_sectors = _collect_field("industry_sectors", lambda: f_industry.result())
        industry_flows = _collect_field("industry_flows", lambda: f_industry_flows.result())
        concept_sectors = _collect_field("concept_sectors", lambda: f_concept.result())
        concept_flows = _collect_field("concept_flows", lambda: f_concept_flows.result())
        themes = _collect_field("themes", lambda: f_themes.result())
        breadth_indicators = _collect_field("breadth_indicators", lambda: f_breadth_indicators.result())
        overseas = _collect_field("overseas", lambda: f_overseas.result())
        announcements = _collect_field("announcements", lambda: f_announcements.result())

    # 给指数注入近 30 日收盘价序列(history)。失败记录到 errors,不影响整体。
    indices_list = (indices or {}).get("indices", []) if isinstance(indices, dict) else (indices or [])
    for idx in indices_list:
        sym = idx.get("symbol")
        if not sym:
            continue
        hist = _collect_field(f"index_history:{sym}", dc.fetch_index_history, sym, 30)
        if isinstance(hist, list) and hist:
            idx["history"] = [float(p["close"]) for p in hist if p.get("close") is not None]
        else:
            idx["history"] = None
            if isinstance(hist, dict) and "error" in hist:
                errors.append({"field": f"index_history:{sym}", "error": hist["error"]})

    # 给行业/概念板块注入近 10 日涨跌幅序列(history)。
    for s in (industry_sectors or []):
        nm = s.get("name")
        if not nm:
            continue
        hist = _collect_field(f"industry_history:{nm}", dc.fetch_sector_history, nm, "industry", 10)
        if isinstance(hist, list) and hist:
            s["history"] = [float(p["change_pct"]) for p in hist if p.get("change_pct") is not None]
        else:
            s["history"] = None
            if isinstance(hist, dict) and "error" in hist:
                errors.append({"field": f"industry_history:{nm}", "error": hist["error"]})

    for s in (concept_sectors or []):
        nm = s.get("name")
        if not nm:
            continue
        hist = _collect_field(f"concept_history:{nm}", dc.fetch_sector_history, nm, "concept", 10)
        if isinstance(hist, list) and hist:
            s["history"] = [float(p["change_pct"]) for p in hist if p.get("change_pct") is not None]
        else:
            s["history"] = None
            if isinstance(hist, dict) and "error" in hist:
                errors.append({"field": f"concept_history:{nm}", "error": hist["error"]})

    payload = {
        "trade_date": td,
        "snapshot_type": snapshot_type,
        "indices": _safe(indices, "indices", []) if indices else [],
        "breadth": breadth if isinstance(breadth, dict) else {},
        "industry_sectors": industry_sectors if isinstance(industry_sectors, list) else [],
        "concept_sectors": concept_sectors if isinstance(concept_sectors, list) else [],
        "industry_flows": industry_flows if isinstance(industry_flows, list) else [],
        "concept_flows": concept_flows if isinstance(concept_flows, list) else [],
        "themes": themes if isinstance(themes, list) else [],
        "breadth_indicators": breadth_indicators if isinstance(breadth_indicators, dict) else {},
        "overseas": overseas if isinstance(overseas, list) else [],
        "announcements": announcements if isinstance(announcements, list) else [],
        # 字段级 staleness 标记:外网接口拉取失败 / 返回空时,标 True。
        # 前端应根据此字段决定是否显示"网络问题"提示,而不是"暂无数据"。
        "stale_fields": _compute_stale_fields(
            industry_sectors, concept_sectors, industry_flows, concept_flows,
            themes, overseas, announcements,
        ),
        "as_of": td,
        "errors": errors,
    }

    # 写 DB（upsert）
    try:
        owns = session is None
        s = session or get_session()
        try:
            upsert_market_snapshot(s, td, snapshot_type, payload)
            s.commit()
        finally:
            if owns:
                s.close()
    except Exception as exc:  # noqa: BLE001
        payload["db_error"] = str(exc)

    return payload


def get_market_snapshot(
    trade_date: str | None = None,
    snapshot_type: str = "post_market",
    session=None,
) -> dict:
    """从 DB 读取 MarketSnapshot；不存在则触发采集。"""
    td = trade_date or _today()
    owns = session is None
    s = session or get_session()
    try:
        from sqlalchemy import select
        row = s.scalar(
            select(MarketSnapshot).where(
                MarketSnapshot.trade_date == td,
                MarketSnapshot.snapshot_type == snapshot_type,
            )
        )
        if row is None:
            # 不存在则触发采集
            return collect_market_intel(td, snapshot_type, session=s)
        # 从 DB 读出 path 不存 stale_fields — 在读出时基于 list 字段是否非空实时重算。
        # 这样即使写 path 是 1 周前的、当时 industry 没拉到,DB 命中时 UI 仍能提示"网络问题"。
        industry = json.loads(row.industry_sectors_json or "[]")
        concept = json.loads(row.concept_sectors_json or "[]")
        industry_flows = json.loads(row.industry_flows_json or "[]")
        concept_flows = json.loads(row.concept_flows_json or "[]")
        themes = json.loads(row.themes_json or "[]")
        overseas = json.loads(row.overseas_json or "[]")
        announcements = json.loads(row.announcements_json or "[]")
        return {
            "trade_date": row.trade_date,
            "snapshot_type": row.snapshot_type,
            "indices": json.loads(row.indices_json or "[]"),
            "breadth": json.loads(row.breadth_json or "{}"),
            "industry_sectors": industry,
            "concept_sectors": concept,
            "industry_flows": industry_flows,
            "concept_flows": concept_flows,
            "themes": themes,
            "breadth_indicators": json.loads(row.breadth_indicators_json or "{}"),
            "overseas": overseas,
            "announcements": announcements,
            "stale_fields": _compute_stale_fields(
                industry, concept, industry_flows, concept_flows,
                themes, overseas, announcements,
            ),
            "source": row.source,
            "as_of": row.as_of,
        }
    finally:
        if owns:
            s.close()


def refresh_market_intel_async(*, trigger: str = "manual", target_date: str | None = None) -> dict:
    """后台异步采集，返回 job 状态。

    Args:
        trigger: 触发来源（manual / cron 等），记日志用。
        target_date: 采集目标交易日 YYYY-MM-DD；None = 抓今天。
                      UI 选"昨日"刷新时传进来,确保回填的是那天的数据。
    """
    from datetime import date as _date
    td_str: str
    if target_date:
        try:
            td_str = _date.fromisoformat(target_date).isoformat()
        except ValueError:
            td_str = _today()
    else:
        td_str = _today()

    global _active_job_id
    with _lock:
        if _active_job_id is not None:
            return {"status": "running", "job_id": _active_job_id}
        import uuid
        job_id = uuid.uuid4().hex[:8]
        _active_job_id = job_id

    def _task():
        global _active_job_id
        try:
            collect_market_intel(td_str, "post_market")
        finally:
            with _lock:
                _active_job_id = None

    _async_executor.submit(_task)
    return {"status": "started", "trigger": trigger, "job_id": job_id, "target_date": td_str}
