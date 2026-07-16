"""Synchronous orchestration for the Briefing domain."""
from __future__ import annotations

import json
from datetime import datetime

from backend.db.session_scope import session_scope
from backend.services.briefing import _state, collectors, composer, modules, persistence
from backend.services.briefing.types import ChatModel


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def run_daily_briefing(
    *,
    trigger: str = "scheduled",
    session=None,
    brief_type: str = "post_market",
    model: ChatModel | None = None,
) -> dict:
    """Orchestrate collect, compose, persistence, and runtime status."""
    today = _today()
    profile, profile_warnings = modules.get_brief_type_profile(brief_type)
    effective_brief_type = profile.brief_type

    snapshot: dict = {}
    compose_result: dict = {}
    failures: list[dict] = []
    succeeded = 0
    failed = 0

    if session is None:
        try:
            with session_scope() as ev_s:
                collectors.collect_and_run_for_brief_type(
                    brief_type=effective_brief_type,
                    trade_date=today,
                    sector_snapshot=None,
                    session=ev_s,
                )
        except Exception:  # noqa: BLE001
            pass
        evidence_rows: list[dict] = []
        try:
            with session_scope() as ev_s:
                evidence_rows = collectors.search_evidence(
                    trade_date=today,
                    limit=20,
                    session=ev_s,
                )
        except Exception:  # noqa: BLE001
            evidence_rows = []
    else:
        try:
            collectors.collect_and_run_for_brief_type(
                brief_type=effective_brief_type,
                trade_date=today,
                sector_snapshot=None,
                session=session,
            )
        except Exception:  # noqa: BLE001
            pass
        evidence_rows = []
        try:
            evidence_rows = collectors.search_evidence(
                trade_date=today,
                limit=20,
                session=session,
            )
        except Exception:  # noqa: BLE001
            evidence_rows = []

    try:
        snapshot = collectors.collect_watchlist_snapshot(session=session)
    except Exception as exc:  # noqa: BLE001
        failures.append({"stage": "collect", "message": str(exc)})
        failed += 1

    collect_errors = snapshot.get("errors", []) if snapshot else []
    for collect_error in collect_errors:
        failures.append({
            "stage": "collect",
            "fund_code": collect_error.get("fund_code"),
            "message": collect_error.get("message"),
        })
        failed += 1

    quality = collectors.compute_data_quality(snapshot, evidence_rows)

    as_of = today
    try:
        indices_list = snapshot.get("market_snapshot", []) if isinstance(snapshot, dict) else []
        if indices_list:
            first_market_date = indices_list[0].get("market_date")
            if first_market_date:
                as_of = first_market_date
    except Exception:  # noqa: BLE001
        pass

    try:
        compose_result = composer.compose_briefing(
            snapshot,
            evidence=evidence_rows,
            profile=profile,
            model=model,
        )
        if profile_warnings:
            compose_result["warnings"] = profile_warnings + list(
                compose_result.get("warnings", [])
            )
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

    try:
        if session is None:
            with session_scope() as target_session:
                persistence.persist_briefing(
                    target_session,
                    briefing_date=today,
                    payload={**payload, "brief_type": effective_brief_type},
                    brief_type=effective_brief_type,
                )
        else:
            target_session = session
            persistence.persist_briefing(
                target_session,
                briefing_date=today,
                payload={**payload, "brief_type": effective_brief_type},
                brief_type=effective_brief_type,
            )
    except Exception as exc:  # noqa: BLE001
        failures.append({"stage": "db_upsert", "message": str(exc)})
        failed += 1

    total_funds = len(snapshot.get("watchlist_changes", []))
    snap = {
        "last_run_at": _now(),
        "trigger": trigger,
        "total_funds": total_funds,
        "succeeded": succeeded,
        "failed": failed,
        "failures": failures,
    }
    _state.update_last_run(snap)
    return snap


__all__ = ["run_daily_briefing"]
