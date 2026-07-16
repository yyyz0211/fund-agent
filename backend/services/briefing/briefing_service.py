"""每日基金简报编排服务。

编排流程:collect_watchlist_snapshot(指数 + 自选池 metrics + 当日 evidence)
       → compose_briefing(DeepSeek 生成 markdown + 结构化 sections)
       → upsert Briefing 表（含 data_quality / confidence / missing_data / evidence_count）
       → 写内存快照。

简报不走 LangGraph / qa_graph，不经过 policy.py 合规检查。

Phase 1.2 事务约定:
- `run_daily_briefing` 把网络/LLM调用挪出事务:evidence 采集 + LLM compose
  在事务外,只 persist(Briefing upsert)走短事务。
- Service 函数体禁止 `s.commit() / s.rollback() / s.close()`;
  caller 注 session 时只 flush,owning 模式走 `with session_scope()`.
- `read_briefing` 同 read pattern:`session is None -> session_scope()`,
  注 session 则只读 + flush。
- `compose_briefing` 已由 Phase 1.1 接 `model` 参数,签名稳定,本任务不动。
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
from backend.db.session_scope import session_scope
from backend.services.briefing.prompts import BRIEFING_PROMPT_TEMPLATE_V2
from backend.services.briefing.types import ChatModel
from backend.services.market import data_collector as dc
from backend.services.market import market_service, market_evidence_service
from backend.services.watchlist import watchlist_service
from backend.services.fund import fund_service


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


_lock = Lock()
_last_run: dict = {}
settings = app_settings.get_settings()


def _get_settings():
    return app_settings.get_settings()


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


# ---------------------------------------------------------------------------
# 简报合成
# ---------------------------------------------------------------------------

def compose_briefing(
    snapshot: dict,
    evidence: list[dict] | None = None,
    *,
    model: ChatModel | None = None,
    profile: BriefTypeProfile | None = None,
) -> dict:
    """调用 DeepSeek 把 snapshot + evidence 合成 markdown + sections。

    V2 行为：通过 module builders 生成结构化 sections，再交给 LLM 仅做语言
    组织。返回 dict 含 keys: markdown, sections, warnings, llm_model, prompt_used_chars。

    Args:
        snapshot: 市场快照数据
        evidence: 当日证据列表，将被拼入 prompt 供 LLM 引用
        model: 聊天模型实例。**必须**由 composition root(API 路由 / scheduler)
            通过 `backend.graph.model.build_model()` 构造并显式传入;本函数不再
            提供 lazy import 兜底 — 缺 model 时立刻 `RuntimeError` 让上层发现。
        profile: V2 profile；None 时默认走 post_market（向后兼容）

    Raises:
        RuntimeError: `model` 为 None(未注入)。
    """
    from string import Template
    from backend.services.briefing import module_briefing as mb

    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    evidence_json = json.dumps(evidence or [], ensure_ascii=False, indent=2)

    # 决定 profile：默认 post_market
    if profile is None:
        profile, _profile_warnings = mb.get_brief_type_profile("post_market")

    # V2: 跑 module builders
    modules, module_order, _module_warnings = mb.run_module_builders(
        profile=profile, snapshot=snapshot, evidence=evidence or [], context={},
    )
    # data quality
    quality = compute_data_quality(snapshot, evidence or [])
    quick_summary_mod = mb.run_quick_summary_module(
        profile=profile,
        modules=modules,
        data_quality=quality["data_quality"],
        confidence=quality["confidence"],
    )
    as_of = _today()
    try:
        idx_list = snapshot.get("market_snapshot", []) if isinstance(snapshot, dict) else []
        if idx_list:
            md = idx_list[0].get("market_date")
            if md:
                as_of = md
    except Exception:
        pass
    data_statement_mod = mb.run_data_statement_module(
        modules=modules,
        as_of=as_of,
        briefing_date=_today(),
        data_quality=quality["data_quality"],
        confidence=quality["confidence"],
        missing_data=quality["missing_data"],
        failed_modules=quality.get("failed_modules", []),
        data_sources_last_updated=quality.get("data_sources_last_updated", {}),
        evidence_count=len(evidence or []),
    )

    # 模块顺序：quick_summary 前置，data_statement 末尾
    all_modules: dict[str, dict] = {
        mk: (m.to_dict() if hasattr(m, "to_dict") else dict(m) if isinstance(m, dict) else {"key": mk})
        for mk, m in modules.items()
    }
    all_modules["quick_summary"] = (
        quick_summary_mod.to_dict() if hasattr(quick_summary_mod, "to_dict") else dict(quick_summary_mod)
    )
    all_modules["data_statement"] = (
        data_statement_mod.to_dict() if hasattr(data_statement_mod, "to_dict") else dict(data_statement_mod)
    )
    module_order_final = ["quick_summary", *module_order, "data_statement"]

    sections_structured = {
        "brief_type": profile.brief_type,
        "profile_version": "daily_briefing_v2_2026_07_09",
        "module_order": module_order_final,
        "modules": all_modules,
        "warnings": [],
    }

    module_json = json.dumps(sections_structured, ensure_ascii=False, indent=2)
    prompt = BRIEFING_PROMPT_TEMPLATE_V2.substitute(
        brief_type=profile.brief_type,
        max_markdown_words=profile.max_markdown_words,
        profile_json=json.dumps({
            "brief_type": profile.brief_type,
            "title": profile.title,
            "required_modules": profile.required_modules,
            "optional_modules": profile.optional_modules,
            "max_markdown_words": profile.max_markdown_words,
        }, ensure_ascii=False),
        snapshot_json=snapshot_json,
        evidence_json=evidence_json,
        module_sections_json=module_json,
    )

    # Phase 1.1: model 由 composition root 注入。如果上层忘记传,这里立刻失败
    # 而不是悄悄 lazy import — 让调用方在测试或部署时立即发现。
    if model is None:
        raise RuntimeError(
            "compose_briefing requires `model` to be injected by the composition root "
            "(API route or scheduler). Call build_model() in the entry point and pass it."
        )
    response = model.invoke(prompt)
    raw_content = response.content if hasattr(response, "content") else str(response)

    warnings: list[str] = []

    def _parse(candidate: str) -> tuple[dict | None, str | None]:
        """返回 (parsed_dict_or_None, error_or_None)。"""
        try:
            return json.loads(candidate), None
        except (json.JSONDecodeError, TypeError) as exc:
            return None, str(exc)

    parsed, _err = _parse(raw_content)
    if parsed is not None:
        markdown = parsed.get("markdown", raw_content)
        md_warnings = parsed.get("markdown_warnings", [])
    else:
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
            md_warnings = parsed.get("markdown_warnings", [])
            warnings.append("llm_returned_wrapped_json，已剥除外层 braces")
        else:
            warnings.append("llm_returned_non_json，使用原始文本作为 markdown")
            markdown = raw_content
            md_warnings = []

    # sections: 把 V2 结构也带回去，前端继续可读
    return {
        "markdown": markdown,
        "sections": sections_structured,
        "warnings": warnings + md_warnings,
        "llm_model": getattr(settings, "briefing_llm_model", "deepseek-chat"),
        "prompt_used_chars": len(prompt),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_daily_briefing(
    *,
    trigger: str = "scheduled",
    session=None,
    brief_type: str = "post_market",
    model: ChatModel | None = None,
) -> dict:
    """编排: collect → compose → upsert Briefing → 写内存快照。

    绝不抛异常。单步失败记入 failures，整批继续。

    brief_type: post_market / pre_market / intraday。默认 post_market 以保持
    旧调用（未传参）行为一致。

    Phase 1.2 事务拆分 (spec §4.2):
    - 阶段 1: evidence 采集 + 读取 (网络/DB 短事务)
    - 阶段 2: collect_watchlist_snapshot + LLM compose (网络, **无事务**)
    - 阶段 3: Briefing upsert (独立 short-tx; caller 注 session 则仅 flush)

    Args:
        trigger: 触发来源(manual / scheduled / api)。
        session: 数据库 session,`None` 时新建。
        brief_type: 简报类型。
        model: 聊天模型实例,**必须**由 composition root 注入。如果为 None,
            `compose_briefing` 会立即 `RuntimeError`,本函数捕获后记入
            failures 列表,继续走"无 LLM 输出"的降级路径。
    """
    from backend.db.repositories.briefing import upsert_briefing
    from backend.services.briefing import module_briefing as mb

    today = _today()
    profile, profile_warnings = mb.get_brief_type_profile(brief_type)
    effective_brief_type = profile.brief_type

    snapshot: dict = {}
    compose_result: dict = {}
    failures: list[dict] = []
    succeeded = 0
    failed = 0

    # ------------------------------------------------------------------
    # 阶段 1: evidence 采集 (无事务或独立短事务)
    # ------------------------------------------------------------------
    if session is None:
        # 阶段 1a: ingest (独立 short-tx)
        try:
            with session_scope() as ev_s:
                market_evidence_service.collect_and_run_for_brief_type(
                    brief_type=effective_brief_type, trade_date=today,
                    sector_snapshot=None, session=ev_s,
                )
        except Exception:  # noqa: BLE001
            pass  # ingestion failures are non-fatal
        # 阶段 1b: search (独立 short-tx; 可读到 1a 写入的 evidence)
        evidence_rows: list[dict] = []
        try:
            with session_scope() as ev_s:
                evidence_rows = market_evidence_service.search_evidence(
                    trade_date=today, limit=20, session=ev_s,
                )
        except Exception:
            evidence_rows = []
    else:
        # caller 注 session: 同一 session 共用, 只 flush
        try:
            market_evidence_service.collect_and_run_for_brief_type(
                brief_type=effective_brief_type, trade_date=today,
                sector_snapshot=None, session=session,
            )
        except Exception:  # noqa: BLE001
            pass
        evidence_rows = []
        try:
            evidence_rows = market_evidence_service.search_evidence(
                trade_date=today, limit=20, session=session,
            )
        except Exception:
            evidence_rows = []

    # ------------------------------------------------------------------
    # 阶段 2a: collect (网络, 无事务)
    # ------------------------------------------------------------------
    try:
        snapshot = collect_watchlist_snapshot(session=session)
    except Exception as exc:  # noqa: BLE001
        failures.append({"stage": "collect", "message": str(exc)})
        failed += 1

    # collect 单项 errors 也计入 failed (按 fund_code 维度)
    collect_errors = snapshot.get("errors", []) if snapshot else []
    for ce in collect_errors:
        failures.append({
            "stage": "collect",
            "fund_code": ce.get("fund_code"),
            "message": ce.get("message"),
        })
        failed += 1

    # compute data quality (now includes failed_modules and data_sources_last_updated)
    quality = compute_data_quality(snapshot, evidence_rows)

    # as_of：真实数据交易日（从 indices 第一行的 market_date 取）
    as_of = today
    try:
        indices_list = snapshot.get("market_snapshot", []) if isinstance(snapshot, dict) else []
        if indices_list:
            first_md = indices_list[0].get("market_date")
            if first_md:
                as_of = first_md
    except Exception:
        pass

    # ------------------------------------------------------------------
    # 阶段 2b: compose — LLM (DeepSeek) 网络调用, **绝不在事务内**
    # ------------------------------------------------------------------
    try:
        compose_result = compose_briefing(
            snapshot,
            evidence=evidence_rows,
            profile=profile,
            model=model,
        )
        if profile_warnings:
            compose_result["warnings"] = profile_warnings + list(compose_result.get("warnings", []))
        succeeded = 1
    except Exception as exc:  # noqa: BLE001
        compose_result = {
            "markdown": "（系统错误，简报生成失败。）",
            "sections": {},
            "warnings": [f"compose 失败：{exc}"],
        }
        failures.append({"stage": "compose", "message": str(exc)})
        failed += 1

    if not snapshot.get("watchlist_changes") and not snapshot.get("market_snapshot"):
        compose_result = {
            "markdown": "（今日自选池为空，无涨跌数据。）",
            "sections": {},
            "warnings": compose_result.get("warnings", []),
        }
        # 自选池为空时不算成功（无可用数据生成正稿）
        succeeded = 0

    sections = compose_result.get("sections", {})

    sections_json = json.dumps(sections, ensure_ascii=False)

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

    # ------------------------------------------------------------------
    # 阶段 3: 持久化 (独立 short-tx or 注 session only-flush)
    # ------------------------------------------------------------------
    try:
        if session is None:
            with session_scope() as s:
                upsert_briefing(
                    s,
                    briefing_date=today,
                    payload={**payload, "brief_type": effective_brief_type},
                    brief_type=effective_brief_type,
                )
        else:
            upsert_briefing(
                session,
                briefing_date=today,
                payload={**payload, "brief_type": effective_brief_type},
                brief_type=effective_brief_type,
            )
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


def read_briefing(brief_date: str | None = None, brief_type: str = "post_market") -> dict | None:
    """从 DB 读取 briefing（None=最近），返回 dict（含新 data_quality 字段）。

    brief_type: 按 type 过滤；None 表示不限定。

    Phase 1.2: 顶层事务 — 自动 commit/rollback/close via `session_scope()`。
    不带 session 参数的纯读接口。
    """
    with session_scope() as s:
        if brief_date:
            stmt = select(Briefing).where(Briefing.briefing_date == brief_date)
            if brief_type:
                stmt = stmt.where(Briefing.brief_type == brief_type)
            row = s.scalar(stmt)
        else:
            stmt = select(Briefing)
            if brief_type:
                stmt = stmt.where(Briefing.brief_type == brief_type)
            row = s.scalar(stmt.order_by(Briefing.briefing_date.desc()))
        if row is None:
            return None
        sections = {}
        try:
            sections = json.loads(row.sections_json) if row.sections_json else {}
        except Exception:
            pass
        missing_data: list[str] = []
        failed_modules: list[dict] = []
        data_sources_last_updated: dict = {}
        if row.missing_data_json:
            try:
                parsed = json.loads(row.missing_data_json)
                if isinstance(parsed, list):
                    missing_data = [str(x) for x in parsed]
            except Exception:
                pass
        # 从 sections_json 中提取 failed_modules 和 data_sources_last_updated
        # V2: 在 sections.modules.data_statement 中；legacy: 在 sections.data_statement 中
        v2_ds = (sections.get("modules") or {}).get("data_statement") or {}
        legacy_ds = sections.get("data_statement") or {}
        ds = v2_ds.get("content", v2_ds) or legacy_ds
        if ds:
            failed_modules = ds.get("failed_modules", []) or []
            data_sources_last_updated = ds.get("data_sources_last_updated", {}) or {}
        return {
            "id": row.id,
            "briefing_date": row.briefing_date,
            "brief_type": getattr(row, "brief_type", "post_market"),
            "title": row.title,
            "markdown": row.markdown,
            "sections": sections,
            "source": row.source,
            "as_of": row.as_of,
            "data_quality": row.data_quality,
            "confidence": row.confidence,
            "missing_data": missing_data,
            "evidence_count": row.evidence_count,
            "failed_modules": failed_modules,
            "data_sources_last_updated": data_sources_last_updated,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


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


def start_run_async(
    *,
    trigger: str = "manual",
    brief_type: str = "post_market",
    model: ChatModel | None = None,
) -> dict:
    """后台线程触发一次简报生成,立即返回 {status, trigger, brief_type}。

    单飞:已有任务在跑时直接返回 running 状态。

    Args:
        model: 聊天模型实例,**必须**由调用方(composition root)注入并
            一路传到 `run_daily_briefing` → `compose_briefing`。生产路径
            应在 API 路由里调 `build_model()` 后传入;为 None 时后台任务
            会立刻失败记入 failures,调度语义保持不变。
    """
    global _active_job_id
    with _active_lock:
        if _active_job_id is not None:
            return {"status": "running", "job_id": _active_job_id, "brief_type": brief_type}
        import uuid as _uuid
        job_id = _uuid.uuid4().hex[:8]
        _active_job_id = job_id

    def _task() -> None:
        global _active_job_id
        try:
            run_daily_briefing(trigger=trigger, brief_type=brief_type, model=model)
        finally:
            with _active_lock:
                _active_job_id = None

    _async_executor.submit(_task)
    return {"status": "started", "trigger": trigger, "brief_type": brief_type, "job_id": job_id}
