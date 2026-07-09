# 每日简报 V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing daily briefing from a single LLM-generated markdown article into a profile-driven, module-based briefing system with structured `sections_json`, safer LLM boundaries, and a V2-ready frontend renderer.

**Architecture:** Keep the existing `Briefing` table and `/api/briefing/*` contract for Phase 1-3, but move briefing logic into small V2 helpers: profiles choose modules, module builders produce authoritative structured results, and the final composer only asks the LLM for markdown. Phase 4 adds `brief_type` persistence and API filters so `pre_market`, `intraday`, and `post_market` can coexist.

**Tech Stack:** Python, SQLAlchemy, FastAPI, pytest, React/Next.js, TypeScript, ReactMarkdown, Node test runner.

## Global Constraints

- Do not output automatic trading, buy/sell, add/reduce position, or timing advice.
- Do not predict tomorrow's market direction.
- Do not create a full news feed or CLS telegraph list page in this plan.
- Do not force all evidence into the briefing body.
- Do not perform real fund holding look-through in Phase 1-4; first pass uses fund name, notes, and keyword matching.
- Do not rebuild the `Briefing` table for Phase 1-3.
- Keep `/api/briefing/latest`, `/api/briefing/list`, and `/api/briefing/run` backward-compatible until Phase 4.
- Phase 1-4 do not implement user feedback collection; Phase 5 handles feedback.
- Every briefing must include `quick_summary` and `data_statement`.
- `sections_json` V2 shape is `{brief_type, profile_version, module_order, modules, warnings}`.
- `Briefing.markdown` stores markdown; do not duplicate markdown in `sections_json`.
- Each module uses the envelope `{key, title, status, summary, content, evidence_ids, missing_data, warnings, confidence}`.
- Module-specific data goes inside `content`.
- LLM output may only supply `markdown` and `markdown_warnings`; ignore any LLM-provided `modules` or `sections`.
- If LLM JSON parsing fails, use raw text as `Briefing.markdown` and still preserve backend-built `sections_json`.
- `brief_type` Phase 4 migration must default old rows to `post_market`.
- Phase 4 uniqueness target is `(briefing_date, brief_type)`.

---

## File Structure

Create or modify these files:

- Create `backend/services/briefing_v2_profiles.py`
  - Owns `BriefTypeProfile`, module status constants, module envelope helpers, profile registry, and `get_brief_type_profile`.
- Create `backend/services/briefing_v2_modules.py`
  - Owns deterministic module builders, `theme_context`, risk levels, evidence scoring, and `run_module_builders`.
- Create `backend/services/briefing_v2_composer.py`
  - Owns prompt building and `compose_briefing_v2`; calls the LLM only for markdown.
- Modify `backend/services/briefing_service.py`
  - Keeps collection and persistence orchestration, but routes daily generation through V2 helpers for `post_market`.
- Modify `backend/graph/prompts.py`
  - Replaces the old briefing prompt with a V2 markdown-only prompt.
- Modify `backend/db/models.py`
  - Phase 4: add `Briefing.brief_type` and adjust unique constraint behavior.
- Modify `backend/db/init_db.py`
  - Phase 4: add lightweight migration for `brief_type`; if unique constraint rebuild is needed, implement a controlled SQLite table rebuild.
- Modify `backend/db/repository.py`
  - Add `brief_type`-aware `upsert_briefing`, latest, and list helpers.
- Modify `backend/api/routes/briefing.py`
  - Add optional `type` query parameter and `brief_type` run payload support in Phase 4.
- Modify `backend/scheduler.py`
  - Phase 4: schedule `post_market`; optionally add `pre_market` once its profile is enabled.
- Modify `backend/tools/market_tools.py`
  - Read latest briefing by optional `brief_type` and preserve V2 sections.
- Modify `frontend/src/types/api.ts`
  - Add V2 module section types and `brief_type`.
- Modify `frontend/src/lib/api.ts`
  - Add optional `type` params for briefing latest/list and optional `brief_type` body for run.
- Modify `frontend/app/briefing/page.tsx`
  - Render V2 modules by `module_order`, with markdown fallback for old briefings.
- Modify `frontend/tests/briefing-ui.test.mjs`
  - Add V2 module rendering tests and fallback tests.
- Add `backend/tests/test_briefing_v2_profiles.py`
- Add `backend/tests/test_briefing_v2_modules.py`
- Add `backend/tests/test_briefing_v2_composer.py`
- Modify `backend/tests/test_briefing_service.py`
- Modify `backend/tests/test_briefing_route.py`
- Modify `backend/tests/test_models.py`
- Modify `backend/tests/test_repository.py`
- Modify `backend/tests/test_scheduler_briefing.py`

---

### Task 1: Briefing V2 Profiles And Module Envelope

**Files:**
- Create: `backend/services/briefing_v2_profiles.py`
- Add: `backend/tests/test_briefing_v2_profiles.py`

**Interfaces:**
- Produces:
  - `BriefTypeProfile`
  - `MODULE_READY = "ready"`, `MODULE_PARTIAL = "partial"`, `MODULE_MISSING = "missing"`, `MODULE_FAILED = "failed"`
  - `make_module_section(key: str, title: str, status: str, summary: str, content: dict | None = None, evidence_ids: list[int] | None = None, missing_data: list[str] | None = None, warnings: list[str] | None = None, confidence: str = "medium") -> dict`
  - `get_brief_type_profile(brief_type: str | None) -> tuple[BriefTypeProfile, list[str]]`
- Consumes: no project services.

- [ ] **Step 1: Write failing profile tests**

Create `backend/tests/test_briefing_v2_profiles.py`:

```python
from __future__ import annotations


def test_post_market_profile_modules_and_forbidden_modules():
    from backend.services.briefing_v2_profiles import get_brief_type_profile

    profile, warnings = get_brief_type_profile("post_market")

    assert warnings == []
    assert profile.brief_type == "post_market"
    assert profile.required_modules == [
        "quick_summary",
        "market_state",
        "themes_and_flows",
        "watchlist_impact",
        "risk_radar",
        "key_evidence",
        "data_statement",
    ]
    assert profile.forbidden_modules == ["overnight", "intraday_anomaly"]
    assert profile.data_window == "trade_date_full_day"
    assert profile.max_markdown_words == 1000


def test_pre_market_profile_omits_post_market_replay_modules():
    from backend.services.briefing_v2_profiles import get_brief_type_profile

    profile, warnings = get_brief_type_profile("pre_market")

    assert warnings == []
    assert "overnight" in profile.required_modules
    assert "themes_and_flows" not in profile.required_modules
    assert "intraday_anomaly" in profile.forbidden_modules


def test_unknown_profile_falls_back_to_post_market_with_warning():
    from backend.services.briefing_v2_profiles import get_brief_type_profile

    profile, warnings = get_brief_type_profile("closing_notes")

    assert profile.brief_type == "post_market"
    assert warnings == ["unknown_brief_type:closing_notes;fallback:post_market"]


def test_make_module_section_uses_content_envelope():
    from backend.services.briefing_v2_profiles import make_module_section

    section = make_module_section(
        key="market_state",
        title="市场状态",
        status="ready",
        summary="指数上涨但宽度一般。",
        content={"label": "分化"},
        evidence_ids=[1, 2],
        missing_data=["breadth"],
        warnings=["breadth_partial"],
        confidence="medium",
    )

    assert section == {
        "key": "market_state",
        "title": "市场状态",
        "status": "ready",
        "summary": "指数上涨但宽度一般。",
        "content": {"label": "分化"},
        "evidence_ids": [1, 2],
        "missing_data": ["breadth"],
        "warnings": ["breadth_partial"],
        "confidence": "medium",
    }
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_v2_profiles.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.briefing_v2_profiles'`.

- [ ] **Step 3: Implement profiles and envelope helper**

Create `backend/services/briefing_v2_profiles.py` with:

```python
"""Briefing V2 profile and module envelope definitions."""
from __future__ import annotations

from dataclasses import dataclass


MODULE_READY = "ready"
MODULE_PARTIAL = "partial"
MODULE_MISSING = "missing"
MODULE_FAILED = "failed"


@dataclass(frozen=True)
class BriefTypeProfile:
    brief_type: str
    title: str
    required_modules: list[str]
    optional_modules: list[str]
    forbidden_modules: list[str]
    data_window: str
    max_markdown_words: int = 1000


POST_MARKET_PROFILE = BriefTypeProfile(
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


PRE_MARKET_PROFILE = BriefTypeProfile(
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
    optional_modules=[],
    forbidden_modules=["themes_and_flows", "intraday_anomaly"],
    data_window="pre_market_window",
    max_markdown_words=800,
)


INTRADAY_PROFILE = BriefTypeProfile(
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
    optional_modules=[],
    forbidden_modules=["overnight"],
    data_window="intraday_snapshot",
    max_markdown_words=800,
)


_PROFILES = {
    "post_market": POST_MARKET_PROFILE,
    "pre_market": PRE_MARKET_PROFILE,
    "intraday": INTRADAY_PROFILE,
}


def get_brief_type_profile(brief_type: str | None) -> tuple[BriefTypeProfile, list[str]]:
    normalized = (brief_type or "post_market").strip() or "post_market"
    profile = _PROFILES.get(normalized)
    if profile is not None:
        return profile, []
    return POST_MARKET_PROFILE, [f"unknown_brief_type:{normalized};fallback:post_market"]


def make_module_section(
    *,
    key: str,
    title: str,
    status: str,
    summary: str,
    content: dict | None = None,
    evidence_ids: list[int] | None = None,
    missing_data: list[str] | None = None,
    warnings: list[str] | None = None,
    confidence: str = "medium",
) -> dict:
    return {
        "key": key,
        "title": title,
        "status": status,
        "summary": summary,
        "content": content or {},
        "evidence_ids": list(evidence_ids or []),
        "missing_data": list(missing_data or []),
        "warnings": list(warnings or []),
        "confidence": confidence,
    }
```

- [ ] **Step 4: Run profile tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_v2_profiles.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/briefing_v2_profiles.py backend/tests/test_briefing_v2_profiles.py
git commit -m "feat(briefing): add v2 profiles and module envelope"
```

---

### Task 2: Deterministic Module Builders And Runner

**Files:**
- Create: `backend/services/briefing_v2_modules.py`
- Add: `backend/tests/test_briefing_v2_modules.py`

**Interfaces:**
- Consumes:
  - `BriefTypeProfile`
  - `make_module_section`
- Produces:
  - `build_theme_context(context: dict, sections_by_key: dict[str, dict]) -> dict`
  - `market_state_module(context: dict, profile: BriefTypeProfile) -> dict`
  - `themes_and_flows_module(context: dict, profile: BriefTypeProfile) -> dict`
  - `watchlist_impact_module(context: dict, profile: BriefTypeProfile, theme_context: dict) -> dict`
  - `risk_radar_module(context: dict, profile: BriefTypeProfile, sections_by_key: dict[str, dict]) -> dict`
  - `key_evidence_module(context: dict, profile: BriefTypeProfile, sections_by_key: dict[str, dict]) -> dict`
  - `quick_summary_module(context: dict, profile: BriefTypeProfile, sections_by_key: dict[str, dict], quality: dict) -> dict`
  - `data_statement_module(context: dict, profile: BriefTypeProfile, sections_by_key: dict[str, dict], quality: dict) -> dict`
  - `run_module_builders(context: dict, profile: BriefTypeProfile, quality: dict) -> tuple[list[str], dict[str, dict], list[str]]`

- [ ] **Step 1: Write failing module builder tests**

Create `backend/tests/test_briefing_v2_modules.py`:

```python
from __future__ import annotations


def _profile():
    from backend.services.briefing_v2_profiles import get_brief_type_profile

    return get_brief_type_profile("post_market")[0]


def _context():
    return {
        "trade_date": "2026-07-09",
        "as_of": "2026-07-09",
        "snapshot": {
            "market_snapshot": [
                {"name": "上证指数", "change_pct": 0.8, "close": 3100.0},
                {"name": "创业板指", "change_pct": -0.2, "close": 1900.0},
            ],
            "market_breadth": {
                "up": 1800,
                "down": 3100,
                "limit_up": 35,
                "limit_down": 12,
                "volume": 8800,
            },
            "industry_sectors": [
                {"name": "半导体", "change_pct": 3.2},
                {"name": "煤炭", "change_pct": -2.4},
            ],
            "concept_sectors": [
                {"name": "AI 算力", "change_pct": 4.1},
                {"name": "光伏", "change_pct": -1.7},
            ],
            "industry_flows": [
                {"name": "半导体", "net_flow": 12.5},
                {"name": "煤炭", "net_flow": -6.2},
            ],
            "concept_flows": [],
            "watchlist_changes": [
                {
                    "fund_code": "012345",
                    "fund_name": "示例半导体主题基金",
                    "period_returns": {"1d": 0.011, "1w": 0.02, "1m": 0.03},
                },
                {
                    "fund_code": "678901",
                    "fund_name": "示例消费基金",
                    "period_returns": {"1d": -0.004, "1w": 0.01, "1m": 0.02},
                },
            ],
            "collect_meta": {"warnings": []},
        },
        "evidence": [
            {
                "id": 1,
                "category": "news",
                "title": "AI 算力板块走强",
                "summary": "财联社电报称 AI 算力方向活跃",
                "source": "财联社",
                "source_url": "https://www.cls.cn/detail/1",
                "published_at": "2026-07-09T14:35:00",
            }
        ],
        "data_sources_last_updated": {
            "market_snapshot": "2026-07-09T15:30:00+08:00",
            "cls_telegraph": "2026-07-09T17:00:00+08:00",
        },
    }


def test_market_state_module_detects_index_breadth_divergence():
    from backend.services.briefing_v2_modules import market_state_module

    section = market_state_module(_context(), _profile())

    assert section["key"] == "market_state"
    assert section["status"] == "ready"
    assert section["content"]["label"] == "分化"
    assert any("下跌家数" in r for r in section["content"]["reasons"])


def test_themes_and_flows_marks_missing_concept_flows_partial():
    from backend.services.briefing_v2_modules import themes_and_flows_module

    section = themes_and_flows_module(_context(), _profile())

    assert section["key"] == "themes_and_flows"
    assert section["status"] == "partial"
    assert "concept_flows" in section["missing_data"]
    assert section["content"]["leading_themes"][0]["name"] in {"AI 算力", "半导体"}


def test_watchlist_impact_uses_theme_context_keyword_match():
    from backend.services.briefing_v2_modules import watchlist_impact_module

    theme_context = {"leading": ["半导体", "AI 算力"], "lagging": ["煤炭"], "source": "themes_and_flows"}
    section = watchlist_impact_module(_context(), _profile(), theme_context)

    assert section["status"] == "ready"
    assert section["content"]["overall"] == "mixed"
    assert section["content"]["positive"][0]["fund_code"] == "012345"


def test_run_module_builders_orders_quick_summary_first_and_data_statement_last():
    from backend.services.briefing_v2_modules import run_module_builders

    order, modules, warnings = run_module_builders(
        _context(),
        _profile(),
        {"data_quality": "partial", "confidence": "medium", "missing_data": ["macro_evidence"]},
    )

    assert warnings == []
    assert order[0] == "quick_summary"
    assert order[-1] == "data_statement"
    assert set(order) == set(modules)
    assert modules["data_statement"]["content"]["failed_modules"] == []
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_v2_modules.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.briefing_v2_modules'`.

- [ ] **Step 3: Implement module builders**

Create `backend/services/briefing_v2_modules.py`. Include the following required constants and helper structure:

```python
"""Deterministic Briefing V2 module builders."""
from __future__ import annotations

from typing import Any

from backend.services.briefing_v2_profiles import (
    BriefTypeProfile,
    MODULE_FAILED,
    MODULE_MISSING,
    MODULE_PARTIAL,
    MODULE_READY,
    make_module_section,
)


THEME_KEYWORDS = {
    "科技成长": ["AI", "人工智能", "算力", "半导体", "芯片"],
    "新能源": ["新能源", "电池", "光伏", "储能"],
    "医药": ["医药", "创新药", "医疗"],
    "消费": ["消费", "白酒", "食品"],
    "军工": ["军工"],
    "港股": ["港股", "恒生", "中概"],
}


def _rows(snapshot: dict, key: str) -> list[dict]:
    rows = snapshot.get(key) or []
    return rows if isinstance(rows, list) else []


def _pct(row: dict) -> float:
    value = row.get("change_pct")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _flow(row: dict) -> float:
    value = row.get("net_flow")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
```

Implement the public builders with these rules:

```python
def market_state_module(context: dict, profile: BriefTypeProfile) -> dict:
    snapshot = context.get("snapshot") or {}
    indices = _rows(snapshot, "market_snapshot")
    breadth = snapshot.get("market_breadth") or {}
    missing = []
    if not indices:
        missing.append("indices")
    if not breadth:
        missing.append("breadth")
    if missing:
        return make_module_section(
            key="market_state",
            title="市场状态",
            status=MODULE_MISSING,
            summary="指数或市场宽度数据缺失，无法判断市场状态。",
            content={"label": "数据不足", "reasons": []},
            missing_data=missing,
            confidence="low",
        )
    up = int(breadth.get("up") or 0)
    down = int(breadth.get("down") or 0)
    avg_change = sum(_pct(r) for r in indices) / max(len(indices), 1)
    if avg_change > 0 and down > up:
        label = "分化"
        reasons = ["主要指数上涨，但下跌家数较多，市场宽度偏弱。"]
    elif avg_change > 0 and up >= down:
        label = "偏强"
        reasons = ["主要指数上涨，且上涨家数不低于下跌家数。"]
    elif avg_change < 0 and down > up:
        label = "偏弱"
        reasons = ["主要指数回落，且下跌家数多于上涨家数。"]
    else:
        label = "分化"
        reasons = ["指数和宽度信号不一致。"]
    return make_module_section(
        key="market_state",
        title="市场状态",
        status=MODULE_READY,
        summary=f"市场状态为{label}。",
        content={"state": label, "label": label, "reasons": reasons},
        confidence="medium",
    )
```

For `themes_and_flows_module`, sort top and bottom rows, mark empty flows as partial, and return `content.leading_themes`, `content.lagging_themes`, `content.theme_context`. For `watchlist_impact_module`, scan fund names against `THEME_KEYWORDS` and `theme_context`. For `risk_radar_module`, create a high risk when market state label is `分化` and breadth down is greater than up. For `quick_summary_module`, read previous modules and put `main_themes`, `top_risks`, `watchlist_impact`, and `confidence` under `content`. For `data_statement_module`, collect failed modules from `sections_by_key.values()` where `status == "failed"`.

Use this runner skeleton:

```python
def run_module_builders(
    context: dict,
    profile: BriefTypeProfile,
    quality: dict,
) -> tuple[list[str], dict[str, dict], list[str]]:
    modules: dict[str, dict] = {}
    warnings: list[str] = []
    content_modules = [
        key for key in profile.required_modules + profile.optional_modules
        if key not in {"quick_summary", "data_statement"}
        and key not in profile.forbidden_modules
    ]
    for key in content_modules:
        try:
            if key == "market_state":
                section = market_state_module(context, profile)
            elif key == "themes_and_flows":
                section = themes_and_flows_module(context, profile)
            elif key == "watchlist_impact":
                section = watchlist_impact_module(context, profile, build_theme_context(context, modules))
            elif key == "risk_radar":
                section = risk_radar_module(context, profile, modules)
            elif key == "key_evidence":
                section = key_evidence_module(context, profile, modules)
            elif key == "overnight":
                section = make_module_section(
                    key="overnight",
                    title="隔夜与盘前事件",
                    status=MODULE_MISSING,
                    summary="当前未接入隔夜外围数据。",
                    content={"events": []},
                    missing_data=["overnight"],
                    confidence="low",
                )
            elif key == "intraday_anomaly":
                section = make_module_section(
                    key="intraday_anomaly",
                    title="盘中异动",
                    status=MODULE_MISSING,
                    summary="当前未接入盘中异动模块。",
                    content={"items": []},
                    missing_data=["intraday_anomaly"],
                    confidence="low",
                )
            else:
                section = make_module_section(
                    key=key,
                    title=key,
                    status=MODULE_MISSING,
                    summary=f"模块 {key} 未注册。",
                    content={},
                    missing_data=[key],
                    confidence="low",
                )
        except Exception as exc:
            section = make_module_section(
                key=key,
                title=key,
                status=MODULE_FAILED,
                summary=f"模块 {key} 执行失败。",
                content={"error": str(exc)},
                warnings=[str(exc)],
                confidence="low",
            )
        modules[key] = section
    modules["quick_summary"] = quick_summary_module(context, profile, modules, quality)
    modules["data_statement"] = data_statement_module(context, profile, modules, quality)
    order = [key for key in profile.required_modules + profile.optional_modules if key in modules]
    ordered = ["quick_summary"] + [key for key in order if key not in {"quick_summary", "data_statement"}] + ["data_statement"]
    return ordered, modules, warnings
```

- [ ] **Step 4: Run module tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_v2_modules.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/briefing_v2_modules.py backend/tests/test_briefing_v2_modules.py
git commit -m "feat(briefing): add v2 module builders"
```

---

### Task 3: Markdown-Only V2 Composer

**Files:**
- Create: `backend/services/briefing_v2_composer.py`
- Add: `backend/tests/test_briefing_v2_composer.py`
- Modify: `backend/graph/prompts.py`

**Interfaces:**
- Consumes:
  - `BriefTypeProfile`
  - V2 `module_order` and `modules`
- Produces:
  - `BRIEFING_V2_MARKDOWN_PROMPT_TEMPLATE`
  - `compose_briefing_v2(context: dict, profile: BriefTypeProfile, module_order: list[str], modules: dict[str, dict], warnings: list[str] | None = None) -> dict`
  - Return shape: `{"markdown": str, "markdown_warnings": list[str], "llm_model": str, "prompt_used_chars": int}`

- [ ] **Step 1: Write failing composer tests**

Create `backend/tests/test_briefing_v2_composer.py`:

```python
from __future__ import annotations

from unittest.mock import patch

from langchain_core.messages import AIMessage


def _profile():
    from backend.services.briefing_v2_profiles import get_brief_type_profile

    return get_brief_type_profile("post_market")[0]


def _modules():
    return {
        "quick_summary": {
            "key": "quick_summary",
            "title": "30 秒摘要",
            "status": "ready",
            "summary": "今日市场偏分化。",
            "content": {"market_state": "分化", "main_themes": ["AI 算力"], "top_risks": []},
            "evidence_ids": [],
            "missing_data": [],
            "warnings": [],
            "confidence": "medium",
        },
        "data_statement": {
            "key": "data_statement",
            "title": "数据质量",
            "status": "ready",
            "summary": "数据质量为 partial。",
            "content": {"data_quality": "partial", "failed_modules": []},
            "evidence_ids": [],
            "missing_data": [],
            "warnings": [],
            "confidence": "medium",
        },
    }


def test_compose_v2_uses_only_markdown_fields_from_llm():
    from backend.services.briefing_v2_composer import compose_briefing_v2

    class FakeModel:
        def invoke(self, prompt):
            assert "module_sections" in str(prompt)
            return AIMessage(content='{"markdown":"# 简报\\n\\n正文","markdown_warnings":["short"],"modules":{"bad":true}}')

    with patch("backend.graph.model.build_model", return_value=FakeModel()):
        result = compose_briefing_v2({}, _profile(), ["quick_summary", "data_statement"], _modules())

    assert result["markdown"].startswith("# 简报")
    assert result["markdown_warnings"] == ["short"]
    assert "modules" not in result


def test_compose_v2_non_json_preserves_raw_markdown_and_warning():
    from backend.services.briefing_v2_composer import compose_briefing_v2

    class FakeModel:
        def invoke(self, _prompt):
            return AIMessage(content="纯文本简报")

    with patch("backend.graph.model.build_model", return_value=FakeModel()):
        result = compose_briefing_v2({}, _profile(), ["quick_summary", "data_statement"], _modules())

    assert result["markdown"] == "纯文本简报"
    assert "llm_returned_non_json" in result["markdown_warnings"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_v2_composer.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.briefing_v2_composer'`.

- [ ] **Step 3: Add V2 prompt template**

Modify `backend/graph/prompts.py` by adding a new prompt constant after `BRIEFING_PROMPT_TEMPLATE`:

```python
BRIEFING_V2_MARKDOWN_PROMPT_TEMPLATE = """你是本地基金系统的市场简报编辑。

只根据下方 module_sections 写一份中文 markdown 简报。

硬性规则:
- 不得输出买入、卖出、加仓、减仓、仓位、择时建议。
- 不得预测明日涨跌。
- 不得新增 module_sections 中没有的事实。
- 如果涉及政策、公告、宏观原因,必须来自 module_sections 的证据或摘要。
- 只返回 JSON: {"markdown": "# 简报\n\n正文", "markdown_warnings": []}
- 不得返回 modules、sections 或任何结构化事实字段。

brief_type:
$brief_type

module_order:
$module_order_json

module_sections:
$module_sections_json

warnings:
$warnings_json
"""
```

- [ ] **Step 4: Implement composer**

Create `backend/services/briefing_v2_composer.py`:

```python
"""Briefing V2 markdown composer."""
from __future__ import annotations

import json
from string import Template

from backend.config import settings as app_settings
from backend.graph.prompts import BRIEFING_V2_MARKDOWN_PROMPT_TEMPLATE
from backend.services.briefing_v2_profiles import BriefTypeProfile

settings = app_settings.get_settings()


def _parse_llm_json(raw_content: str) -> tuple[dict | None, list[str]]:
    try:
        parsed = json.loads(raw_content)
        return parsed if isinstance(parsed, dict) else None, []
    except json.JSONDecodeError:
        return None, ["llm_returned_non_json"]


def compose_briefing_v2(
    context: dict,
    profile: BriefTypeProfile,
    module_order: list[str],
    modules: dict[str, dict],
    warnings: list[str] | None = None,
) -> dict:
    prompt = Template(BRIEFING_V2_MARKDOWN_PROMPT_TEMPLATE).substitute(
        brief_type=profile.brief_type,
        module_order_json=json.dumps(module_order, ensure_ascii=False),
        module_sections_json=json.dumps({"module_sections": modules}, ensure_ascii=False, indent=2),
        warnings_json=json.dumps(warnings or [], ensure_ascii=False),
    )
    from backend.graph import model as _model_module

    model = _model_module.build_model()
    response = model.invoke(prompt)
    raw_content = response.content if hasattr(response, "content") else str(response)
    parsed, parse_warnings = _parse_llm_json(raw_content)
    if parsed is None:
        return {
            "markdown": raw_content,
            "markdown_warnings": parse_warnings,
            "llm_model": getattr(settings, "briefing_llm_model", "deepseek-chat"),
            "prompt_used_chars": len(prompt),
        }
    markdown = parsed.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        markdown = raw_content
        parse_warnings.append("llm_json_missing_markdown")
    markdown_warnings = parsed.get("markdown_warnings")
    if not isinstance(markdown_warnings, list):
        markdown_warnings = []
    return {
        "markdown": markdown,
        "markdown_warnings": [str(w) for w in markdown_warnings] + parse_warnings,
        "llm_model": getattr(settings, "briefing_llm_model", "deepseek-chat"),
        "prompt_used_chars": len(prompt),
    }
```

- [ ] **Step 5: Run composer tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_v2_composer.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/graph/prompts.py backend/services/briefing_v2_composer.py backend/tests/test_briefing_v2_composer.py
git commit -m "feat(briefing): add v2 markdown composer"
```

---

### Task 4: Integrate V2 Post-Market Briefing Generation

**Files:**
- Modify: `backend/services/briefing_service.py`
- Modify: `backend/tests/test_briefing_service.py`

**Interfaces:**
- Consumes:
  - `get_brief_type_profile`
  - `run_module_builders`
  - `compose_briefing_v2`
- Produces:
  - `collect_briefing_context(*, brief_type: str = "post_market", trade_date: str | None = None, session=None) -> dict`
  - `build_sections_json(profile, module_order, modules, warnings) -> str`
  - `run_daily_briefing(trigger="scheduled", session=None)` writes V2 `sections_json` for `post_market`.

- [ ] **Step 1: Add failing service integration tests**

Append to `backend/tests/test_briefing_service.py`:

```python
class TestBriefingV2Integration:
    def test_run_daily_briefing_writes_v2_sections_json(self, in_memory_session):
        import json
        from unittest.mock import patch

        from backend.db.models import Briefing
        from backend.services import briefing_service

        snapshot = {
            "market_snapshot": [{"name": "上证指数", "change_pct": 0.8, "market_date": "2026-07-09"}],
            "market_breadth": {"up": 1800, "down": 3100},
            "industry_sectors": [{"name": "半导体", "change_pct": 3.2}],
            "industry_flows": [{"name": "半导体", "net_flow": 12.5}],
            "concept_sectors": [],
            "concept_flows": [],
            "watchlist_changes": [
                {"fund_code": "012345", "fund_name": "示例半导体主题基金", "period_returns": {"1d": 0.01}}
            ],
            "collect_meta": {"warnings": []},
            "errors": [],
        }

        briefing_service.reset_for_tests()

        with patch.object(briefing_service, "collect_watchlist_snapshot", return_value=snapshot), \
             patch("backend.services.market_evidence_service.collect_and_run_for_brief_type", return_value={"inserted": 0}), \
             patch("backend.services.market_evidence_service.search_evidence", return_value=[]), \
             patch("backend.services.briefing_v2_composer.compose_briefing_v2", return_value={
                 "markdown": "# 简报\\n\\n正文",
                 "markdown_warnings": [],
                 "llm_model": "test",
                 "prompt_used_chars": 10,
             }):
            briefing_service.run_daily_briefing(trigger="manual", session=in_memory_session)

        row = in_memory_session.query(Briefing).one()
        sections = json.loads(row.sections_json)
        assert sections["brief_type"] == "post_market"
        assert sections["module_order"][0] == "quick_summary"
        assert "modules" in sections
        assert row.markdown.startswith("# 简报")

    def test_build_sections_json_does_not_duplicate_markdown(self):
        import json
        from backend.services import briefing_service
        from backend.services.briefing_v2_profiles import get_brief_type_profile

        profile = get_brief_type_profile("post_market")[0]
        payload = briefing_service.build_sections_json(
            profile=profile,
            module_order=["quick_summary", "data_statement"],
            modules={
                "quick_summary": {"key": "quick_summary", "status": "ready", "summary": "ok", "content": {}},
                "data_statement": {"key": "data_statement", "status": "ready", "summary": "ok", "content": {}},
            },
            warnings=["w1"],
        )

        decoded = json.loads(payload)
        assert "markdown" not in decoded
        assert decoded["module_order"] == ["quick_summary", "data_statement"]
        assert decoded["warnings"] == ["w1"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_service.py::TestBriefingV2Integration -q
```

Expected: FAIL because `build_sections_json` does not exist and `run_daily_briefing` still writes old sections.

- [ ] **Step 3: Add V2 context and sections helpers**

Modify `backend/services/briefing_service.py` imports:

```python
from backend.services.briefing_v2_profiles import get_brief_type_profile
from backend.services.briefing_v2_modules import run_module_builders
from backend.services.briefing_v2_composer import compose_briefing_v2
```

Add helper functions below `collect_watchlist_snapshot`:

```python
def collect_briefing_context(
    *,
    brief_type: str = "post_market",
    trade_date: str | None = None,
    snapshot: dict | None = None,
    evidence: list[dict] | None = None,
    session=None,
) -> dict:
    td = trade_date or _today()
    snap = snapshot if snapshot is not None else collect_watchlist_snapshot(session=session)
    return {
        "brief_type": brief_type,
        "trade_date": td,
        "as_of": _extract_as_of(snap, td),
        "snapshot": snap,
        "evidence": list(evidence or []),
        "data_sources_last_updated": _extract_source_updates(snap, evidence or []),
    }


def _extract_as_of(snapshot: dict, fallback: str) -> str:
    try:
        indices = snapshot.get("market_snapshot") or []
        if indices and indices[0].get("market_date"):
            return str(indices[0]["market_date"])
    except Exception:
        return fallback
    return fallback


def _extract_source_updates(snapshot: dict, evidence: list[dict]) -> dict:
    latest_evidence = None
    for item in evidence:
        published = item.get("published_at")
        if published and (latest_evidence is None or str(published) > latest_evidence):
            latest_evidence = str(published)
    return {
        "market_snapshot": snapshot.get("as_of") or _now(),
        "market_evidence": latest_evidence,
    }


def build_sections_json(
    *,
    profile,
    module_order: list[str],
    modules: dict[str, dict],
    warnings: list[str],
) -> str:
    payload = {
        "brief_type": profile.brief_type,
        "profile_version": "daily_briefing_v2_2026_07_09",
        "module_order": module_order,
        "modules": modules,
        "warnings": warnings,
    }
    return json.dumps(payload, ensure_ascii=False)
```

- [ ] **Step 4: Route `run_daily_briefing` through V2 helpers**

Inside `run_daily_briefing`, after `quality = compute_data_quality(snapshot, evidence_rows)`, replace the old `compose_briefing` branch with:

```python
    profile, profile_warnings = get_brief_type_profile("post_market")
    context = collect_briefing_context(
        brief_type=profile.brief_type,
        trade_date=today,
        snapshot=snapshot,
        evidence=evidence_rows,
        session=session,
    )
    module_order, modules, module_warnings = run_module_builders(context, profile, quality)

    if snapshot.get("watchlist_changes") or snapshot.get("market_snapshot"):
        try:
            compose_result = compose_briefing_v2(
                context,
                profile,
                module_order,
                modules,
                warnings=profile_warnings + module_warnings,
            )
            succeeded = 1
        except Exception as exc:
            failures.append({"stage": "llm", "message": str(exc)})
            failed += 1
            compose_result = {
                "markdown": "（简报正文生成失败，结构化模块已保留。）",
                "markdown_warnings": [str(exc)],
                "llm_model": getattr(settings, "briefing_llm_model", "deepseek-chat"),
            }
    else:
        compose_result = {
            "markdown": "（今日自选池为空，无涨跌数据。）",
            "markdown_warnings": [],
            "llm_model": getattr(settings, "briefing_llm_model", "deepseek-chat"),
        }
```

Set:

```python
    as_of = context["as_of"]
    sections_json = build_sections_json(
        profile=profile,
        module_order=module_order,
        modules=modules,
        warnings=profile_warnings + module_warnings + compose_result.get("markdown_warnings", []),
    )
```

- [ ] **Step 5: Run service integration tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_service.py::TestBriefingV2Integration -q
```

Expected: PASS.

- [ ] **Step 6: Run existing briefing tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_service.py backend/tests/test_graph_prompts.py -q
```

Expected: PASS except for any pre-existing unrelated failures; if `test_graph_prompts.py::test_briefing_prompt_does_not_use_doubled_braces_for_json` fails with `KeyError: evidence_json`, update the test to pass `evidence_json="[]"`.

- [ ] **Step 7: Commit**

```bash
git add backend/services/briefing_service.py backend/tests/test_briefing_service.py backend/tests/test_graph_prompts.py
git commit -m "feat(briefing): generate v2 post-market sections"
```

---

### Task 5: Frontend V2 Types And Module Renderer

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/app/briefing/page.tsx`
- Modify: `frontend/tests/briefing-ui.test.mjs`

**Interfaces:**
- Consumes:
  - `briefing.sections.module_order`
  - `briefing.sections.modules[moduleKey]`
- Produces:
  - Type guards:
    - `isBriefingV2Sections(value: unknown): value is BriefingV2Sections`
  - UI renders markdown fallback when `module_order` is missing.

- [ ] **Step 1: Add failing frontend tests**

Add tests to `frontend/tests/briefing-ui.test.mjs` for pure helpers exported from `frontend/app/briefing/page.tsx`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import {
  isBriefingV2Sections,
  moduleDisplayRows,
} from "../app/briefing/page.tsx";

test("isBriefingV2Sections detects module_order and modules", () => {
  assert.equal(isBriefingV2Sections({
    module_order: ["quick_summary"],
    modules: {
      quick_summary: {
        key: "quick_summary",
        title: "30 秒摘要",
        status: "ready",
        summary: "摘要",
        content: {},
        evidence_ids: [],
        missing_data: [],
        warnings: [],
        confidence: "medium",
      },
    },
  }), true);
  assert.equal(isBriefingV2Sections({ market_snapshot: [] }), false);
});

test("moduleDisplayRows follows module_order and skips missing modules", () => {
  const rows = moduleDisplayRows({
    module_order: ["quick_summary", "missing", "data_statement"],
    modules: {
      quick_summary: { key: "quick_summary", title: "30 秒摘要", status: "ready", summary: "摘要", content: {} },
      data_statement: { key: "data_statement", title: "数据质量", status: "ready", summary: "质量", content: {} },
    },
  });
  assert.deepEqual(rows.map((row) => row.key), ["quick_summary", "data_statement"]);
});
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
node --test frontend/tests/briefing-ui.test.mjs
```

Expected: FAIL because helpers are not exported.

- [ ] **Step 3: Add TypeScript types**

Modify `frontend/src/types/api.ts`:

```typescript
export type BriefingModuleStatus = "ready" | "partial" | "missing" | "failed";
export type BriefingConfidence = "high" | "medium" | "low";

export interface BriefingModuleSection {
  key: string;
  title: string;
  status: BriefingModuleStatus;
  summary: string;
  content: Record<string, unknown>;
  evidence_ids?: number[];
  missing_data?: string[];
  warnings?: string[];
  confidence?: BriefingConfidence;
}

export interface BriefingV2Sections {
  brief_type?: string;
  profile_version?: string;
  module_order: string[];
  modules: Record<string, BriefingModuleSection>;
  warnings?: string[];
}
```

Change `Briefing.sections` to:

```typescript
sections: BriefingSection | BriefingV2Sections | Record<string, unknown>;
```

- [ ] **Step 4: Add helpers and V2 module rendering**

In `frontend/app/briefing/page.tsx`, export:

```typescript
export function isBriefingV2Sections(value: unknown): value is BriefingV2Sections {
  if (!value || typeof value !== "object") return false;
  const candidate = value as { module_order?: unknown; modules?: unknown };
  return Array.isArray(candidate.module_order)
    && !!candidate.modules
    && typeof candidate.modules === "object";
}

export function moduleDisplayRows(sections: BriefingV2Sections): BriefingModuleSection[] {
  return sections.module_order
    .map((key) => sections.modules[key])
    .filter((section): section is BriefingModuleSection => !!section);
}
```

Add a `BriefingModulesView` component:

```tsx
function BriefingModulesView({ sections }: { sections: BriefingV2Sections }) {
  const rows = moduleDisplayRows(sections);
  return (
    <div className="space-y-3">
      {rows.map((section) => (
        <section key={section.key} className="rounded-xl border border-gray-100 bg-white p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-gray-950">{section.title}</h2>
              <p className="mt-1 text-sm leading-6 text-gray-700">{section.summary}</p>
            </div>
            <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
              {section.status}
            </span>
          </div>
          {section.warnings && section.warnings.length > 0 ? (
            <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
              {section.warnings.join("；")}
            </div>
          ) : null}
        </section>
      ))}
    </div>
  );
}
```

Use it in the existing card:

```tsx
{isBriefingV2Sections(briefing.sections) ? (
  <BriefingModulesView sections={briefing.sections} />
) : (
  <ReactMarkdown remarkPlugins={[remarkGfm]}>
    {briefing.markdown}
  </ReactMarkdown>
)}
```

- [ ] **Step 5: Run frontend tests**

Run:

```bash
node --test frontend/tests/briefing-ui.test.mjs
```

Expected: PASS.

- [ ] **Step 6: Run frontend build**

Run:

```bash
npm run build --prefix frontend
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/api.ts frontend/app/briefing/page.tsx frontend/tests/briefing-ui.test.mjs
git commit -m "feat(briefing): render v2 module sections"
```

---

### Task 6: Brief Type Persistence And API Filters

**Files:**
- Modify: `backend/db/models.py`
- Modify: `backend/db/init_db.py`
- Modify: `backend/db/repository.py`
- Modify: `backend/api/routes/briefing.py`
- Modify: `backend/services/briefing_service.py`
- Modify: `backend/tests/test_models.py`
- Modify: `backend/tests/test_repository.py`
- Modify: `backend/tests/test_briefing_route.py`

**Interfaces:**
- Produces:
  - `Briefing.brief_type: str`
  - `upsert_briefing(session, briefing_date: str, payload: dict, brief_type: str = "post_market") -> Briefing`
  - `GET /api/briefing/latest?type=post_market`
  - `GET /api/briefing/list?type=post_market&limit=30`
  - `POST /api/briefing/run` accepts JSON body `{"brief_type": "post_market"}` while preserving old header-only call.

- [ ] **Step 1: Add failing model/repository tests**

Add to `backend/tests/test_repository.py`:

```python
def test_upsert_briefing_allows_same_date_different_types(in_memory_session):
    from backend.db.repository import upsert_briefing
    from backend.db.models import Briefing

    payload = {
        "title": "简报",
        "markdown": "正文",
        "sections_json": "{}",
        "source": "test",
        "as_of": "2026-07-09",
    }

    upsert_briefing(in_memory_session, "2026-07-09", payload, brief_type="pre_market")
    upsert_briefing(in_memory_session, "2026-07-09", payload | {"title": "盘后"}, brief_type="post_market")
    in_memory_session.commit()

    rows = in_memory_session.query(Briefing).order_by(Briefing.brief_type).all()
    assert [row.brief_type for row in rows] == ["post_market", "pre_market"]
```

Add to `backend/tests/test_briefing_route.py`:

```python
def test_route_latest_filters_by_type(client_with_session):
    client, session_factory = client_with_session
    _insert_briefing(session_factory, briefing_date="2026-07-09", title="盘前", markdown="pre", brief_type="pre_market")
    _insert_briefing(session_factory, briefing_date="2026-07-09", title="盘后", markdown="post", brief_type="post_market")

    resp = client.get("/api/briefing/latest?type=pre_market")

    assert resp.status_code == 200
    assert resp.json()["briefing"]["title"] == "盘前"
    assert resp.json()["briefing"]["brief_type"] == "pre_market"
```

Also update `_insert_briefing` in that test file to accept `brief_type: str = "post_market"`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_repository.py::test_upsert_briefing_allows_same_date_different_types backend/tests/test_briefing_route.py::test_route_latest_filters_by_type -q
```

Expected: FAIL because `Briefing.brief_type` and route filters do not exist.

- [ ] **Step 3: Add model field and repository support**

Modify `backend/db/models.py`:

```python
__table_args__ = (UniqueConstraint("briefing_date", "brief_type", name="uq_briefing_date_type"),)
brief_type: Mapped[str] = mapped_column(String, default="post_market", index=True)
```

Modify `backend/db/repository.py`:

```python
def upsert_briefing(session, briefing_date: str, payload: dict, brief_type: str = "post_market") -> Briefing:
    row = session.scalar(
        select(Briefing).where(
            Briefing.briefing_date == briefing_date,
            Briefing.brief_type == brief_type,
        )
    )
    values = dict(payload)
    values["brief_type"] = brief_type
    if row is None:
        row = Briefing(briefing_date=briefing_date, **values)
        session.add(row)
    else:
        for key, value in values.items():
            if hasattr(row, key):
                setattr(row, key, value)
    session.flush()
    return row
```

- [ ] **Step 4: Add lightweight migration**

Modify `backend/db/init_db.py` missing-column migration to add:

```python
"briefings": {
    "brief_type": "VARCHAR DEFAULT 'post_market'",
},
```

Add a comment near the migration explaining:

```python
# Existing SQLite DBs may still have the old unique index on briefing_date.
# For local prototype data, duplicate same-date brief types require a fresh DB
# or a versioned migration that rebuilds the briefings table. Tests use a fresh
# metadata schema and validate the target model constraint.
```

- [ ] **Step 5: Add route filters and run payload**

Modify `backend/api/routes/briefing.py`:

```python
def _briefing_to_dict(row: Briefing) -> dict:
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
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
```

Update latest/list:

```python
@router.get("/latest")
def get_latest_briefing(
    brief_type: str = Query(default="post_market", alias="type"),
    session: Session = Depends(get_session),
) -> dict:
    row = session.scalar(
        select(Briefing)
        .where(Briefing.brief_type == brief_type)
        .order_by(Briefing.briefing_date.desc())
        .limit(1)
    )
    if row is None:
        return {"briefing": None}
    return {"briefing": _briefing_to_dict(row)}
```

For `POST /api/briefing/run`, add an optional body model:

```python
from pydantic import BaseModel


class BriefingRunRequest(BaseModel):
    brief_type: str = "post_market"
```

Then:

```python
def run_now(body: BriefingRunRequest | None = None, x_local_trigger: str | None = Header(default=None)) -> dict:
    if not x_local_trigger or x_local_trigger.lower() not in ("1", "true"):
        raise HTTPException(status_code=403, detail="missing X-Local-Trigger header")
    brief_type = body.brief_type if body is not None else "post_market"
    return briefing_service.start_run_async(trigger="manual", brief_type=brief_type)
```

- [ ] **Step 6: Update service async entry point**

Modify `backend/services/briefing_service.py` `run_daily_briefing` and async wrapper to accept `brief_type: str = "post_market"` and pass it to `get_brief_type_profile`, evidence ingestion, `collect_briefing_context`, and `upsert_briefing`.

Required call shape:

```python
upsert_briefing(s, briefing_date=today, payload=payload, brief_type=profile.brief_type)
```

- [ ] **Step 7: Run backend route and repository tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_repository.py backend/tests/test_briefing_route.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/db/models.py backend/db/init_db.py backend/db/repository.py backend/api/routes/briefing.py backend/services/briefing_service.py backend/tests/test_models.py backend/tests/test_repository.py backend/tests/test_briefing_route.py
git commit -m "feat(briefing): support briefing types"
```

---

### Task 7: Scheduler And QA Tool Type Awareness

**Files:**
- Modify: `backend/scheduler.py`
- Modify: `backend/tools/market_tools.py`
- Modify: `backend/tests/test_scheduler_briefing.py`
- Modify: `backend/tests/test_tools.py`

**Interfaces:**
- Consumes:
  - `briefing_service.start_run_async(trigger: str, brief_type: str = "post_market")`
  - `briefing_service.read_briefing(brief_date: str | None = None, brief_type: str = "post_market")`
- Produces:
  - Scheduler keeps post-market briefing behavior.
  - QA tool can read a specific briefing type.

- [ ] **Step 1: Add failing tests for type-aware reads**

Add to `backend/tests/test_tools.py`:

```python
def test_get_market_briefing_passes_brief_type(monkeypatch):
    from backend.tools import market_tools

    captured = {}

    def fake_read_briefing(brief_date=None, brief_type="post_market"):
        captured["brief_date"] = brief_date
        captured["brief_type"] = brief_type
        return {"title": "盘前", "markdown": "pre"}

    monkeypatch.setattr(market_tools.briefing_service, "read_briefing", fake_read_briefing)

    result = market_tools.get_market_briefing.invoke({"brief_type": "pre_market"})

    assert captured["brief_type"] == "pre_market"
    assert result["title"] == "盘前"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_tools.py::test_get_market_briefing_passes_brief_type -q
```

Expected: FAIL because the tool does not accept/pass `brief_type`.

- [ ] **Step 3: Update tool signature and service read**

Modify `backend/services/briefing_service.py`:

```python
def read_briefing(brief_date: str | None = None, brief_type: str = "post_market") -> dict | None:
    s = get_session()
    try:
        if brief_date:
            row = s.scalar(
                select(Briefing).where(
                    Briefing.briefing_date == brief_date,
                    Briefing.brief_type == brief_type,
                )
            )
        else:
            row = s.scalar(
                select(Briefing)
                .where(Briefing.brief_type == brief_type)
                .order_by(Briefing.briefing_date.desc())
            )
```

Modify `backend/tools/market_tools.py` tool schema to accept:

```python
brief_type: str = "post_market"
```

and call:

```python
briefing_service.read_briefing(brief_date=brief_date or None, brief_type=brief_type)
```

- [ ] **Step 4: Confirm scheduler still defaults post-market**

If `backend/scheduler.py` calls `briefing_service.start_run_async(trigger="scheduled")`, leave it defaulting to `post_market`. Add only an explicit comment:

```python
# Daily scheduled briefing remains post_market until pre_market scheduling is enabled.
```

- [ ] **Step 5: Run tool and scheduler tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_tools.py backend/tests/test_scheduler_briefing.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/briefing_service.py backend/tools/market_tools.py backend/scheduler.py backend/tests/test_tools.py backend/tests/test_scheduler_briefing.py
git commit -m "feat(briefing): pass briefing type through tools"
```

---

### Task 8: Frontend API Type Parameter Support

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/tests/api-client.test.mjs`

**Interfaces:**
- Produces:
  - `api.briefingLatest(type = "post_market")`
  - `api.briefingList(limit = 30, type = "post_market")`
  - `api.briefingRun(briefType = "post_market")`
  - `Briefing.brief_type?: string`

- [ ] **Step 1: Add failing API client tests**

Add to `frontend/tests/api-client.test.mjs`:

```javascript
test("briefingLatest sends type query", async () => {
  const calls = [];
  global.fetch = async (url) => {
    calls.push(String(url));
    return new Response(JSON.stringify({ briefing: null }), { status: 200 });
  };
  const { api } = await import("../src/lib/api.ts");
  await api.briefingLatest("pre_market");
  assert.match(calls[0], /\/api\/briefing\/latest\?type=pre_market/);
});

test("briefingRun sends brief_type body", async () => {
  const calls = [];
  global.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ status: "running" }), { status: 202 });
  };
  const { api } = await import("../src/lib/api.ts");
  await api.briefingRun("pre_market");
  assert.equal(JSON.parse(calls[0].init.body).brief_type, "pre_market");
});
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
node --test frontend/tests/api-client.test.mjs
```

Expected: FAIL because APIs do not accept type parameters.

- [ ] **Step 3: Update frontend API client**

Modify `frontend/src/lib/api.ts`:

```typescript
briefingLatest: (type = "post_market") => get<BriefingLatestResponse>("/api/briefing/latest", { type }),
briefingList: (limit = 30, type = "post_market") => get<BriefingListResponse>("/api/briefing/list", { limit, type }),
briefingRun: (briefType = "post_market") =>
  fetch(BASE + "/api/briefing/run", {
    method: "POST",
    headers: { "X-Local-Trigger": "1", "Content-Type": "application/json" },
    body: JSON.stringify({ brief_type: briefType }),
  }).then(async (r) => {
    if (!r.ok) throw new Error(`/api/briefing/run -> ${r.status}`);
    return (await r.json()) as BriefingRunResponse;
  }),
```

Modify `frontend/src/types/api.ts`:

```typescript
brief_type?: string;
```

inside `Briefing` and `BriefingSummary`.

- [ ] **Step 4: Run API client tests**

Run:

```bash
node --test frontend/tests/api-client.test.mjs
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/types/api.ts frontend/tests/api-client.test.mjs
git commit -m "feat(briefing): support briefing type in frontend api"
```

---

### Task 9: Final Regression And Documentation Review

**Files:**
- Modify only if failures reveal issues:
  - `docs/superpowers/specs/2026-07-09-daily-briefing-v2-design.md`
  - `docs/superpowers/plans/2026-07-09-daily-briefing-v2.md`

**Interfaces:**
- Consumes all previous tasks.
- Produces verified implementation state.

- [ ] **Step 1: Run backend briefing-focused tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_briefing_service.py backend/tests/test_briefing_route.py backend/tests/test_briefing_v2_profiles.py backend/tests/test_briefing_v2_modules.py backend/tests/test_briefing_v2_composer.py backend/tests/test_repository.py backend/tests/test_tools.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: PASS. If `backend/tests/test_settings.py::test_settings_defaults` still fails because `deepseek_model` expected `deepseek-chat` but current default is `deepseek-v4-flash`, either align the default/config test in a separate commit or record it as a pre-existing failure before merging.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
node --test frontend/tests/*.test.mjs
```

Expected: PASS.

- [ ] **Step 4: Run frontend build**

Run:

```bash
npm run build --prefix frontend
```

Expected: PASS.

- [ ] **Step 5: Review requirements checklist**

Confirm:

```text
profile selects modules by brief_type
module builders produce content envelope
quick_summary and data_statement are always present
LLM cannot overwrite modules
sections_json does not duplicate markdown
old markdown fallback still works
brief_type defaults to post_market
pre_market and post_market can coexist after migration
```

- [ ] **Step 6: Commit final fixes**

```bash
git add backend frontend docs/superpowers/plans/2026-07-09-daily-briefing-v2.md
git commit -m "test(briefing): verify v2 briefing flow"
```

---

## Self-Review

**Spec coverage:** This plan covers profile/module architecture, unified module envelope, `theme_context`, markdown-only LLM composer, V2 `sections_json`, frontend `module_order` rendering, `brief_type` persistence/API filters, migration tests, and final regression checks. Phase 5 user feedback is intentionally not implemented because the spec says Phase 1-4 do not implement feedback and Phase 5 is a later optimization.

**Completeness scan:** This plan avoids unresolved marker tokens and empty edge-case instructions. Code snippets define exact function names and expected payload shapes.

**Type consistency:** V2 structured data consistently uses `module_order`, `modules`, module envelope fields, and module-specific `content`. `Briefing.markdown` remains the markdown source of truth.
