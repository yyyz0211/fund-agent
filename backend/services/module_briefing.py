"""每日简报 V2 模块系统。

包含 BriefTypeProfile 定义、Module Envelope 协议、所有 module builders
和 Module Runner。

与旧版 compose_briefing 保持兼容：新简报走 V2 流程，旧简报格式不变。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

from backend.graph.prompts import BRIEFING_PROMPT_TEMPLATE_V2


# ---------------------------------------------------------------------------
# BriefTypeProfile
# ---------------------------------------------------------------------------

@dataclass
class BriefTypeProfile:
    """简报类型配置。"""
    brief_type: str
    title: str
    required_modules: list[str]
    optional_modules: list[str]
    forbidden_modules: list[str]
    data_window: str
    max_markdown_words: int

    @classmethod
    def post_market(cls) -> "BriefTypeProfile":
        return cls(
            brief_type="post_market",
            title="盘后简报",
            required_modules=[
                "quick_summary",
                "market_state",
                "themes_and_flows",
                "watchlist_impact",
                "risk_radar",
                "key_evidence",
                "data_statement",
            ],
            optional_modules=[],
            forbidden_modules=["overnight", "intraday_anomaly"],
            data_window="trade_date_full_day",
            max_markdown_words=1000,
        )

    @classmethod
    def pre_market(cls) -> "BriefTypeProfile":
        return cls(
            brief_type="pre_market",
            title="盘前简报",
            required_modules=[
                "quick_summary",
                "overnight",
                "key_evidence",
                "watchlist_impact",
                "risk_radar",
                "data_statement",
            ],
            optional_modules=["events"],
            forbidden_modules=["themes_and_flows", "intraday_anomaly"],
            data_window="pre_market",
            max_markdown_words=800,
        )

    @classmethod
    def intraday(cls) -> "BriefTypeProfile":
        return cls(
            brief_type="intraday",
            title="盘中简报",
            required_modules=[
                "quick_summary",
                "market_state",
                "themes_and_flows",
                "intraday_anomaly",
                "watchlist_impact",
                "risk_radar",
                "data_statement",
            ],
            optional_modules=["key_evidence"],
            forbidden_modules=["overnight"],
            data_window="intraday",
            max_markdown_words=600,
        )


_PROFILES: dict[str, BriefTypeProfile] = {}


def _init_profiles() -> dict[str, BriefTypeProfile]:
    return {
        "post_market": BriefTypeProfile.post_market(),
        "pre_market": BriefTypeProfile.pre_market(),
        "intraday": BriefTypeProfile.intraday(),
    }


def get_brief_type_profile(brief_type: str) -> tuple[BriefTypeProfile, list[str]]:
    """返回 profile 及 warning 列表。未知类型回退到 post_market。"""
    global _PROFILES
    if not _PROFILES:
        _PROFILES.update(_init_profiles())
    warnings: list[str] = []
    if brief_type not in _PROFILES:
        warnings.append(f"未知 brief_type '{brief_type}'，回退到 post_market")
        brief_type = "post_market"
    return _PROFILES[brief_type], warnings


# ---------------------------------------------------------------------------
# Module Envelope
# ---------------------------------------------------------------------------

@dataclass
class ModuleSection:
    """Module builder 统一输出 envelope。"""
    key: str
    title: str
    status: Literal["ready", "partial", "missing", "failed"] = "ready"
    summary: str = ""
    content: dict = field(default_factory=dict)
    evidence_ids: list[int] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Keyword theme mapping (用于自选池关联)
# ---------------------------------------------------------------------------

_THEME_KEYWORD_MAP: list[dict] = [
    {"keywords": ["AI", "人工智能", "算力", "半导体", "芯片", "GPU", "HBM", "IC"],
     "theme": "科技成长"},
    {"keywords": ["新能源", "电池", "光伏", "储能", "锂电", "电动车", "电动汽车"],
     "theme": "新能源"},
    {"keywords": ["医药", "创新药", "医疗", "疫苗", "中药", "CXO"],
     "theme": "医药"},
    {"keywords": ["消费", "白酒", "食品", "饮料", "家电", "汽车"],
     "theme": "消费"},
    {"keywords": ["军工", "国防", "航空航天"],
     "theme": "军工"},
    {"keywords": ["港股", "恒生", "中概", "海外"],
     "theme": "港股/海外"},
]


def _match_fund_theme(fund_name: str) -> str | None:
    """根据基金名称返回匹配的主题，没有匹配返回 None。"""
    name = fund_name or ""
    for entry in _THEME_KEYWORD_MAP:
        for kw in entry["keywords"]:
            if kw in name:
                return entry["theme"]
    return None


# ---------------------------------------------------------------------------
# Module Builders
# ---------------------------------------------------------------------------

def build_market_state_module(snapshot: dict, evidence: list[dict]) -> ModuleSection:
    """判断市场整体状态。"""
    indices = snapshot.get("market_snapshot") or []
    breadth = snapshot.get("market_breadth") or {}
    sectors = snapshot.get("industry_sectors") or []
    concepts = snapshot.get("concept_sectors") or []

    reasons: list[str] = []
    signals: list[str] = []

    # 指数涨跌
    up_count = sum(1 for i in indices if (i.get("change_pct") or 0) > 0)
    down_count = sum(1 for i in indices if (i.get("change_pct") or 0) < 0)
    avg_change = sum(i.get("change_pct") or 0 for i in indices) / max(len(indices), 1)

    # 宽度
    up_breadth = breadth.get("up", 0)
    down_breadth = breadth.get("down", 0)
    total_breadth = breadth.get("total", 1)
    limit_up = breadth.get("limit_up", 0)
    limit_down = breadth.get("limit_down", 0)

    if not indices and not breadth:
        return ModuleSection(
            key="market_state",
            title="市场状态",
            status="missing",
            summary="数据不足，无法判断市场状态。",
            missing_data=["market_snapshot", "market_breadth"],
            confidence="low",
        )

    # 判断逻辑
    if avg_change > 0.3 and up_count >= down_count:
        if total_breadth > 0 and up_breadth > down_breadth:
            state_label = "偏强"
            summary = "主要指数上涨，市场宽度健康，整体偏强。"
        else:
            state_label = "分化"
            summary = "指数上涨但宽度不佳，市场分化。"
            signals.append("指数涨但下跌家数较多" if total_breadth > 0 else "")
    elif avg_change < -0.3 and down_count >= up_count:
        if total_breadth > 0 and down_breadth > up_breadth:
            state_label = "偏弱"
            summary = "主要指数下跌，市场情绪偏弱。"
        else:
            state_label = "分化"
            summary = "指数下跌但宽度一般，市场分化。"
    elif total_breadth > 0 and abs(up_breadth - down_breadth) / max(total_breadth, 1) < 0.1:
        state_label = "分化"
        summary = "涨跌家数接近，市场整体分化。"
    elif abs(avg_change) < 0.1:
        state_label = "分化"
        summary = "主要指数变化不大，市场整体平稳分化。"
    else:
        state_label = "分化"
        summary = "市场整体分化，结构化特征明显。"

    # 补充宽度信息
    if total_breadth > 0:
        if up_breadth > down_breadth * 1.5:
            reasons.append(f"上涨家数 {up_breadth} 远超下跌 {down_breadth}，宽度健康")
        elif down_breadth > up_breadth * 1.5:
            reasons.append(f"下跌家数 {down_breadth} 远超上涨 {up_breadth}，宽度恶化")
        if limit_up > 50:
            reasons.append(f"涨停 {limit_up} 家，赚钱效应较好")
        elif limit_down > 30:
            reasons.append(f"跌停 {limit_down} 家，亏钱效应明显")

    # 板块信息
    if sectors:
        top3 = sectors[:3] if len(sectors) >= 3 else sectors
        top_names = [s.get("name", "") for s in top3 if s.get("change_pct", 0) > 0]
        if top_names:
            reasons.append(f"行业强势：{'、'.join(top_names)}")

    state_map: dict[str, str] = {
        "偏强": "bullish", "偏弱": "bearish",
        "分化": "divergent", "退潮": "retreating",
    }

    return ModuleSection(
        key="market_state",
        title="市场状态",
        status="ready",
        summary=summary,
        content={
            "state": state_map.get(state_label, "divergent"),
            "label": state_label,
            "reasons": [r for r in reasons if r],
            "signals": [s for s in signals if s],
        },
        confidence="medium",
    )


def build_themes_and_flows_module(
    snapshot: dict,
    evidence: list[dict],
    theme_context: dict | None = None,
) -> ModuleSection:
    """识别今日主线与资金流向。"""
    sectors = snapshot.get("industry_sectors") or []
    concepts = snapshot.get("concept_sectors") or []
    industry_flows = snapshot.get("industry_flows") or []
    concept_flows = snapshot.get("concept_flows") or []
    warnings: list[str] = []
    missing_data: list[str] = []

    leading_themes: list[dict] = []
    lagging_themes: list[dict] = []

    # 行业涨跌 top/bottom
    if sectors:
        sorted_sectors = sorted(sectors, key=lambda x: x.get("change_pct", 0), reverse=True)
        for s in sorted_sectors[:5]:
            leading_themes.append({
                "name": s.get("name", "未知"),
                "direction": "leading",
                "change_pct": s.get("change_pct", 0),
                "evidence": ["industry_sector"],
                "trend": _infer_trend(s.get("name", ""), theme_context),
                "confidence": "medium",
            })
        if len(sorted_sectors) >= 3:
            for s in sorted_sectors[-3:]:
                if (s.get("change_pct", 0) or 0) < 0:
                    lagging_themes.append({
                        "name": s.get("name", "未知"),
                        "direction": "lagging",
                        "change_pct": s.get("change_pct", 0),
                    })
    else:
        missing_data.append("industry_sectors")

    # 概念涨跌
    if concepts:
        sorted_concepts = sorted(concepts, key=lambda x: x.get("change_pct", 0), reverse=True)
        for c in sorted_concepts[:5]:
            leading_themes.append({
                "name": c.get("name", "未知"),
                "direction": "leading",
                "change_pct": c.get("change_pct", 0),
                "evidence": ["concept_sector"],
                "trend": _infer_trend(c.get("name", ""), theme_context),
                "confidence": "medium",
            })
    else:
        missing_data.append("concept_sectors")

    # 资金流
    if industry_flows:
        for f in industry_flows[:5]:
            net = f.get("net_flow", 0)
            if net > 0:
                for lt in leading_themes:
                    if lt.get("name") == f.get("name"):
                        lt["net_flow"] = net
                        break
    else:
        missing_data.append("industry_flows")

    if not concept_flows:
        missing_data.append("concept_flows")

    if not sectors and not concepts:
        return ModuleSection(
            key="themes_and_flows",
            title="主线与资金",
            status="missing",
            summary="缺乏板块数据，无法识别主线。",
            missing_data=missing_data,
            warnings=warnings,
            confidence="low",
        )

    if missing_data:
        warnings.append(f"以下数据缺失：{', '.join(missing_data)}，主线判断置信度降低")

    summary_parts = []
    if leading_themes:
        names = [t["name"] for t in leading_themes[:3]]
        summary_parts.append(f"主线：{'、'.join(names)}")
    if lagging_themes:
        names = [t["name"] for t in lagging_themes[:2]]
        summary_parts.append(f"弱势：{'、'.join(names)}")

    return ModuleSection(
        key="themes_and_flows",
        title="主线与资金",
        status="partial" if missing_data else "ready",
        summary="，".join(summary_parts) if summary_parts else "今日板块无明显趋势。",
        content={
            "leading_themes": leading_themes[:5],
            "lagging_themes": lagging_themes[:3],
        },
        evidence_ids=[],
        missing_data=missing_data,
        warnings=warnings,
        confidence="medium" if leading_themes else "low",
    )


def _infer_trend(theme_name: str, theme_context: dict | None) -> str:
    """基于主题上下文推断趋势。没有历史数据时返回空字符串。"""
    if not theme_context:
        return ""
    # theme_context 中存储近 N 日主题列表
    # 如果 theme_name 在连续多日中出现，视为 continuing
    recent = theme_context.get("recent_themes", [])
    if not recent:
        return ""
    # 简化：至少在最近 2 天出现才视为 continuing
    count = sum(1 for day_list in recent[:3] if theme_name in day_list)
    if count >= 2:
        return "continuing"
    elif count == 1:
        return "emerging"
    return "new"


def build_watchlist_impact_module(
    snapshot: dict,
    theme_context: dict | None = None,
) -> ModuleSection:
    """判断自选池与今日主线的关系。"""
    watchlist = snapshot.get("watchlist_changes") or []
    leading_themes: list[str] = []
    lagging_themes: list[str] = []

    if theme_context:
        leading_themes = theme_context.get("leading_themes", [])
        lagging_themes = theme_context.get("lagging_themes", [])

    positive: list[dict] = []
    negative: list[dict] = []
    neutral: list[dict] = []
    divergent: list[dict] = []

    if not watchlist:
        return ModuleSection(
            key="watchlist_impact",
            title="自选池影响",
            status="ready",
            summary="自选池为空，无法生成自选池影响。",
            content={"overall": "empty", "positive": [], "negative": [], "neutral": [], "divergent": []},
            confidence="high",
        )

    for fund in watchlist:
        fund_code = fund.get("fund_code", "")
        fund_name = fund.get("fund_name", "")
        returns = fund.get("period_returns") or {}
        fund_theme = _match_fund_theme(fund_name)

        if not leading_themes and not lagging_themes:
            neutral.append({"fund_code": fund_code, "fund_name": fund_name})
            continue

        if not fund_theme:
            neutral.append({"fund_code": fund_code, "fund_name": fund_name})
            continue

        # 检查是否匹配主线或弱势
        is_leading = any(fund_theme == lt for lt in leading_themes)
        is_lagging = any(fund_theme == lt for lt in lagging_themes)

        if is_leading:
            positive.append({
                "fund_code": fund_code,
                "fund_name": fund_name,
                "reason": f"名称包含{fund_theme}，今日该主题强势",
            })
        elif is_lagging:
            negative.append({
                "fund_code": fund_code,
                "fund_name": fund_name,
                "reason": f"名称包含{fund_theme}，今日该主题弱势",
            })
        else:
            neutral.append({"fund_code": fund_code, "fund_name": fund_name})

    # 判断整体方向
    if positive and not negative:
        overall = "positive"
        summary = f"自选池整体与今日主线正向关联，{len(positive)} 只基金匹配。"
    elif negative and not positive:
        overall = "negative"
        summary = f"自选池整体受主线弱势影响，{len(negative)} 只基金处于弱势板块。"
    elif positive and negative:
        overall = "mixed"
        summary = f"自选池分化，{len(positive)} 只正向，{len(negative)} 只负向。"
    else:
        overall = "neutral"
        summary = "自选池与今日主线无明确关联。"

    return ModuleSection(
        key="watchlist_impact",
        title="自选池影响",
        status="ready",
        summary=summary,
        content={
            "overall": overall,
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "divergent": divergent,
        },
        confidence="medium",
    )


def build_risk_radar_module(snapshot: dict, missing_data: list[str]) -> ModuleSection:
    """生成风险雷达，区分 market/sector/watchlist/data 四类。"""
    market_risks: list[dict] = []
    sector_risks: list[dict] = []
    watchlist_risks: list[dict] = []
    data_risks: list[dict] = []
    warnings: list[str] = []

    breadth = snapshot.get("market_breadth") or {}
    up = breadth.get("up", 0)
    down = breadth.get("down", 0)
    limit_down = breadth.get("limit_down", 0)
    total = breadth.get("total", 1)
    volume = breadth.get("volume", 0)

    # 市场宽度风险
    if total > 0 and down > up * 1.3:
        market_risks.append({
            "level": "high",
            "signal": "市场宽度持续恶化",
            "detail": f"下跌家数 {down} 显著超过上涨 {up}，宽度指标走弱",
        })
    if total > 0 and up + down < total * 0.5:
        market_risks.append({
            "level": "medium",
            "signal": "市场成交不活跃",
            "detail": f"涨跌家数仅 {up + down}，低于总家数 {total} 的 50%",
        })
    if limit_down > 30:
        market_risks.append({
            "level": "high",
            "signal": "跌停家数明显增多",
            "detail": f"跌停 {limit_down} 家，亏钱效应明显",
        })
    if volume and volume < 5000:
        market_risks.append({
            "level": "low",
            "signal": "成交额偏低",
            "detail": f"成交额 {volume:.0f} 亿元，市场活跃度一般",
        })

    # 板块风险：领涨主题退潮检测（简化版）
    sectors = snapshot.get("industry_sectors") or []
    if sectors:
        top = sectors[0] if sectors else {}
        if (top.get("change_pct", 0) or 0) < 0.1 and len(sectors) > 5:
            sector_risks.append({
                "level": "medium",
                "signal": "领涨板块涨幅收窄",
                "detail": f"最强板块 {top.get('name', '?')} 仅涨 {top.get('change_pct', 0):.2f}%",
            })

    # 自选池风险
    watchlist = snapshot.get("watchlist_changes") or []
    laggards = []
    for fund in watchlist:
        ret = (fund.get("period_returns") or {}).get("1d", 0) or 0
        if ret < -2.0:
            laggards.append(f"{fund.get('fund_name', fund.get('fund_code', ''))} ({ret:+.2f}%)")
    if len(laggards) >= 3:
        watchlist_risks.append({
            "level": "high",
            "signal": "多只基金明显跑输",
            "detail": f"{'、'.join(laggards[:3])}等跌幅超过 2%",
        })

    # 数据风险
    data_risk_map = {
        "market_breadth": ("市场宽度数据缺失", "high"),
        "industry_flows": ("行业资金流数据缺失", "medium"),
        "concept_flows": ("概念资金流数据缺失", "medium"),
        "concept_sectors": ("概念板块数据缺失", "medium"),
        "policy_evidence": ("政策证据缺失", "low"),
        "macro_evidence": ("宏观证据缺失", "low"),
        "announcement_evidence": ("公告证据缺失", "low"),
    }
    for key in missing_data:
        label, level = data_risk_map.get(key, (f"{key} 缺失", "low"))
        data_risks.append({"level": level, "signal": label})

    all_risks = market_risks + sector_risks + watchlist_risks + data_risks
    has_high = any(r["level"] == "high" for r in all_risks)
    summary = f"发现 {len(all_risks)} 条风险信号" if all_risks else "未发现明显风险信号"

    return ModuleSection(
        key="risk_radar",
        title="风险雷达",
        status="ready",
        summary=summary,
        content={
            "market": market_risks,
            "sector": sector_risks,
            "watchlist": watchlist_risks,
            "data": data_risks,
        },
        warnings=warnings,
        confidence="medium",
    )


def build_key_evidence_module(evidence: list[dict]) -> ModuleSection:
    """从 evidence 列表中提取关键证据并增加 freshness/weight 字段。"""
    if not evidence:
        return ModuleSection(
            key="key_evidence",
            title="关键证据",
            status="missing",
            summary="本地暂无市场证据，无法引用。",
            content={"items": []},
            missing_data=["policy_evidence", "announcement_evidence", "macro_evidence"],
            confidence="low",
        )

    from datetime import datetime, timezone, timedelta

    items: list[dict] = []
    now = datetime.now(timezone.utc)

    for e in evidence:
        published_str = e.get("published_at") or ""
        freshness = "older"
        try:
            pub_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            delta = (now - pub_dt.astimezone(timezone.utc)).total_seconds()
            if delta < 3600:
                freshness = "realtime"
            elif delta < 86400:
                freshness = "today"
            elif delta < 259200:
                freshness = "recent"
            else:
                freshness = "older"
        except Exception:
            pass

        # weight 基于来源和 category
        source = e.get("source", "") or ""
        category = e.get("category", "") or ""
        weight = "low"
        if category == "policy" or "交易所" in source or "证监会" in source:
            weight = "high"
        elif category in ("announcement", "macro") or source:
            weight = "medium"

        items.append({
            "evidence_id": e.get("id"),
            "category": category,
            "title": e.get("title", ""),
            "source": e.get("source", ""),
            "source_url": e.get("source_url", ""),
            "published_at": published_str,
            "freshness": freshness,
            "weight": weight,
        })

    # 按 weight 和 freshness 排序，高权重优先
    weight_order = {"high": 0, "medium": 1, "low": 2}
    freshness_order = {"realtime": 0, "today": 1, "recent": 2, "older": 3}
    items.sort(key=lambda x: (weight_order.get(x["weight"], 2), freshness_order.get(x["freshness"], 3)))
    top_items = items[:10]

    summary = f"本次简报引用 {len(top_items)} 条关键证据。"
    return ModuleSection(
        key="key_evidence",
        title="关键证据",
        status="ready",
        summary=summary,
        content={"items": top_items},
        evidence_ids=[e.get("id") for e in top_items if e.get("id")],
        confidence="medium",
    )


def build_data_statement_module(
    as_of: str,
    briefing_date: str,
    data_quality: str,
    confidence: str,
    missing_data: list[str],
    failed_modules: list[dict],
    data_sources_last_updated: dict,
    evidence_count: int,
    all_module_statuses: dict[str, str],
) -> ModuleSection:
    """生成数据质量声明，包含 failed_modules 汇总。"""
    content = {
        "data_quality": data_quality,
        "confidence": confidence,
        "missing_data": missing_data,
        "failed_modules": failed_modules,
        "data_sources_last_updated": data_sources_last_updated,
        "disclaimer": "本简报为本地数据自动生成，不构成投资建议。",
    }

    warnings: list[str] = []
    # 汇总失败模块
    failed_module_names = [
        f"{fm['module']}({fm.get('fund_code', '') or fm.get('reason', '')})"
        for fm in failed_modules
    ]
    if failed_module_names:
        warnings.append(f"失败模块：{', '.join(failed_module_names)}")

    # 汇总各模块状态
    failed_status_modules = [k for k, v in all_module_statuses.items() if v == "failed"]
    if failed_status_modules:
        warnings.append(f"以下模块未成功生成：{', '.join(failed_status_modules)}")

    missing_labels = {
        "market_snapshot": "行情指数",
        "market_breadth": "市场宽度",
        "industry_sectors": "行业板块",
        "concept_sectors": "概念板块",
        "industry_flows": "行业资金流",
        "concept_flows": "概念资金流",
        "policy_evidence": "政策证据",
        "announcement_evidence": "公告证据",
        "macro_evidence": "宏观证据",
    }
    missing_labels_display = [missing_labels.get(m, m) for m in missing_data]
    summary_parts = [f"数据质量：{data_quality}，置信度：{confidence}"]
    if missing_labels_display:
        summary_parts.append(f"缺失：{', '.join(missing_labels_display)}")
    if evidence_count > 0:
        summary_parts.append(f"证据 {evidence_count} 条")

    return ModuleSection(
        key="data_statement",
        title="数据质量",
        status="ready",
        summary="，".join(summary_parts),
        content=content,
        missing_data=missing_data,
        warnings=warnings,
        confidence=confidence,
    )


def build_quick_summary_module(
    market_state_mod: ModuleSection | None,
    themes_mod: ModuleSection | None,
    watchlist_mod: ModuleSection | None,
    risk_mod: ModuleSection | None,
    data_quality: str,
    confidence: str,
) -> ModuleSection:
    """基于已完成模块聚合生成 30 秒摘要。"""
    sections = {
        "market_state": market_state_mod,
        "themes": themes_mod,
        "watchlist": watchlist_mod,
        "risk": risk_mod,
    }

    market_state = ""
    if market_state_mod and market_state_mod.content:
        market_state = market_state_mod.content.get("label", "分化")

    main_themes: list[str] = []
    if themes_mod and themes_mod.content:
        for t in themes_mod.content.get("leading_themes", [])[:3]:
            main_themes.append(t.get("name", ""))

    top_risks: list[str] = []
    if risk_mod and risk_mod.content:
        for risk_list in [risk_mod.content.get("market", []), risk_mod.content.get("sector", [])]:
            for r in risk_list[:2]:
                if r.get("level") == "high":
                    top_risks.append(r.get("signal", ""))

    watchlist_impact = "neutral"
    if watchlist_mod and watchlist_mod.content:
        watchlist_impact = watchlist_mod.content.get("overall", "neutral")

    return ModuleSection(
        key="quick_summary",
        title="30 秒摘要",
        status="ready",
        summary="，".join([
            f"市场{market_state}" if market_state else "市场状态待确认",
            f"主线：{'、'.join(main_themes) if main_themes else '暂无'}",
            f"自选池：{watchlist_impact}",
        ]),
        content={
            "market_state": market_state,
            "main_themes": main_themes,
            "top_risks": top_risks[:3],
            "watchlist_impact": watchlist_impact,
            "confidence": confidence,
        },
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Module Runner
# ---------------------------------------------------------------------------

def build_overnight_module(evidence: list[dict], snapshot: dict | None = None) -> ModuleSection:
    """盘前模块：依赖隔夜海外/盘前 evidence。无可用数据时返回 missing。"""
    overnight_evidence = [
        e for e in evidence
        if e.get("category") in ("macro", "news")
        and e.get("title")
    ]
    if not overnight_evidence and not (snapshot or {}).get("overnight_overseas"):
        return ModuleSection(
            key="overnight",
            title="隔夜外围",
            status="missing",
            summary="暂无隔夜外围数据，盘前简报无法生成该模块。",
            content={"events": []},
            missing_data=["overnight_overseas", "pre_market_news"],
            confidence="low",
        )
    events = [
        {
            "type": e.get("category"),
            "name": e.get("title"),
            "source": e.get("source"),
            "published_at": e.get("published_at"),
            "impact": "medium" if e.get("category") == "policy" else "low",
        }
        for e in overnight_evidence[:10]
    ]
    return ModuleSection(
        key="overnight",
        title="隔夜外围",
        status="ready",
        summary=f"采集到 {len(events)} 条隔夜/盘前事件。",
        content={"events": events, "items": events},
        confidence="medium",
    )


def build_intraday_anomaly_module(snapshot: dict) -> ModuleSection:
    """盘中模块：基于盘中行情和宽度判断异动。"""
    breadth = (snapshot or {}).get("market_breadth") or {}
    sectors = (snapshot or {}).get("industry_sectors") or []
    up = breadth.get("up", 0)
    down = breadth.get("down", 0)
    total = breadth.get("total", 1) or 1

    anomalies: list[dict] = []
    if total > 0 and abs(up - down) / total < 0.05:
        anomalies.append({
            "type": "breadth_convergence",
            "level": "medium",
            "detail": f"涨跌家数收敛（{up}/{down}），市场处于风格切换点",
        })
    if sectors:
        top = sectors[0] if sectors else {}
        if abs(top.get("change_pct", 0) or 0) > 3:
            anomalies.append({
                "type": "sector_spike",
                "level": "high",
                "detail": f"领涨板块 {top.get('name', '?')} 单日异动 {top.get('change_pct', 0):.2f}%",
            })
    if not anomalies:
        return ModuleSection(
            key="intraday_anomaly",
            title="盘中异动",
            status="partial",
            summary="盘中暂无显著异动信号。",
            content={"anomalies": []},
            confidence="low",
        )
    return ModuleSection(
        key="intraday_anomaly",
        title="盘中异动",
        status="ready",
        summary=f"检测到 {len(anomalies)} 项盘中异动。",
        content={"anomalies": anomalies},
        confidence="medium",
    )


def _builder_for_module(module_key: str):
    """返回 module_key 对应的 builder 函数。"""
    registry: dict[str, Any] = {
        "market_state": build_market_state_module,
        "themes_and_flows": build_themes_and_flows_module,
        "watchlist_impact": build_watchlist_impact_module,
        "risk_radar": build_risk_radar_module,
        "key_evidence": build_key_evidence_module,
        "data_statement": build_data_statement_module,
        "quick_summary": build_quick_summary_module,
        "overnight": build_overnight_module,
        "intraday_anomaly": build_intraday_anomaly_module,
    }
    return registry.get(module_key)


def run_module_builders(
    profile: BriefTypeProfile,
    snapshot: dict,
    evidence: list[dict],
    context: dict,
) -> tuple[dict[str, ModuleSection], list[str]]:
    """按 profile 顺序执行所有 module builders。

    Args:
        profile: 简报类型配置
        snapshot: 市场快照数据
        evidence: 证据列表
        context: 额外上下文（包含 theme_context 等）

    Returns:
        (modules_dict, warnings)
        modules_dict: key -> ModuleSection
    """
    warnings: list[str] = []
    modules: dict[str, ModuleSection] = {}
    module_order: list[str] = []

    # 构建 theme_context 供多个模块共享
    # 先跑一次 themes_and_flows，得到 leading/lagging 主题
    theme_context_raw: dict = {}
    if "themes_and_flows" in profile.required_modules:
        try:
            tf_mod = build_themes_and_flows_module(snapshot, evidence)
            modules["themes_and_flows"] = tf_mod
            module_order.append("themes_and_flows")
            # 提取主题列表构建 context
            if tf_mod.content:
                theme_context_raw["leading_themes"] = [
                    t.get("name", "") for t in tf_mod.content.get("leading_themes", [])
                ]
                theme_context_raw["lagging_themes"] = [
                    t.get("name", "") for t in tf_mod.content.get("lagging_themes", [])
                ]
        except Exception as exc:
            modules["themes_and_flows"] = ModuleSection(
                key="themes_and_flows", title="主线与资金",
                status="failed", summary=f"生成失败：{exc}",
                warnings=[str(exc)], confidence="low",
            )
            module_order.append("themes_and_flows")
            warnings.append(f"themes_and_flows 模块失败：{exc}")

    # 执行其余内容模块（跳过 quick_summary 和 data_statement，跳过 forbidden）
    special = {"quick_summary", "data_statement", "themes_and_flows"}
    for mk in profile.required_modules:
        if mk in special:
            continue
        if mk in profile.forbidden_modules:
            warnings.append(f"模块 {mk} 被 profile 禁止，跳过")
            continue
        builder = _builder_for_module(mk)
        if builder is None:
            warnings.append(f"未找到模块 {mk} 的 builder，跳过")
            continue
        try:
            if mk == "watchlist_impact":
                mod = builder(snapshot, theme_context_raw)
            elif mk == "overnight":
                mod = builder(evidence, snapshot)
            elif mk in ("risk_radar",):
                # 从已生成的模块收集 missing_data
                all_missing = set()
                for existing_mod in modules.values():
                    all_missing.update(existing_mod.missing_data)
                if mk == "risk_radar":
                    mod = builder(snapshot, list(all_missing))
            elif mk == "key_evidence":
                mod = builder(evidence)
            elif mk == "market_state":
                mod = builder(snapshot, evidence)
            else:
                mod = builder(snapshot)
            modules[mk] = mod
            module_order.append(mk)
        except Exception as exc:
            modules[mk] = ModuleSection(
                key=mk, title=mk.replace("_", " ").title(),
                status="failed", summary=f"生成失败：{exc}",
                warnings=[str(exc)], confidence="low",
            )
            module_order.append(mk)
            warnings.append(f"{mk} 模块失败：{exc}")

    # 执行 optional_modules
    for mk in profile.optional_modules:
        if mk in special or mk in modules:
            continue
        if mk in profile.forbidden_modules:
            continue
        builder = _builder_for_module(mk)
        if builder is None:
            continue
        try:
            if mk == "key_evidence":
                mod = builder(evidence)
            elif mk == "overnight":
                mod = builder(evidence, snapshot)
            else:
                mod = builder(snapshot)
            modules[mk] = mod
            module_order.append(mk)
        except Exception:
            pass  # optional 模块失败不阻塞

    return modules, module_order, warnings


def run_quick_summary_module(
    profile: BriefTypeProfile,
    modules: dict[str, ModuleSection],
    data_quality: str,
    confidence: str,
) -> ModuleSection:
    """在所有内容模块之后执行 quick_summary。"""
    try:
        return build_quick_summary_module(
            market_state_mod=modules.get("market_state"),
            themes_mod=modules.get("themes_and_flows"),
            watchlist_mod=modules.get("watchlist_impact"),
            risk_mod=modules.get("risk_radar"),
            data_quality=data_quality,
            confidence=confidence,
        )
    except Exception as exc:
        return ModuleSection(
            key="quick_summary", title="30 秒摘要",
            status="failed", summary="摘要生成失败",
            warnings=[str(exc)], confidence="low",
        )


def run_data_statement_module(
    modules: dict[str, ModuleSection],
    as_of: str,
    briefing_date: str,
    data_quality: str,
    confidence: str,
    missing_data: list[str],
    failed_modules: list[dict],
    data_sources_last_updated: dict,
    evidence_count: int,
) -> ModuleSection:
    """最后执行 data_statement，汇总所有模块状态。"""
    all_statuses = {mk: m.status for mk, m in modules.items()}
    try:
        return build_data_statement_module(
            as_of=as_of,
            briefing_date=briefing_date,
            data_quality=data_quality,
            confidence=confidence,
            missing_data=missing_data,
            failed_modules=failed_modules,
            data_sources_last_updated=data_sources_last_updated,
            evidence_count=evidence_count,
            all_module_statuses=all_statuses,
        )
    except Exception as exc:
        return ModuleSection(
            key="data_statement", title="数据质量",
            status="failed", summary="数据声明生成失败",
            warnings=[str(exc)], confidence="low",
        )


def compose_briefing_v2(
    profile: BriefTypeProfile,
    modules: dict[str, ModuleSection],
    quick_summary_mod: ModuleSection,
    data_statement_mod: ModuleSection,
    snapshot: dict,
    evidence: list[dict],
) -> dict:
    """V2 final composer：把 module sections 组织成最终 markdown。

    LLM 负责压缩和语言组织，不重新生成结构化数据。
    返回 dict: {markdown, sections, warnings, markdown_warnings}
    """
    from string import Template

    # 构建 module_sections JSON 给 LLM
    module_sections_json = {}
    for mk, m in modules.items():
        module_sections_json[mk] = m.to_dict()
    module_sections_json["quick_summary"] = quick_summary_mod.to_dict()
    module_sections_json["data_statement"] = data_statement_mod.to_dict()

    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    evidence_json = json.dumps(evidence or [], ensure_ascii=False, indent=2)
    module_json = json.dumps(module_sections_json, ensure_ascii=False, indent=2)

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

    from backend.graph import model as _model_module
    model = _model_module.build_model()
    response = model.invoke(prompt)
    raw_content = response.content if hasattr(response, "content") else str(response)

    markdown_warnings: list[str] = []
    markdown_text = raw_content

    # 尝试解析 JSON（只取 markdown 和 markdown_warnings）
    def _parse(candidate: str) -> tuple[dict | None, str | None]:
        try:
            return json.loads(candidate), None
        except (json.JSONDecodeError, TypeError) as exc:
            return None, str(exc)

    parsed, _ = _parse(raw_content)
    if parsed is not None:
        markdown_text = parsed.get("markdown", raw_content)
        markdown_warnings = parsed.get("markdown_warnings", [])
    else:
        # 剥外层 braces
        candidate = raw_content.strip()
        for _ in range(4):
            if candidate.startswith("{") and candidate.endswith("}"):
                candidate = candidate[1:-1].strip()
                parsed_inner, _ = _parse(candidate)
                if parsed_inner:
                    markdown_text = parsed_inner.get("markdown", raw_content)
                    markdown_warnings = parsed_inner.get("markdown_warnings", [])
                    markdown_warnings.append("llm_returned_wrapped_json，已剥除外层")
                    break
        else:
            markdown_warnings.append("llm_returned_non_json，使用原始文本")

    return {
        "markdown": markdown_text,
        "sections": module_sections_json,
        "warnings": markdown_warnings,
        "markdown_warnings": markdown_warnings,
    }
