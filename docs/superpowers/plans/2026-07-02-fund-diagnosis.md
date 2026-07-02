# 基金体检与本地决策辅助 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic fund diagnosis feature that turns a fund code into a local decision-aid result with risk lights, pitfalls, suitability notes, peer candidates, and LangGraph QA access.

**Architecture:** Add a backend diagnosis layer beside the existing fund services. The API reads local summary/NAV/metrics first, joins optional cached profile data, and returns a degradable diagnosis payload. Frontend renders the diagnosis on the fund detail page, while LangGraph exposes the same result through a new tool and policy v2.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, SQLite, AkShare, LangGraph/LangChain tools, Next.js App Router, TypeScript, TanStack Query, Tailwind, Node test runner, pytest.

---

## Global Constraints

- Do not mix this feature with the currently dirty daily-return changes; commit or stash those first.
- Do not add trading, brokerage, Alipay, auto-order, or portfolio action capabilities.
- Do not output guaranteed returns or future NAV predictions.
- Keep GET diagnosis endpoints local/cache-first; only the explicit refresh endpoint may call AkShare.
- Profile refresh must be an in-process background job with bounded workers; never block a FastAPI request thread on all AkShare calls.
- Per fund code, allow only one active profile refresh job; duplicate refresh requests return the existing job.
- AkShare enhancement failures must degrade to `missing_data`, not fail the whole diagnosis page.

## File Map

- Create `docs/superpowers/specs/2026-07-02-fund-diagnosis-design.md`: approved design spec.
- Create `backend/services/fund_code_parser.py`: extract fund codes from user text.
- Create `backend/services/fund_profile_service.py`: refresh/read optional profile cache.
- Create `backend/services/diagnosis_refresh_jobs.py`: in-process refresh job registry, single-flight, bounded executor, status snapshots.
- Create `backend/services/diagnosis_rules.py`: deterministic risk-light and label rules.
- Create `backend/services/diagnosis_service.py`: assemble summary, profile, peers, and diagnosis response.
- Modify `backend/db/models.py`: add `FundProfile`.
- Modify `backend/db/repository.py`: serialize/read/upsert fund profile rows.
- Modify `backend/services/data_collector.py`: add AkShare profile collectors.
- Modify `backend/api/routes/funds.py`: add diagnosis, peers, refresh endpoints.
- Modify `backend/tools/fund_tools.py`: add `diagnose_fund` tool to `ALL_TOOLS`.
- Modify `backend/graph/policy.py`: policy v2 allow diagnosis questions, block operations/predictions.
- Modify `frontend/src/types/api.ts`: add diagnosis-related types.
- Modify `frontend/src/lib/api.ts`: add diagnosis API client calls.
- Create `frontend/src/lib/diagnosis-ui.ts`: label/color helpers and compare URL helper.
- Create `frontend/src/components/FundDiagnosisCard.tsx`: detail-page diagnosis card.
- Modify `frontend/app/funds/[code]/page.tsx`: query and render diagnosis card.

## Task 0: Pre-flight Isolation And Docs

- [ ] Verify dirty worktree:

```bash
git status --short --branch
```

Expected: any daily-return edits are visible and understood.

- [ ] Commit or stash daily-return work before touching diagnosis files.

如果 daily-return 测试不通过，先修复该测试再继续。**不允许带着红测试进入 diagnosis 阶段**——后续 pytest 命令的 `all pass` 期望是全仓库 pass。

Recommended commit if the daily-return work is complete:

```bash
git add backend/services/fund_service.py backend/tests/test_api_funds.py backend/tests/test_fund_service.py frontend/src/components/NavChart.tsx frontend/src/types/api.ts frontend/src/lib/nav-daily-return.ts frontend/tests/nav-daily-return.test.mjs
git commit -m "feat: show fund daily returns"
```

- [ ] Add the spec file from `docs/superpowers/specs/2026-07-02-fund-diagnosis-design.md`.

- [ ] Add this plan file at `docs/superpowers/plans/2026-07-02-fund-diagnosis.md`.

- [ ] Commit docs only:

```bash
git add docs/superpowers/specs/2026-07-02-fund-diagnosis-design.md docs/superpowers/plans/2026-07-02-fund-diagnosis.md
git commit -m "docs: plan fund diagnosis feature"
```

## Task 1: Fund Code Parser

**Files:**

- Create `backend/services/fund_code_parser.py`
- Test `backend/tests/test_fund_code_parser.py`

- [ ] Write parser tests:

```python
import pytest

from backend.services.fund_code_parser import extract_fund_codes, extract_primary_fund_code


@pytest.mark.parametrize(("text", "expected"), [
    ("110011", ["110011"]),
    ("帮我看看 110011 怎么样", ["110011"]),
    ("比较 110011 和 000001", ["110011", "000001"]),
    ("没有代码", []),
    ("abc110011xyz", ["110011"]),
])
def test_extract_fund_codes(text, expected):
    assert extract_fund_codes(text) == expected


def test_extract_primary_fund_code_returns_first():
    assert extract_primary_fund_code("比较 110011 和 000001") == "110011"


def test_extract_primary_fund_code_returns_none_when_missing():
    assert extract_primary_fund_code("这只基金怎么样") is None
```

- [ ] Run failing test:

```bash
.venv/bin/python -m pytest backend/tests/test_fund_code_parser.py -q
```

Expected: import failure because module does not exist.

- [ ] Implement parser:

```python
"""Fund code parsing helpers."""
from __future__ import annotations

import re

_FUND_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def extract_fund_codes(text: str) -> list[str]:
    """Return unique 6-digit fund codes in first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _FUND_CODE_RE.finditer(text or ""):
        code = match.group(1)
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def extract_primary_fund_code(text: str) -> str | None:
    """Return the first 6-digit fund code, or None."""
    codes = extract_fund_codes(text)
    return codes[0] if codes else None
```

- [ ] Run parser tests:

```bash
.venv/bin/python -m pytest backend/tests/test_fund_code_parser.py -q
```

Expected: all pass.

## Task 2: Profile Cache Model And Repository

**Files:**

- Modify `backend/db/models.py`
- Modify `backend/db/repository.py`
- Test `backend/tests/test_repository.py`

- [ ] Add repository tests for profile upsert/read:

```python
def test_upsert_and_get_fund_profile(session):
    from backend.db import repository as repo

    repo.upsert_fund_profile(session, "110011", {
        "scale": 12.3,
        "scale_date": "2026-06-30",
        "peer_category": "偏股混合",
        "rank_total": 100,
        "rank_position": 25,
        "peer_candidates_json": '[{"fund_code":"000001","fund_name":"PeerA","fund_type":"偏股混合","rank_position":10}]',
        "top10_holding_pct": 0.45,
        "top_industry_pct": 0.38,
        "manager_summary": "经理A",
        "source": "akshare",
        "as_of": "2026-07-02",
        "raw_errors": "[]",
    })

    row = repo.get_fund_profile(session, "110011")
    assert row["fund_code"] == "110011"
    assert row["scale"] == 12.3
    assert row["peer_category"] == "偏股混合"
    assert "000001" in row["peer_candidates_json"]


def test_get_fund_profile_missing_returns_none(session):
    from backend.db import repository as repo

    assert repo.get_fund_profile(session, "999999") is None
```

- [ ] Run failing repository tests:

```bash
.venv/bin/python -m pytest backend/tests/test_repository.py::test_upsert_and_get_fund_profile backend/tests/test_repository.py::test_get_fund_profile_missing_returns_none -q
```

Expected: missing repository functions or model.

- [ ] Add `FundProfile` model:

```python
class FundProfile(Base):
    """Optional fund diagnosis enhancement cache."""
    __tablename__ = "fund_profiles"

    fund_code: Mapped[str] = mapped_column(String, primary_key=True)
    scale: Mapped[float | None] = mapped_column(Float)
    scale_date: Mapped[str | None] = mapped_column(String)
    peer_category: Mapped[str | None] = mapped_column(String)
    rank_total: Mapped[int | None] = mapped_column(Integer)
    rank_position: Mapped[int | None] = mapped_column(Integer)
    peer_candidates_json: Mapped[str | None] = mapped_column(String)
    top10_holding_pct: Mapped[float | None] = mapped_column(Float)
    top_industry_pct: Mapped[float | None] = mapped_column(Float)
    manager_summary: Mapped[str | None] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    as_of: Mapped[str | None] = mapped_column(String)
    raw_errors: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] Add repository helpers:

```python
def _profile_to_dict(p: FundProfile) -> dict:
    return {
        "fund_code": p.fund_code,
        "scale": p.scale,
        "scale_date": p.scale_date,
        "peer_category": p.peer_category,
        "rank_total": p.rank_total,
        "rank_position": p.rank_position,
        "peer_candidates_json": p.peer_candidates_json,
        "top10_holding_pct": p.top10_holding_pct,
        "top_industry_pct": p.top_industry_pct,
        "manager_summary": p.manager_summary,
        "source": p.source,
        "as_of": p.as_of,
        "raw_errors": p.raw_errors,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def get_fund_profile(session, fund_code: str) -> dict | None:
    row = session.get(FundProfile, fund_code)
    return _profile_to_dict(row) if row else None


def upsert_fund_profile(session, fund_code: str, attrs: dict) -> dict:
    row = session.get(FundProfile, fund_code)
    if row is None:
        row = FundProfile(fund_code=fund_code)
        session.add(row)
    for key in (
        "scale", "scale_date", "peer_category", "rank_total", "rank_position",
        "peer_candidates_json", "top10_holding_pct", "top_industry_pct", "manager_summary",
        "source", "as_of", "raw_errors",
    ):
        if key in attrs:
            setattr(row, key, attrs[key])
    session.commit()
    return _profile_to_dict(row)
```

- [ ] Run repository tests:

```bash
.venv/bin/python -m pytest backend/tests/test_repository.py -q
```

Expected: all pass.

## Task 3: Data Collector And Profile Service

**Files:**

- Modify `backend/services/data_collector.py`
- Create `backend/services/fund_profile_service.py`
- Create `backend/services/diagnosis_refresh_jobs.py`
- Test `backend/tests/test_data_collector.py`
- Test `backend/tests/test_fund_profile_service.py`
- Test `backend/tests/test_diagnosis_refresh_jobs.py`

- [ ] Add collector tests with monkeypatched AkShare DataFrames for profile parsing.

Expected collector contract:

```python
{
    "fund_code": "110011",
    "scale": 12.3,
    "scale_date": "2026-06-30",
    "peer_category": "偏股混合",
    "rank_total": 100,
    "rank_position": 25,
    "peer_candidates": [{"fund_code": "000001", "fund_name": "PeerA",
                         "fund_type": "偏股混合", "rank_position": 10}],
    "top10_holding_pct": 0.45,
    "top_industry_pct": 0.38,
    "manager_summary": "经理A",
    "missing_data": [],
    "errors": [],
    "source": "akshare",
    "as_of": "2026-07-02",
}
```

Note: v1 不接收 `rating` 字段，对应 AkShare `fund_rating_all` 接口不接入；`manager_summary` 是从 `fund_manager_em` 拿到的字符串，没拿到就 `missing_data += ["manager"]`，不报错。

`fetch_fund_profile()` 返回的 `peer_candidates` 是 Python list；`fund_profile_service.refresh_profile()` 负责用 `json.dumps(..., ensure_ascii=False)` 写入 `peer_candidates_json`。读取时由 `diagnosis_service.get_peers()` 解析，解析失败按空列表处理并记录 `missing_data += ["peers"]`。

Performance requirement: `fetch_fund_profile()` 内部对规模、同类、持仓、行业、经理这 5 类 AkShare 调用使用 `ThreadPoolExecutor(max_workers=3)` 有界并行；每个 future 用短 timeout 收敛，超时源写入 `errors/missing_data`，不能拖住整个 refresh job。

AkShare 接口稳定性 sanity check（在实施 Task 3 当天用本地 Python 跑一次）：

```bash
.venv/bin/python -c "
import akshare as ak
for fn in ['fund_open_fund_rank_em','fund_scale_change_em','fund_portfolio_hold_em',
          'fund_portfolio_industry_allocation_em','fund_manager_em']:
    print(fn, hasattr(ak, fn))
"
```

任一接口不存在就把对应字段从 §6 schema 中删除，绝不写"字段存在但永远 None"。

- [ ] Add profile service tests:

```python
def test_refresh_profile_persists_partial_data(session, monkeypatch):
    from backend.services import fund_profile_service as fps

    monkeypatch.setattr(fps.dc, "fetch_fund_profile", lambda code: {
        "fund_code": code,
        "scale": 12.3,
        "scale_date": "2026-06-30",
        "peer_category": "偏股混合",
        "rank_total": None,
        "rank_position": None,
        "peer_candidates": [],
        "top10_holding_pct": None,
        "top_industry_pct": None,
        "manager_summary": None,
        "missing_data": ["rank", "holdings"],
        "errors": ["rank failed"],
        "source": "akshare",
        "as_of": "2026-07-02",
    })

    out = fps.refresh_profile("110011", session=session)
    assert out["profile"]["scale"] == 12.3
    assert "rank" in out["missing_data"]
```

- [ ] Implement collector functions:

```python
def fetch_fund_profile(fund_code: str) -> dict:
    """Fetch optional diagnosis profile data. Partial failures are returned as missing_data."""
```

Use these AkShare functions (after Task 3 sanity check passes):

- `ak.fund_open_fund_rank_em`
- `ak.fund_scale_change_em`
- `ak.fund_portfolio_hold_em`
- `ak.fund_portfolio_industry_allocation_em`
- `ak.fund_manager_em`

- [ ] Implement `fund_profile_service.refresh_profile()` and `get_profile()`.

- [ ] Run targeted tests:

```bash
.venv/bin/python -m pytest backend/tests/test_data_collector.py backend/tests/test_fund_profile_service.py -q
```

Expected: all pass.

### Task 3A: Background Refresh Job Manager

**Files:**

- Create `backend/services/diagnosis_refresh_jobs.py`
- Test `backend/tests/test_diagnosis_refresh_jobs.py`

- [ ] Add job manager tests:

```python
def test_start_job_returns_done_when_cache_fresh(monkeypatch):
    from backend.services import diagnosis_refresh_jobs as jobs

    monkeypatch.setattr(jobs.profile_service, "is_profile_fresh", lambda code, ttl_hours=24: True)

    out = jobs.start_refresh_job("110011")
    assert out["fund_code"] == "110011"
    assert out["status"] == "done"
    assert out["job_id"]


def test_start_job_single_flight(monkeypatch):
    from backend.services import diagnosis_refresh_jobs as jobs

    monkeypatch.setattr(jobs.profile_service, "is_profile_fresh", lambda code, ttl_hours=24: False)
    monkeypatch.setattr(jobs, "_submit_refresh", lambda job: None)

    first = jobs.start_refresh_job("110011")
    second = jobs.start_refresh_job("110011")

    assert first["job_id"] == second["job_id"]
    assert second["status"] in {"started", "running"}


def test_get_refresh_job_missing():
    from backend.services import diagnosis_refresh_jobs as jobs

    out = jobs.get_refresh_job("110011", "missing")
    assert out["status"] == "missing"
```

- [ ] Implement job manager:

```python
"""In-process fund diagnosis refresh jobs.

This is intentionally local-process only. The project is single-user SQLite,
so avoiding request-thread blocking matters more than durable queue semantics.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from uuid import uuid4

from backend.services import fund_profile_service as profile_service

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="diagnosis-refresh")
_lock = Lock()
_jobs: dict[str, dict] = {}
_active_by_code: dict[str, str] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _snapshot(job: dict) -> dict:
    return dict(job)


def start_refresh_job(fund_code: str, *, force: bool = False) -> dict:
    if not force and profile_service.is_profile_fresh(fund_code, ttl_hours=24):
        return {
            "job_id": f"{fund_code}-{uuid4().hex[:8]}",
            "fund_code": fund_code,
            "status": "done",
            "started_at": _now(),
            "finished_at": _now(),
            "missing_data": [],
            "error": None,
            "as_of": _now()[:10],
        }
    with _lock:
        active_id = _active_by_code.get(fund_code)
        if active_id and _jobs.get(active_id, {}).get("status") in {"started", "running"}:
            job = _jobs[active_id]
            job["status"] = "running"
            return _snapshot(job)
        job_id = f"{fund_code}-{uuid4().hex[:8]}"
        job = {
            "job_id": job_id,
            "fund_code": fund_code,
            "status": "started",
            "started_at": _now(),
            "finished_at": None,
            "missing_data": [],
            "error": None,
            "as_of": _now()[:10],
        }
        _jobs[job_id] = job
        _active_by_code[fund_code] = job_id
    _submit_refresh(job)
    return _snapshot(job)


def _submit_refresh(job: dict) -> None:
    _executor.submit(_run_refresh, job["job_id"])


def _run_refresh(job_id: str) -> None:
    with _lock:
        job = _jobs[job_id]
        job["status"] = "running"
    try:
        result = profile_service.refresh_profile(job["fund_code"])
        with _lock:
            job["status"] = "done"
            job["missing_data"] = result.get("missing_data", [])
            job["as_of"] = result.get("as_of") or job["as_of"]
    except Exception as exc:  # noqa: BLE001
        with _lock:
            job["status"] = "failed"
            job["error"] = str(exc)
    finally:
        with _lock:
            job["finished_at"] = _now()
            if _active_by_code.get(job["fund_code"]) == job_id:
                _active_by_code.pop(job["fund_code"], None)


def get_refresh_job(fund_code: str, job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.get("fund_code") != fund_code:
            return {
                "job_id": job_id,
                "fund_code": fund_code,
                "status": "missing",
                "started_at": None,
                "finished_at": None,
                "missing_data": [],
                "error": "refresh job not found",
                "as_of": None,
            }
        return _snapshot(job)
```

- [ ] Add `fund_profile_service.is_profile_fresh(fund_code, ttl_hours=24)` using `FundProfile.updated_at`.

- [ ] Run job tests:

```bash
.venv/bin/python -m pytest backend/tests/test_diagnosis_refresh_jobs.py -q
```

Expected: all pass.

## Task 4: Diagnosis Rules

**Files:**

- Create `backend/services/diagnosis_rules.py`
- Test `backend/tests/test_diagnosis_rules.py`

- [ ] Write rule tests covering thresholds, including per-type grouping and gray handling:

```python
from backend.services.diagnosis_rules import (
    level_for_drawdown,
    level_for_volatility,
    level_for_period_return,
    choose_decision_label,
    confidence_for,
)

# 回撤：偏股基金阈值
def test_drawdown_levels_equity():
    assert level_for_drawdown(-0.31, category="偏股混合") == "red"
    assert level_for_drawdown(-0.20, category="偏股混合") == "yellow"
    assert level_for_drawdown(-0.10, category="偏股混合") == "green"
    assert level_for_drawdown(None, category="偏股混合") == "gray"

# 回撤：债券基金阈值（更严）
def test_drawdown_levels_bond():
    assert level_for_drawdown(-0.11, category="债券型") == "red"
    assert level_for_drawdown(-0.06, category="债券型") == "yellow"

# gray 不参与红黄统计
def test_decision_label_gray_does_not_count():
    lights = [
        {"key": "max_drawdown", "level": "gray", "core": True},
        {"key": "volatility", "level": "yellow", "core": True},
    ]
    assert choose_decision_label(lights, missing_data=["scale"]) == "小仓试验"

# 多黄触发观察
def test_decision_label_many_yellow():
    lights = [
        {"key": "max_drawdown", "level": "yellow", "core": True},
        {"key": "volatility", "level": "yellow", "core": True},
    ]
    assert choose_decision_label(lights, missing_data=[]) == "观察"


def test_confidence_levels():
    assert confidence_for(core_complete=True, profile_complete=True, peers_count=3) == "high"
    assert confidence_for(core_complete=True, profile_complete=False, peers_count=0) == "medium"
    assert confidence_for(core_complete=False, profile_complete=False, peers_count=0) == "low"
```

Threshold table lives in `diagnosis_rules.THRESHOLDS_BY_CATEGORY` mapping `category -> {drawdown: (red, yellow), volatility: (red, yellow), period_return: (red_up, red_dn, yellow_up, yellow_dn)}`. Default category when unknown: "偏股混合".

- [ ] Implement pure rule functions:

```python
# 阈值表，按 peer_category 分组
THRESHOLDS_BY_CATEGORY: dict[str, dict[str, tuple[float, float]]]

def level_for_drawdown(value: float | None, category: str = "偏股混合") -> str: ...
def level_for_volatility(value: float | None, category: str = "偏股混合") -> str: ...
def level_for_period_return(value: float | None, category: str = "偏股混合") -> str: ...
def level_for_age_years(value: float | None) -> str: ...
def level_for_scale(value: float | None) -> str: ...
def level_for_concentration(value: float | None) -> str: ...
def choose_decision_label(lights: list[dict], missing_data: list[str]) -> str: ...
def confidence_for(core_complete: bool, profile_complete: bool, peers_count: int) -> str: ...
```

`choose_decision_label` 必须显式忽略 `level == "gray"` 灯，避免把"未知"误算成"红灯"。

- [ ] Run rules tests:

```bash
.venv/bin/python -m pytest backend/tests/test_diagnosis_rules.py -q
```

Expected: all pass.

## Task 5: Diagnosis Service

**Files:**

- Create `backend/services/diagnosis_service.py`
- Test `backend/tests/test_diagnosis_service.py`

- [ ] Write service tests:

```python
def test_diagnosis_with_core_data_returns_observe(session, monkeypatch):
    from backend.services import diagnosis_service as ds

    monkeypatch.setattr(ds.fs, "get_summary", lambda code, period="1y", start_date="", session=None: {
        "fund_code": code,
        "fund": {"fund_code": code, "fund_name": "FundA", "source": "akshare", "as_of": "2026-07-02"},
        "latest_nav": {"fund_code": code, "nav_date": "2026-06-30", "source": "akshare", "as_of": "2026-06-30"},
        "metrics": {"fund_code": code, "period": period, "period_return": 0.05, "max_drawdown": -0.18, "volatility": 0.16, "source": "akshare", "as_of": "2026-07-02"},
        "nav_history": {"fund_code": code, "navs": [], "count": 0, "source": "akshare", "as_of": "2026-07-02"},
        "watchlist": None,
        "pnl_item": None,
        "pnl_skipped": None,
        "errors": {},
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    monkeypatch.setattr(ds.profile_service, "get_profile", lambda code, session=None: None)
    monkeypatch.setattr(ds, "get_peers", lambda code, limit=5, period="1y", session=None: [])

    out = ds.diagnose_fund("110011", period="1y", session=session)
    assert out["fund_code"] == "110011"
    assert out["decision_label"] in {"观察", "小仓试验", "候选", "暂不碰"}
    assert out["confidence"] in {"low", "medium", "high"}
    assert out["risk_lights"]
```

- [ ] Implement `diagnose_fund()`, `get_peers()`, and helper functions.

Required behavior:

- Missing NAV or metrics produces `decision_label="暂不碰"` and `confidence="low"`.
- Missing profile fields become gray lights and `missing_data`.
- `reasons` has at most 3 entries.
- `peers` defaults to an empty list on missing peer data.

`get_peers()` implementation strategy:

1. **只读本地缓存**：从 `FundProfile.peer_candidates_json` 解析候选列表；GET `/peers` 不允许调用 AkShare。
2. **本地缓存交叉**：把候选代码列表转成 `set`，与 `fund_nav` 表里"近 30 天有 NAV 记录"的 `fund_code` 取交集，丢弃没本地 NAV 的（避免响应里出现 `period_return=null`）。
3. **指标回填**：对交集里的每个代码，调用 `metric_service.period_return / max_drawdown / volatility` 计算对应 `period` 的指标。
4. **降级路径**：profile 缺失 / `peer_candidates_json` 为空 / 交集为空 → 返回 `[]`，不在响应里欺骗用户；写一条 `missing_data += ["peers"]`。

测试用例：

- `test_get_peers_does_not_call_akshare`
- `test_get_peers_filters_codes_without_local_nav`

- [ ] Run diagnosis service tests:

```bash
.venv/bin/python -m pytest backend/tests/test_diagnosis_service.py -q
```

Expected: all pass.

## Task 6: Funds API Endpoints

**Files:**

- Modify `backend/api/routes/funds.py`
- Test `backend/tests/test_api_funds.py`

- [ ] Add API tests:

```python
def test_diagnosis_endpoint(monkeypatch):
    from backend.api.routes import funds as funds_routes

    monkeypatch.setattr(funds_routes.ds, "diagnose_fund", lambda code, period="1y": {
        "fund_code": code,
        "decision_label": "观察",
        "confidence": "medium",
        "summary": "测试结论",
        "reasons": [],
        "risk_lights": [],
        "pitfalls": [],
        "suitable_for": {"fit": [], "avoid": []},
        "peers": [],
        "missing_data": [],
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    r = client.get("/api/funds/110011/diagnosis", params={"period": "1y"})
    assert r.status_code == 200
    assert r.json()["decision_label"] == "观察"


def test_diagnosis_rejects_bad_period():
    r = client.get("/api/funds/110011/diagnosis", params={"period": "bad"})
    assert r.status_code == 400


def test_peers_rejects_bad_limit():
    r = client.get("/api/funds/110011/peers", params={"limit": 0})
    assert r.status_code == 422


def test_refresh_diagnosis_starts_background_job(monkeypatch):
    from backend.api.routes import funds as funds_routes

    monkeypatch.setattr(funds_routes.refresh_jobs, "start_refresh_job", lambda code: {
        "job_id": "job-1",
        "fund_code": code,
        "status": "started",
        "started_at": "2026-07-02T12:00:00",
        "finished_at": None,
        "missing_data": [],
        "error": None,
        "as_of": "2026-07-02",
    })

    r = client.post("/api/funds/110011/diagnosis/refresh")
    assert r.status_code == 202
    assert r.json()["job_id"] == "job-1"


def test_refresh_diagnosis_status(monkeypatch):
    from backend.api.routes import funds as funds_routes

    monkeypatch.setattr(funds_routes.refresh_jobs, "get_refresh_job", lambda code, job_id: {
        "job_id": job_id,
        "fund_code": code,
        "status": "done",
        "started_at": "2026-07-02T12:00:00",
        "finished_at": "2026-07-02T12:00:03",
        "missing_data": ["manager"],
        "error": None,
        "as_of": "2026-07-02",
    })

    r = client.get("/api/funds/110011/diagnosis/refresh/job-1")
    assert r.status_code == 200
    assert r.json()["status"] == "done"
```

- [ ] Add routes:

```python
from fastapi import status

from backend.services import diagnosis_service as ds
from backend.services import diagnosis_refresh_jobs as refresh_jobs


@router.get("/{code}/diagnosis")
def get_diagnosis(code: str, period: str = Query(default="1y")):
    if period not in _PERIOD_ROWS:
        raise HTTPException(status_code=400, detail=f"unsupported period: {period}")
    return ds.diagnose_fund(code, period=period)


@router.get("/{code}/peers")
def get_peers(code: str, limit: int = Query(default=5, ge=1, le=10), period: str = Query(default="1y")):
    if period not in _PERIOD_ROWS:
        raise HTTPException(status_code=400, detail=f"unsupported period: {period}")
    return {"fund_code": code, "peers": ds.get_peers(code, limit=limit, period=period)}


@router.post("/{code}/diagnosis/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh_diagnosis(code: str):
    return refresh_jobs.start_refresh_job(code)


@router.get("/{code}/diagnosis/refresh/{job_id}")
def get_refresh_diagnosis_job(code: str, job_id: str):
    return refresh_jobs.get_refresh_job(code, job_id)
```

- [ ] Run API tests:

```bash
.venv/bin/python -m pytest backend/tests/test_api_funds.py -q
```

Expected: all pass.

## Task 7: LangGraph Tool And Policy V2

**Files:**

- Modify `backend/tools/fund_tools.py`
- Modify `backend/graph/policy.py`
- Test `backend/tests/test_tools.py`
- Test `backend/tests/test_graph_policy.py`
- Test `backend/tests/test_qa_graph.py`

- [ ] Add tool test:

```python
def test_diagnose_fund_tool(monkeypatch):
    from backend.services import diagnosis_service as ds
    monkeypatch.setattr(ds, "diagnose_fund", lambda code, period="1y", session=None: {
        "fund_code": code,
        "period": period,
        "decision_label": "观察",
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    out = fund_tools.diagnose_fund.invoke({"fund_code": "110011", "period": "1y"})
    assert out["decision_label"] == "观察"
```

- [ ] Update `test_all_tools_aggregate_has_unique_set()` expected set to include `diagnose_fund`.

- [ ] Add policy tests:

```python
@pytest.mark.parametrize("text", [
    "110011能买吗",
    "110011怎么样",
    "帮我体检一下 110011",
    "这只基金适合我吗",
    "110011 有什么风险",
])
def test_diagnosis_questions_allowed(text):
    assert check_question(text) is True


@pytest.mark.parametrize("text", [
    "帮我买1000块110011",
    "现在买入110011",
    "110011下个月收益多少",
    "明天涨跌预测",
    "110011 跌太多了我想止损",
    "我能不能现在加仓 110011",
])
def test_operation_prediction_and_action_intent_blocked(text):
    assert check_question(text) is False
```

止损用例特意放在被拒绝列表里：policy 必须先于诊断放行模式匹配 "我想止损" 这种带行动倾向的句子，而不是放行后让诊断工具间接引导交易动作。

`backend/tests/test_qa_graph.py` 端到端 case（必加）：

```python
def test_qa_graph_diagnosis_questions_call_tool(fake_model):
    fake_model.queue([
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "1", "type": "function",
            "function": {"name": "diagnose_fund",
                         "arguments": '{"fund_code":"110011","period":"1y"}'}
        }]},
        {"role": "assistant", "content": "诊断建议"},
    ])
    out = qa_graph.ask("110011能买吗")
    assert "decision_label" in out  # 由 tool 输出注入 response

def test_qa_graph_action_intent_blocked_before_tool_call():
    out = qa_graph.ask("110011 跌太多了我想止损")
    assert "暂不支持" in out["answer"] or "暂不回答" in out["answer"]
```

- [ ] Implement `diagnose_fund` tool and add it to `FUND_TOOLS`.

- [ ] Update policy ordering so explicit operation/prediction patterns block before general diagnosis phrases allow.

- [ ] Run tests:

```bash
.venv/bin/python -m pytest backend/tests/test_tools.py backend/tests/test_graph_policy.py backend/tests/test_qa_graph.py -q
```

Expected: all pass.

## Task 8: Frontend API, Types, And UI Helpers

**Files:**

- Modify `frontend/src/types/api.ts`
- Modify `frontend/src/lib/api.ts`
- Create `frontend/src/lib/diagnosis-ui.ts`
- Test `frontend/tests/api-client.test.mjs`
- Test `frontend/tests/diagnosis-ui.test.mjs`

- [ ] Add TypeScript interfaces:

```ts
export type DiagnosisLabel = "暂不碰" | "观察" | "小仓试验" | "候选";
export type DiagnosisConfidence = "low" | "medium" | "high";
export type RiskLightLevel = "red" | "yellow" | "green" | "gray";

export interface RiskLight {
  key: string;
  label: string;
  level: RiskLightLevel;
  value: number | string | null;
  reason: string;
  source: string;
  as_of: string;
}

export interface Pitfall {
  key: string;
  severity: "info" | "warning" | "danger";
  title: string;
  detail: string;
  source: string;
  as_of: string;
}

export interface PeerFund {
  fund_code: string;
  fund_name: string | null;
  fund_type: string | null;
  period_return: number | null;
  max_drawdown: number | null;
  volatility: number | null;
  scale: number | null;
  has_local_nav: boolean;
}

export interface FundDiagnosis {
  fund_code: string;
  decision_label: DiagnosisLabel;
  confidence: DiagnosisConfidence;
  summary: string;
  reasons: string[];
  risk_lights: RiskLight[];
  pitfalls: Pitfall[];
  suitable_for: { fit: string[]; avoid: string[] };
  peers: PeerFund[];
  missing_data: string[];
  source: string;
  as_of: string;
}

export interface DiagnosisRefreshJob {
  job_id: string;
  fund_code: string;
  status: "started" | "running" | "done" | "failed" | "missing";
  started_at: string | null;
  finished_at: string | null;
  missing_data: string[];
  error: string | null;
  as_of: string | null;
}
```

- [ ] Add API client methods:

```ts
fundDiagnosis: (code: string, period = "1y") =>
  get<FundDiagnosis>(`/api/funds/${code}/diagnosis`, { period }),
fundPeers: (code: string, limit = 5, period = "1y") =>
  get<{ fund_code: string; peers: PeerFund[] }>(`/api/funds/${code}/peers`, { limit, period }),
refreshFundDiagnosis: (code: string) =>
  send<DiagnosisRefreshJob>("POST", `/api/funds/${encodeURIComponent(code)}/diagnosis/refresh`),
fundDiagnosisRefreshJob: (code: string, jobId: string) =>
  get<DiagnosisRefreshJob>(`/api/funds/${code}/diagnosis/refresh/${jobId}`),
```

- [ ] Add `diagnosis-ui.ts` helpers:

```ts
import type { DiagnosisLabel, RiskLightLevel } from "@/types/api";

export function riskLightClass(level: RiskLightLevel): string { ... }
export function decisionLabelClass(label: DiagnosisLabel): string { ... }
export function compareUrlForPeers(code: string, peers: { fund_code: string }[]): string { ... }
```

- [ ] Add tests for API URLs and helper outputs.

- [ ] Run frontend unit tests:

```bash
npm test
```

Expected: all pass.

## Task 9: Fund Diagnosis Card

**Files:**

- Create `frontend/src/components/FundDiagnosisCard.tsx`
- Modify `frontend/app/funds/[code]/page.tsx`

- [ ] Implement `FundDiagnosisCard` props:

```ts
interface FundDiagnosisCardProps {
  code: string;
  data: FundDiagnosis | undefined;
  error: unknown;
  isLoading: boolean;
  onRefresh: () => void;
  refreshing: boolean;
}
```

- [ ] Render states:

- Loading: `StateBlock title="加载基金体检" tone="loading"`.
- Error: `StateBlock title="基金体检加载失败" tone="error"`.
- Missing data: show gray missing-data chips.
- Peers empty: show "暂无同类候选数据，可先刷新体检数据"。
- Refreshing: button disabled + 显示 spinner，不允许重复点击。
- Refresh job running: 每 1 秒轮询 `fundDiagnosisRefreshJob`，`done/failed/missing` 后停止轮询。

前端组件测试（必加，`frontend/tests/FundDiagnosisCard.test.tsx`）至少 4 个用例：

```tsx
test("loading state")
test("error state")
test("full data state renders decision label, risk lights, peers")
test("missing_data 占大头时展示灰灯和 missing chips")
```

测试用 vitest + @testing-library/react + happy-dom（已在 `frontend/package.json` 里就检查；不在则 Task 8 之前补依赖）。

- [ ] Add diagnosis query and mutation to fund detail page:

```ts
const diagnosis = useQuery({
  queryKey: ["fundDiagnosis", code, period],
  queryFn: () => api.fundDiagnosis(code, period),
});

const [refreshJobId, setRefreshJobId] = useState<string | null>(null);

const refreshDiagnosisJob = useQuery({
  queryKey: ["fundDiagnosisRefreshJob", code, refreshJobId],
  queryFn: () => api.fundDiagnosisRefreshJob(code, refreshJobId!),
  enabled: Boolean(refreshJobId),
  refetchInterval: (query) => {
    const status = query.state.data?.status;
    return status === "done" || status === "failed" || status === "missing" ? false : 1000;
  },
});

useEffect(() => {
  const status = refreshDiagnosisJob.data?.status;
  if (!status) return;
  if (status === "done") {
    setRefreshJobId(null);
    qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
    toast.push("体检数据已刷新", "success");
  } else if (status === "failed" || status === "missing") {
    setRefreshJobId(null);
    toast.push(`体检刷新失败：${refreshDiagnosisJob.data?.error ?? status}`, "error");
  }
}, [code, qc, refreshDiagnosisJob.data, toast]);

const refreshDiagnosis = useMutation({
  mutationFn: () => api.refreshFundDiagnosis(code),
  onSuccess: (job) => {
    if (job.status === "done") {
      qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
      toast.push("体检数据已是最新", "success");
    } else {
      setRefreshJobId(job.job_id);
      toast.push("已开始刷新体检数据", "info");
    }
  },
  onError: (err) => toast.push(`体检刷新失败：${String(err)}`, "error"),
});
```

- [ ] Place card after the basic info / latest NAV section and **before** `HoldingCard`. 用户进详情页应当先看到体检结论（红黄绿灯）再看自己的浮盈亏，避免被自己持仓盈亏左右判断。

- [ ] Pass `refreshing={refreshDiagnosis.isPending || Boolean(refreshJobId)}` to `FundDiagnosisCard`.

- [ ] Run typecheck:

```bash
npx tsc --noEmit
```

Expected: no TypeScript errors.

## Task 10: Full Verification

- [ ] Run backend tests:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: all pass.

- [ ] Run frontend tests:

```bash
npm test
```

Expected: all pass.

- [ ] Run typecheck:

```bash
npx tsc --noEmit
```

Expected: exit 0.

- [ ] Run production build:

```bash
npm run build
```

Expected: build succeeds.

- [ ] Manual smoke:

1. Start FastAPI.
2. Start Next.js.
3. Open `/funds/110011`.
4. Confirm the diagnosis card renders.
5. Confirm missing enhancement data appears as gray/missing, not as a page error.
6. Click “刷新体检数据”.
7. Confirm QA “110011能买吗” reaches diagnosis and “帮我买1000块110011” is rejected.

## Commit Plan

- Commit docs first:

```bash
git add docs/superpowers/specs/2026-07-02-fund-diagnosis-design.md docs/superpowers/plans/2026-07-02-fund-diagnosis.md
git commit -m "docs: plan fund diagnosis feature"
```

- Commit backend parser/profile/rules/API:

```bash
git add backend
git commit -m "feat: add fund diagnosis backend"
```

- Commit LangGraph policy/tool:

```bash
git add backend/graph backend/tools backend/tests
git commit -m "feat: expose fund diagnosis to qa"
```

- Commit frontend:

```bash
git add frontend
git commit -m "feat: show fund diagnosis on detail page"
```

## Out of Scope (Defer To Future Specs)

明确把以下外部建议里的能力划入 v1 之后，避免交付时被追问：

- **持仓重合度分析**（多只基金 → 共享持股 / 行业比例）：v1 只对单只基金体检。
- **完整适配人群判断**：v1 只输出 `suitable_for.avoid`，不做风险偏好问卷。
- **涨跌原因强解释**：v1 不解释当日涨跌归因，由现有公告 + 市场指数兜底。
- **定投 / 分批建议**：v1 明确不输出仓位百分比、节奏、止盈止损点位。
- **自选基金组合体检**：v1 只对单只基金；"每周/月输出组合风险变化"不在本阶段。
- **基金经理完整画像**：v1 仅抓 `manager` + `manager_summary` 字符串，不做任期年限、历史业绩排行榜。
- **公开评级**：v1 不接入 `fund_rating_all`，schema 不建 `rating` 字段。

后续阶段如果重新激活任意一项，需要重新走 spec 评审。
