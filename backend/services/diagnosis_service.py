"""Fund diagnosis assembly service."""
from __future__ import annotations

import json

from backend.db import repository as repo
from backend.db.session import get_session
from backend.services import diagnosis_rules as rules
from backend.services import fund_profile_service as profile_service
from backend.services import fund_service as fs
from backend.services import metric_service as metrics


def _with_session(session):
    return session or get_session()


def _json_list(value: str | None) -> list[dict]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def get_peers(fund_code: str, limit: int = 5, period: str = "1y", session=None) -> list[dict]:
    """Return peer candidates from local profile cache.

    候选基金即使没有本地 NAV 也返回,指标字段置为 None;这样前端不会
    因本地未刷新候选 NAV 而把同类候选整块隐藏。
    """
    s = _with_session(session)
    owns = session is None
    try:
        profile = profile_service.get_profile(fund_code, session=s)
        candidates = _json_list(profile.get("peer_candidates_json") if profile else None)
        peers = []
        for candidate in candidates:
            code = str(candidate.get("fund_code") or "")
            if not code:
                continue
            navs = repo.get_accumulated_navs(s, code)
            has_local_nav = len(navs) >= 2
            period_return = None
            max_drawdown = None
            volatility = None
            if has_local_nav:
                try:
                    period_return = metrics.period_return(navs, period)
                except ValueError:
                    period_return = None
                max_drawdown = metrics.max_drawdown(navs)
                volatility = metrics.volatility(navs)
            if len(navs) < 2:
                has_local_nav = False
            peer_profile = profile_service.get_profile(code, session=s) or {}
            peers.append({
                "fund_code": code,
                "fund_name": candidate.get("fund_name"),
                "fund_type": candidate.get("fund_type"),
                "period_return": period_return,
                "max_drawdown": max_drawdown,
                "volatility": volatility,
                "scale": peer_profile.get("scale"),
                "has_local_nav": has_local_nav,
            })
            if len(peers) >= limit:
                break
        return peers
    finally:
        if owns:
            s.close()


def _light(
    key: str,
    label: str,
    level: str,
    value,
    reason: str,
    source: str,
    as_of: str,
    *,
    core: bool = False,
) -> dict:
    return {
        "key": key,
        "label": label,
        "level": level,
        "value": value,
        "reason": reason,
        "source": source,
        "as_of": as_of,
        "core": core,
    }


def _reason_for(label: str, level: str) -> str:
    if level == "red":
        return f"{label}处于高风险区间"
    if level == "yellow":
        return f"{label}需要观察"
    if level == "green":
        return f"{label}暂未触发明显风险"
    return f"{label}暂无足够本地数据"


def _profile_missing(profile: dict | None, fund: dict | None = None) -> list[str]:
    has_basic_manager = bool((fund or {}).get("manager"))
    if not profile:
        missing = ["scale", "rank", "peers", "holdings", "industry"]
        if not has_basic_manager:
            missing.append("manager")
        return missing
    missing = []
    if profile.get("scale") is None:
        missing.append("scale")
    if profile.get("rank_total") is None or profile.get("rank_position") is None:
        missing.append("rank")
    if not profile.get("peer_candidates_json"):
        missing.append("peers")
    if profile.get("top10_holding_pct") is None:
        missing.append("holdings")
    if profile.get("top_industry_pct") is None:
        missing.append("industry")
    if profile.get("manager_summary") is None and not has_basic_manager:
        missing.append("manager")
    return missing


def _pitfalls(lights: list[dict], missing_data: list[str], source: str, as_of: str) -> list[dict]:
    out = []
    for light in lights:
        if light["level"] not in {"red", "yellow"}:
            continue
        severity = "danger" if light["level"] == "red" else "warning"
        out.append({
            "key": light["key"],
            "severity": severity,
            "title": light["label"],
            "detail": light["reason"],
            "source": light["source"],
            "as_of": light["as_of"],
        })
    if missing_data:
        out.append({
            "key": "missing_data",
            "severity": "info",
            "title": "数据不完整",
            "detail": "部分画像数据缺失，结论置信度会降低。",
            "source": source,
            "as_of": as_of,
        })
    return out[:6]


def _reasons(lights: list[dict], missing_data: list[str]) -> list[str]:
    priority = {"red": 0, "yellow": 1, "gray": 2, "green": 3}
    sorted_lights = sorted(lights, key=lambda item: priority.get(item["level"], 9))
    reasons = [
        item["reason"]
        for item in sorted_lights
        if item["level"] in {"red", "yellow", "gray"}
    ][:3]
    if not reasons and not missing_data:
        reasons.append("主要风险灯暂未触发明显异常。")
    return reasons[:3]


def _suitable_for(label: str) -> dict:
    if label == "暂不碰":
        return {
            "fit": ["适合先继续补数据和观察，不适合立即纳入候选。"],
            "avoid": ["不适合稳健型或无法承受较大回撤的人。"],
        }
    if label == "观察":
        return {
            "fit": ["适合愿意继续跟踪公开数据的人。"],
            "avoid": ["不适合希望快速得到明确结论的人。"],
        }
    if label == "小仓试验":
        return {
            "fit": ["适合风险承受能力较高、能接受波动的人。"],
            "avoid": ["不适合稳健型或短期资金需求明确的人。"],
        }
    return {
        "fit": ["适合纳入候选池继续比较同类基金。"],
        "avoid": ["仍不适合把历史表现当作未来收益承诺的人。"],
    }


def _summary_sentence(label: str, confidence: str, missing_data: list[str]) -> str:
    if missing_data:
        return f"本地体检结论为{label}，但缺失 {', '.join(missing_data[:3])} 等数据，置信度为 {confidence}。"
    return f"本地体检结论为{label}，置信度为 {confidence}。"


def diagnose_fund(fund_code: str, period: str = "1y", session=None) -> dict:
    """Build a deterministic local fund diagnosis payload."""
    s = _with_session(session)
    owns = session is None
    try:
        summary = fs.get_summary(fund_code, period=period, session=s)
        profile = profile_service.get_profile(fund_code, session=s)
        peers = get_peers(fund_code, limit=5, period=period, session=s)

        source = summary.get("source") or "akshare"
        as_of = summary.get("as_of")
        metrics_payload = summary.get("metrics") or {}
        fund_payload = summary.get("fund") or {}
        errors = summary.get("errors") or {}
        missing_data = list(errors.keys())
        missing_data.extend(_profile_missing(profile, fund_payload))
        if not peers:
            missing_data.append("peers")
        elif any(
            not peer.get("has_local_nav")
            or peer.get("period_return") is None
            or peer.get("max_drawdown") is None
            or peer.get("volatility") is None
            for peer in peers
        ):
            missing_data.append("peer_metrics")
        missing_data = list(dict.fromkeys(missing_data))
        category = (
            (profile or {}).get("peer_category")
            or fund_payload.get("fund_type")
            or "偏股混合"
        )

        lights = [
            _light(
                "period_return",
                f"{period}区间收益",
                rules.level_for_period_return(metrics_payload.get("period_return"), category=category),
                metrics_payload.get("period_return"),
                _reason_for(f"{period}区间收益", rules.level_for_period_return(metrics_payload.get("period_return"), category=category)),
                metrics_payload.get("source") or source,
                metrics_payload.get("as_of") or as_of,
                core=True,
            ),
            _light(
                "max_drawdown",
                "最大回撤",
                rules.level_for_drawdown(metrics_payload.get("max_drawdown"), category=category),
                metrics_payload.get("max_drawdown"),
                _reason_for("最大回撤", rules.level_for_drawdown(metrics_payload.get("max_drawdown"), category=category)),
                metrics_payload.get("source") or source,
                metrics_payload.get("as_of") or as_of,
                core=True,
            ),
            _light(
                "volatility",
                "波动率",
                rules.level_for_volatility(metrics_payload.get("volatility"), category=category),
                metrics_payload.get("volatility"),
                _reason_for("波动率", rules.level_for_volatility(metrics_payload.get("volatility"), category=category)),
                metrics_payload.get("source") or source,
                metrics_payload.get("as_of") or as_of,
                core=True,
            ),
            _light(
                "scale",
                "基金规模",
                rules.level_for_scale((profile or {}).get("scale")),
                (profile or {}).get("scale"),
                _reason_for("基金规模", rules.level_for_scale((profile or {}).get("scale"))),
                (profile or {}).get("source") or source,
                (profile or {}).get("as_of") or as_of,
            ),
            _light(
                "top10_holding_pct",
                "前十大持仓集中度",
                rules.level_for_concentration((profile or {}).get("top10_holding_pct")),
                (profile or {}).get("top10_holding_pct"),
                _reason_for("前十大持仓集中度", rules.level_for_concentration((profile or {}).get("top10_holding_pct"))),
                (profile or {}).get("source") or source,
                (profile or {}).get("as_of") or as_of,
            ),
            _light(
                "top_industry_pct",
                "第一大行业集中度",
                rules.level_for_concentration((profile or {}).get("top_industry_pct")),
                (profile or {}).get("top_industry_pct"),
                _reason_for("第一大行业集中度", rules.level_for_concentration((profile or {}).get("top_industry_pct"))),
                (profile or {}).get("source") or source,
                (profile or {}).get("as_of") or as_of,
            ),
        ]

        core_complete = bool(summary.get("latest_nav")) and bool(summary.get("metrics"))
        profile_complete = not _profile_missing(profile, fund_payload)
        label = rules.choose_decision_label(lights, missing_data)
        metric_peer_count = sum(
            1
            for peer in peers
            if peer.get("has_local_nav")
            and peer.get("period_return") is not None
            and peer.get("max_drawdown") is not None
            and peer.get("volatility") is not None
        )
        confidence = rules.confidence_for(core_complete, profile_complete, metric_peer_count)
        if not core_complete:
            label = "暂不碰"
            confidence = "low"

        return {
            "fund_code": fund_code,
            "period": period,
            "decision_label": label,
            "confidence": confidence,
            "summary": _summary_sentence(label, confidence, missing_data),
            "reasons": _reasons(lights, missing_data),
            "risk_lights": lights,
            "pitfalls": _pitfalls(lights, missing_data, source, as_of),
            "suitable_for": _suitable_for(label),
            "peers": peers,
            "missing_data": missing_data,
            "fund": summary.get("fund"),
            "latest_nav": summary.get("latest_nav"),
            "source": source,
            "as_of": as_of,
        }
    finally:
        if owns:
            s.close()
