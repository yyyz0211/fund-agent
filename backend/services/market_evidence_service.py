"""market_evidence_service: 业务侧 service 层 - 路由 / tool / scheduler 共用。

公开函数:
- `search_evidence(*, trade_date, category, query, limit, session)`
- `refresh_market_evidence_async(*, brief_type, trigger)`
- `collect_and_run_for_brief_type(brief_type, trade_date, sector_snapshot)`
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any

from backend.db.repository import search_market_evidence
from backend.db.session import get_session
from backend.services import market_evidence_ingestion as ing
from backend.services.market_sources import build_default_adapters

logger = logging.getLogger(__name__)


# ---- 单飞异步执行器 (与 market_intel_service 一致模式) ------------------------
_lock = Lock()
_active_job_ids: dict[str, str] = {}
_async_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-evidence")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def search_evidence(
    *,
    trade_date: str | None = None,
    category: str | None = None,
    query: str | None = None,
    limit: int = 50,
    session=None,
) -> list[dict]:
    """包装 repository.search_market_evidence。"""
    td = trade_date or _today()
    owns = session is None
    s = session or get_session()
    try:
        return search_market_evidence(
            s, trade_date=td,
            category=category or None,
            query=(query or "").strip() or None,
            limit=limit,
        )
    finally:
        if owns:
            s.close()


def collect_and_run_for_brief_type(
    brief_type: str,
    *,
    trade_date: str | None = None,
    sector_snapshot: dict | None = None,
    session=None,
) -> dict:
    """调度入口：构造全量 adapter, 跑 ingestion。

    Args:
        brief_type: "pre_market" / "post_market"
        trade_date: 留空取今天
        sector_snapshot: SectorHeatAdapter 需要的当日 industry_sectors 列表;
            传 None 时跳过 sector 类别 (默认 post_market 才启用 sector)
        session: 可选 session
    """
    td = trade_date or _today()
    try:
        client = __import__("httpx").Client(timeout=10.0, follow_redirects=True)
    except Exception:
        client = None
    adapters = build_default_adapters(
        client=client, brief_type=brief_type, sector_snapshot=sector_snapshot
    )
    try:
        return ing.ingest_market_evidence(
            trade_date=td, brief_type=brief_type,
            adapters=adapters, session=session,
        )
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def refresh_market_evidence_async(
    *, brief_type: str = "post_market",
    trigger: str = "manual",
) -> dict:
    """后台异步采集。同 brief_type 单飞: 已有任务在跑时返回 running, 不重复触发。"""
    global _active_job_ids
    import uuid

    with _lock:
        if brief_type in _active_job_ids:
            return {"status": "running", "brief_type": brief_type,
                    "job_id": _active_job_ids[brief_type]}
        job_id = uuid.uuid4().hex[:8]
        _active_job_ids[brief_type] = job_id

    def _task():
        global _active_job_ids
        try:
            # 抓 sector heat 所需的 industry_sectors
            sector_snapshot: dict | None = None
            if brief_type == "post_market":
                try:
                    from backend.services import data_collector as dc
                    sector_snapshot = {"industry_sectors": dc.fetch_sector_snapshot(limit_n=20)}
                except Exception as exc:
                    logger.warning(
                        "market_evidence: sector_snapshot 获取失败, brief_type=%s err=%s",
                        brief_type, exc,
                    )
                    sector_snapshot = None
            result = collect_and_run_for_brief_type(brief_type, sector_snapshot=sector_snapshot)
            logger.info(
                "market_evidence: brief_type=%s job_id=%s result=%s",
                brief_type, job_id, result,
            )
        except Exception as exc:
            # 不再 silent-pass — 至少写日志, 让 uvicorn stderr 能看到失败原因。
            logger.exception(
                "market_evidence: brief_type=%s job_id=%s 异步采集失败: %s",
                brief_type, job_id, exc,
            )
        finally:
            with _lock:
                _active_job_ids.pop(brief_type, None)

    _async_executor.submit(_task)
    return {"status": "started", "trigger": trigger, "brief_type": brief_type, "job_id": job_id}