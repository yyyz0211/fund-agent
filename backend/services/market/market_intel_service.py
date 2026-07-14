"""市场情报编排服务。

编排: 采集全量市场情报 → upsert MarketSnapshot → 返回 dict。
单项失败不影响整体，降级展示。

写入路径拆 fetch + write:
- `_fetch_snapshot_payload` 完成所有 akshare 网络拉取(含各 index / sector
  history 注入),无 DB 调用,可在事务外执行,避免 akshare 慢响应时长事务
  持有锁。
- `collect_market_intel` 在 `_fetch_snapshot_payload` 之后开短事务完成
  upsert;外部传入 session 时沿用其事务,不再 commit/close。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any

from sqlalchemy import select

from backend.db.models import MarketSnapshot
from backend.db.repository import upsert_market_snapshot
from backend.db.session_scope import session_scope
from backend.services.market import data_collector as dc
from backend.services.market import market_service


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


def _enrich_and_build_payload(
    trade_date: str,
    snapshot_type: str,
    *,
    indices,
    breadth,
    industry_sectors,
    industry_flows,
    concept_sectors,
    concept_flows,
    themes,
    breadth_indicators,
    overseas,
    announcements,
    errors: list[dict],
) -> dict:
    """给已 fetch 的字段注入 history,组装 payload(不含 stale_fields/errors)。

    `errors` 累计由 `_collect_field` 内部 append。无 DB 调用。
    """

    def _collect_field(name: str, fn, *args, **kwargs) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            errors.append({"field": name, "error": str(exc)})
            return None

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

    return {
        "trade_date": trade_date,
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
        "as_of": trade_date,
    }


def _build_payload_with_stale(
    trade_date: str,
    snapshot_type: str,
    errors: list[dict],
    *,
    indices,
    breadth,
    industry_sectors,
    industry_flows,
    concept_sectors,
    concept_flows,
    themes,
    breadth_indicators,
    overseas,
    announcements,
) -> dict:
    """组装 payload 并补全 stale_fields/errors。"""
    payload = _enrich_and_build_payload(
        trade_date, snapshot_type,
        indices=indices, breadth=breadth,
        industry_sectors=industry_sectors, industry_flows=industry_flows,
        concept_sectors=concept_sectors, concept_flows=concept_flows,
        themes=themes, breadth_indicators=breadth_indicators,
        overseas=overseas, announcements=announcements,
        errors=errors,
    )
    payload["stale_fields"] = _compute_stale_fields(
        payload["industry_sectors"], payload["concept_sectors"],
        payload["industry_flows"], payload["concept_flows"],
        payload["themes"], payload["overseas"], payload["announcements"],
    )
    payload["errors"] = errors
    return payload


def collect_market_intel(
    trade_date: str | None = None,
    snapshot_type: str = "post_market",
    session=None,
) -> dict:
    """采集全量市场情报,upsert MarketSnapshot,返回 dict。

    单项失败记录到 errors 列表,整体继续。

    事务边界:
    - 网络拉取(akshare)全部在事务外执行,见函数体内的
      `ThreadPoolExecutor(max_workers=1)` 块及后续 `_enrich_and_build_payload`。
    - upsert 在调用方传入 session 时沿用其事务,只在 session=None 时
      开 `session_scope()` 短事务(自动 commit/close)。
    - 任何 DB 错误不抛 — 记入 `payload["db_error"]`,网络 payload
      已收集的内容仍返回给调用方。
    """
    td = trade_date or _today()
    errors: list[dict] = []

    # 阶段 1:网络拉取,无事务、无 DB 调用。
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

        def _gather(name: str, fut) -> Any:
            try:
                return fut.result()
            except Exception as exc:  # noqa: BLE001
                errors.append({"field": name, "error": str(exc)})
                return None

        indices = _gather("indices", f_indices)
        breadth = _gather("breadth", f_breadth)
        industry_sectors = _gather("industry_sectors", f_industry)
        industry_flows = _gather("industry_flows", f_industry_flows)
        concept_sectors = _gather("concept_sectors", f_concept)
        concept_flows = _gather("concept_flows", f_concept_flows)
        themes = _gather("themes", f_themes)
        breadth_indicators = _gather("breadth_indicators", f_breadth_indicators)
        overseas = _gather("overseas", f_overseas)
        announcements = _gather("announcements", f_announcements)

    # 阶段 1b:补 history + 组 payload(无 DB 调用)
    payload = _build_payload_with_stale(
        td, snapshot_type, errors,
        indices=indices, breadth=breadth,
        industry_sectors=industry_sectors, industry_flows=industry_flows,
        concept_sectors=concept_sectors, concept_flows=concept_flows,
        themes=themes, breadth_indicators=breadth_indicators,
        overseas=overseas, announcements=announcements,
    )

    # 阶段 2:写 DB(upsert),短事务;传入 session 时只 flush,不开新事务。
    try:
        if session is None:
            with session_scope() as s:
                upsert_market_snapshot(s, td, snapshot_type, payload)
        else:
            upsert_market_snapshot(session, td, snapshot_type, payload)
    except Exception as exc:  # noqa: BLE001
        payload["db_error"] = str(exc)

    return payload


def get_market_snapshot(
    trade_date: str | None = None,
    snapshot_type: str = "post_market",
    session=None,
) -> dict:
    """从 DB 读取 MarketSnapshot;不存在则触发采集。

    session=None 时自行 `session_scope()` 管理事务边界;
    传入 session 时只读 + flush,不 commit/close。
    """
    td = trade_date or _today()
    if session is None:
        with session_scope() as s:
            return get_market_snapshot(td, snapshot_type, session=s)

    row = session.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.trade_date == td,
            MarketSnapshot.snapshot_type == snapshot_type,
        )
    )
    if row is None:
        # 不存在则触发采集,沿用本 session
        return collect_market_intel(td, snapshot_type, session=session)
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