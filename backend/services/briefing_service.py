"""每日基金简报编排服务。

编排流程:collect_watchlist_snapshot(指数 + 自选池 metrics)
       → compose_briefing(DeepSeek 生成 markdown + 结构化 sections)
       → upsert Briefing 表
       → 写内存快照。

简报不走 LangGraph / qa_graph，不经过 policy.py 合规检查。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any

from backend.config import settings as app_settings
from backend.db.models import Briefing
from backend.db.session import get_session
from backend.graph.model import build_model
from backend.services import market_service, watchlist_service, fund_service


_lock = Lock()
_last_run: dict = {}
settings = app_settings.get_settings()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _empty_snapshot() -> dict:
    return {
        "last_run_at": None,
        "trigger": None,
        "total_funds": 0,
        "succeeded": 0,
        "failed": 0,
        "failures": [],
    }


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
        fund_name = row.get("fund_name", "")
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

    return {
        "market_snapshot": market_result.get("indices", []),
        "watchlist_changes": watchlist_changes,
        "errors": errors,
        "collect_meta": {
            "total_watchlist": total_watchlist,
            "max_funds_applied": max_funds if total_watchlist > max_funds else None,
            "warnings": warnings,
        },
    }


def _collect_market_snapshot():
    """拉最新交易日指数，返回 {indices, source, as_of} 或 {error}。"""
    return market_service.get_indices()


def _safe_get(d: Any, key: str, default=None) -> Any:
    if isinstance(d, dict):
        return d.get(key, default)
    return default


# ---------------------------------------------------------------------------
# 简报合成
# ---------------------------------------------------------------------------

def compose_briefing(snapshot: dict) -> dict:
    """调用 DeepSeek 把 snapshot 合成 markdown + sections。

    Returns:
        dict，含 keys: markdown, sections, warnings, llm_model, prompt_used_chars
    """
    from backend.graph.prompts import BRIEFING_PROMPT_TEMPLATE

    warnings: list[str] = []
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    prompt = BRIEFING_PROMPT_TEMPLATE.format(snapshot_json=snapshot_json)

    model = build_model()
    response = model.invoke(prompt)
    raw_content = response.content if hasattr(response, "content") else str(response)

    # 尝试解析 JSON
    try:
        parsed = json.loads(raw_content)
        markdown = parsed.get("markdown", raw_content)
        sections = parsed.get("sections", {})
    except (json.JSONDecodeError, TypeError):
        warnings.append("llm_returned_non_json，使用原始文本作为 markdown")
        markdown = raw_content
        sections = {}

    return {
        "markdown": markdown,
        "sections": sections,
        "warnings": warnings,
        "llm_model": getattr(settings, "briefing_llm_model", "deepseek-chat"),
        "prompt_used_chars": len(prompt),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_daily_briefing(*, trigger: str = "scheduled", session=None) -> dict:
    """编排: collect → compose → upsert Briefing → 写内存快照。

    绝不抛异常。单步失败记入 failures，整批继续。
    """
    from backend.db.repository import upsert_briefing

    snapshot: dict = {}
    compose_result: dict = {}
    failures: list[dict] = []
    succeeded = 0
    failed = 0

    # collect
    try:
        snapshot = collect_watchlist_snapshot(session=session)
    except Exception as exc:  # noqa: BLE001
        failures.append({"stage": "collect", "message": str(exc)})
        failed += 1

    # collect 单项 errors 也计入 failed（按 fund_code 维度）
    collect_errors = snapshot.get("errors", []) if snapshot else []
    for ce in collect_errors:
        failures.append({
            "stage": "collect",
            "fund_code": ce.get("fund_code"),
            "message": ce.get("message"),
        })
        failed += 1

    # compose
    if snapshot.get("watchlist_changes") or snapshot.get("market_snapshot"):
        try:
            compose_result = compose_briefing(snapshot)
            succeeded = 1
        except Exception as exc:  # noqa: BLE001
            failures.append({"stage": "llm", "message": str(exc)})
            failed += 1
    else:
        compose_result = {
            "markdown": "（今日自选池为空，无涨跌数据。）",
            "sections": {},
            "warnings": [],
            "llm_model": getattr(settings, "briefing_llm_model", "deepseek-chat"),
        }

    today = _today()
    sections_json = json.dumps(compose_result.get("sections", {}), ensure_ascii=False)

    payload = {
        "title": f"每日基金简报 {today}",
        "markdown": compose_result.get("markdown", ""),
        "sections_json": sections_json,
        "source": "akshare + deepseek",
        "as_of": today,
    }

    try:
        owns = session is None
        s = session or get_session()
        try:
            upsert_briefing(s, briefing_date=today, payload=payload)
            s.commit()
        finally:
            if owns:
                s.close()
    except Exception as exc:  # noqa: BLE001
        failures.append({"stage": "db_upsert", "message": str(exc)})
        failed += 1

    # 写内存快照
    total_funds = len(snapshot.get("watchlist_changes", []))
    snap = {
        "last_run_at": _now(),
        "trigger": trigger,
        "total_funds": total_funds,
        "succeeded": succeeded,
        "failed": failed,
        "failures": failures,
    }
    with _lock:
        _last_run.clear()
        _last_run.update(snap)
    return snap


def get_last_run() -> dict:
    """返回最近一次简报生成快照；从未跑过返回全零快照。"""
    with _lock:
        if not _last_run or _last_run.get("last_run_at") is None:
            return _empty_snapshot()
        return dict(_last_run)


def reset_for_tests() -> None:
    """仅测试用:清空内存快照。"""
    global _last_run
    with _lock:
        _last_run.clear()


# ---------------------------------------------------------------------------
# 异步触发(供 API 用)
# ---------------------------------------------------------------------------

_active_lock = Lock()
_active_job_id: str | None = None
_async_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="briefing-run")


def start_run_async(*, trigger: str = "manual") -> dict:
    """后台线程触发一次简报生成,立即返回 {status, trigger}。

    单飞:已有任务在跑时直接返回 running 状态。
    """
    global _active_job_id
    with _active_lock:
        if _active_job_id is not None:
            return {"status": "running", "job_id": _active_job_id}
        import uuid as _uuid
        job_id = _uuid.uuid4().hex[:8]
        _active_job_id = job_id

    def _task() -> None:
        global _active_job_id
        try:
            run_daily_briefing(trigger=trigger)
        finally:
            with _active_lock:
                _active_job_id = None

    _async_executor.submit(_task)
    return {"status": "started", "trigger": trigger, "job_id": job_id}
