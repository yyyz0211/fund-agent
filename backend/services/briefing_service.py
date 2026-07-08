"""每日基金简报编排服务。

编排流程:collect_watchlist_snapshot(指数 + 自选池 metrics + 当日 evidence)
       → compose_briefing(DeepSeek 生成 markdown + 结构化 sections)
       → upsert Briefing 表（含 data_quality / confidence / missing_data / evidence_count）
       → 写内存快照。

简报不走 LangGraph / qa_graph，不经过 policy.py 合规检查。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any

from sqlalchemy import select

from backend.config import settings as app_settings
from backend.db.models import Briefing
from backend.db.session import get_session
# 注意: backend.graph.model 不可在 module 顶部 import, 否则会触发循环
#   backend.graph.__init__ → qa_graph → model → tools → market_tools → briefing_service → model (循环)。
# 改为在 compose_briefing() 内部 lazy import。
from backend.services import data_collector as dc
from backend.services import market_service, watchlist_service, fund_service
from backend.services import market_evidence_service


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

    has_indices = bool(market_snapshot)
    has_sectors = bool(sectors)
    has_overseas = isinstance(snapshot.get("industry_sectors"), list)  # placeholder
    missing: list[str] = []

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

    if not market_snapshot and not sectors and not evidence_count and errors:
        return {"data_quality": "failed", "confidence": "low",
                "missing_data": list(_DATA_DIMENSIONS)}

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
    }


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
        # watchlist.fund_name 由 repository._watchlist_to_dict 返回,
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
        },
    }


def _collect_market_snapshot():
    """拉最新交易日指数，返回 {indices, source, as_of} 或 {error}。"""
    return market_service.get_indices()
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


# ---------------------------------------------------------------------------
# 简报合成
# ---------------------------------------------------------------------------

def compose_briefing(snapshot: dict, evidence: list[dict] | None = None) -> dict:
    """调用 DeepSeek 把 snapshot + evidence 合成 markdown + sections。

    Args:
        snapshot: 市场快照数据
        evidence: 当日证据列表，将被拼入 prompt 供 LLM 引用

    Returns:
        dict，含 keys: markdown, sections, warnings, llm_model, prompt_used_chars
    """
    from backend.graph.prompts import BRIEFING_PROMPT_TEMPLATE

    warnings: list[str] = []
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    evidence_json = json.dumps(evidence or [], ensure_ascii=False, indent=2)
    # 用 SafeFormatter 防止 JSON 中的 {key} 被二次解析为占位符
    from string import Template
    safe_prompt = Template(BRIEFING_PROMPT_TEMPLATE).substitute(
        snapshot_json=snapshot_json, evidence_json=evidence_json
    )
    prompt = safe_prompt  # noqa: F841

    # 内部 lazy import 避免循环: backend.services.briefing_service ← market_tools ← fund_tools
    #   ← qa_graph → model → tools → market_tools → briefing_service ← model
    # 把 model 导入延后到首次实际 LLM 调用时, 此时 backend.graph.model 已完成加载。
    # 测试通过 `patch("backend.graph.model.build_model", ...)` mock 真实来源。
    from backend.graph import model as _model_module
    model = _model_module.build_model()
    response = model.invoke(prompt)
    raw_content = response.content if hasattr(response, "content") else str(response)

    # 尝试解析 JSON
    def _parse(candidate: str) -> tuple[dict | None, str | None]:
        """返回 (parsed_dict_or_None, error_or_None)。"""
        try:
            return json.loads(candidate), None
        except (json.JSONDecodeError, TypeError) as exc:
            return None, str(exc)

    parsed, _err = _parse(raw_content)
    if parsed is not None:
        markdown = parsed.get("markdown", raw_content)
        sections = parsed.get("sections", {})
    else:
        # Fallback: LLM 有时返回 outer doubled braces `{{...}}` (Prompt
        # 模板里意外写成 `{{...}}` 而 string.Template 不解析 `{`, LLM
        # 老老实实复刻 prompt 模板就会这样输出)。逐层剥外层 `{}`, 每剥
        # 一层重试一次, 直到能解析或剥无可剥。
        candidate = raw_content.strip()
        attempts = 0
        while attempts < 4 and (
            candidate.startswith("{") and candidate.endswith("}")
        ):
            attempts += 1
            candidate = candidate[1:-1].strip()
            parsed, _err = _parse(candidate)
            if parsed is not None:
                break
        if parsed is not None:
            markdown = parsed.get("markdown", raw_content)
            sections = parsed.get("sections", {})
            warnings.append(
                "llm_returned_wrapped_json，剥除外层 braces 后解析"
            )
        else:
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

    # 提前创建 session 让 ingest 和 search 共用同一事务上下文
    evidence_owns = session is None
    evidence_session = session or get_session()
    today = _today()

    snapshot: dict = {}
    compose_result: dict = {}
    failures: list[dict] = []
    succeeded = 0
    failed = 0

    # ingest evidence (collect from all sources including CLS) before reading
    try:
        market_evidence_service.collect_and_run_for_brief_type(
            brief_type="post_market", trade_date=today, sector_snapshot=None,
            session=evidence_session,
        )
    except Exception:  # noqa: BLE001
        pass  # ingestion failures are non-fatal; proceed with whatever is in DB

    # collect evidence
    evidence_rows: list[dict] = []
    try:
        evidence_rows = market_evidence_service.search_evidence(
            trade_date=today, limit=20, session=evidence_session,
        )
    except Exception:
        evidence_rows = []

    # close evidence session (only if we own it)
    if evidence_owns:
        evidence_session.close()

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

    # compute data quality
    quality = compute_data_quality(snapshot, evidence_rows)

    # compose
    if snapshot.get("watchlist_changes") or snapshot.get("market_snapshot"):
        try:
            compose_result = compose_briefing(snapshot, evidence=evidence_rows)
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
    # as_of 用真实数据交易日(从 indices 第一行的 market_date 取),
    # 而不是"今天"。周末/节假日/尚未 refresh 时 _today() 跟真实数据日期错位,
    # 用户看到 "数据日期: 2026-07-08" 但实际是 2026-06-30 的旧数据 —— 误导。
    as_of = today
    try:
        indices_list = snapshot.get("market_snapshot", []) if isinstance(snapshot, dict) else []
        if indices_list:
            first_md = indices_list[0].get("market_date")
            if first_md:
                as_of = first_md
    except Exception:
        pass
    sections_json = json.dumps(compose_result.get("sections", {}), ensure_ascii=False)

    payload = {
        "title": f"每日基金简报 {as_of}",
        "markdown": compose_result.get("markdown", ""),
        "sections_json": sections_json,
        "source": "akshare + deepseek",
        "as_of": as_of,
        "data_quality": quality["data_quality"],
        "confidence": quality["confidence"],
        "missing_data_json": json.dumps(quality["missing_data"], ensure_ascii=False),
        "evidence_count": len(evidence_rows),
    }

    try:
        owns = session is None
        s = session or get_session()
        try:
            # briefing_date 用 today 做幂等键 — 同日多次触发覆盖同一行。
            # as_of(数据交易日)与 today(本次生成日)可能不同(如周末/假期),
            # 已在 markdown 末尾 "数据声明" 段真实展示。
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


def read_briefing(brief_date: str | None = None) -> dict | None:
    """从 DB 读取 briefing（None=最近），返回 dict（含新 data_quality 字段）。

    供 market_tools.get_market_briefing 调用。
    """
    s = get_session()
    try:
        if brief_date:
            row = s.scalar(select(Briefing).where(Briefing.briefing_date == brief_date))
        else:
            row = s.scalar(select(Briefing).order_by(Briefing.briefing_date.desc()))
        if row is None:
            return None
        sections = {}
        try:
            sections = json.loads(row.sections_json) if row.sections_json else {}
        except Exception:
            pass
        missing_data: list[str] = []
        if row.missing_data_json:
            try:
                parsed = json.loads(row.missing_data_json)
                if isinstance(parsed, list):
                    missing_data = [str(x) for x in parsed]
            except Exception:
                pass
        return {
            "id": row.id,
            "briefing_date": row.briefing_date,
            "title": row.title,
            "markdown": row.markdown,
            "sections": sections,
            "source": row.source,
            "as_of": row.as_of,
            "data_quality": row.data_quality,
            "confidence": row.confidence,
            "missing_data": missing_data,
            "evidence_count": row.evidence_count,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    finally:
        s.close()


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
