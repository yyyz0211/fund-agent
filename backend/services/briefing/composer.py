"""Briefing composer: LLM 编排."""
from __future__ import annotations

import json
from datetime import datetime

from backend.config import settings as app_settings
from backend.services.briefing import collectors, modules
from backend.services.briefing.prompts import BRIEFING_PROMPT_TEMPLATE_V2
from backend.services.briefing.types import BriefTypeProfile, ChatModel, ModuleSection

settings = app_settings.get_settings()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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

    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    evidence_json = json.dumps(evidence or [], ensure_ascii=False, indent=2)

    # 决定 profile：默认 post_market
    if profile is None:
        profile, _profile_warnings = modules.get_brief_type_profile("post_market")

    # V2: 跑 module builders
    modules_built, module_order, _module_warnings = modules.run_module_builders(
        profile=profile, snapshot=snapshot, evidence=evidence or [], context={},
    )
    # data quality
    quality = collectors.compute_data_quality(snapshot, evidence or [])
    quick_summary_mod = modules.run_quick_summary_module(
        profile=profile,
        modules=modules_built,
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
    data_statement_mod = modules.run_data_statement_module(
        modules=modules_built,
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
        for mk, m in modules_built.items()
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


def compose_briefing_v2(
    profile: BriefTypeProfile,
    modules: dict[str, ModuleSection],
    quick_summary_mod: ModuleSection,
    data_statement_mod: ModuleSection,
    snapshot: dict,
    evidence: list[dict],
    *,
    model: ChatModel | None = None,
) -> dict:
    """V2 final composer：把 module sections 组织成最终 markdown。

    LLM 负责压缩和语言组织，不重新生成结构化数据。
    返回 dict: {markdown, sections, warnings, markdown_warnings}

    Args:
        model: 聊天模型实例。**必须**由 composition root 注入。`None` 时
            立即 `RuntimeError`,与 `compose_briefing` 保持一致。
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

    # Phase 1.1: model 由 composition root 注入,缺则立即失败(不要 lazy import)。
    if model is None:
        raise RuntimeError(
            "compose_briefing_v2 requires `model` to be injected by the composition root."
        )
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


__all__ = ["compose_briefing", "compose_briefing_v2"]
