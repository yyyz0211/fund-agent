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
- AkShare enhancement failures must degrade to `missing_data`, not fail the whole diagnosis page.

## File Map

- Create `docs/superpowers/specs/2026-07-02-fund-diagnosis-design.md`: approved design spec.
- Create `backend/services/fund_code_parser.py`: extract fund codes from user text.
- Create `backend/services/fund_profile_service.py`: refresh/read optional profile cache.
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
        "peer_category": "混合型",
        "rank_total": 100,
        "rank_position": 25,
        "top10_holding_pct": 0.45,
        "top_industry_pct": 0.38,
        "rating": "五星",
        "manager_summary": "经理A",
        "source": "akshare",
        "as_of": "2026-07-02",
        "raw_errors": "[]",
    })

    row = repo.get_fund_profile(session, "110011")
    assert row["fund_code"] == "110011"
    assert row["scale"] == 12.3
    assert row["peer_category"] == "混合型"


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
    top10_holding_pct: Mapped[float | None] = mapped_column(Float)
    top_industry_pct: Mapped[float | None] = mapped_column(Float)
    rating: Mapped[str | None] = mapped_column(String)
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
        "top10_holding_pct": p.top10_holding_pct,
        "top_industry_pct": p.top_industry_pct,
        "rating": p.rating,
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
        "top10_holding_pct", "top_industry_pct", "rating", "manager_summary",
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
- Test `backend/tests/test_data_collector.py`
- Test `backend/tests/test_fund_profile_service.py`

- [ ] Add collector tests with monkeypatched AkShare DataFrames for profile parsing.

Expected collector contract:

```python
{
    "fund_code": "110011",
    "scale": 12.3,
    "scale_date": "2026-06-30",
    "peer_category": "混合型",
    "rank_total": 100,
    "rank_position": 25,
    "top10_holding_pct": 0.45,
    "top_industry_pct": 0.38,
    "rating": "五星",
    "manager_summary": "经理A",
    "missing_data": [],
    "errors": [],
    "source": "akshare",
    "as_of": "2026-07-02",
}
```

- [ ] Add profile service tests:

```python
def test_refresh_profile_persists_partial_data(session, monkeypatch):
    from backend.services import fund_profile_service as fps

    monkeypatch.setattr(fps.dc, "fetch_fund_profile", lambda code: {
        "fund_code": code,
        "scale": 12.3,
        "scale_date": "2026-06-30",
        "peer_category": "混合型",
        "rank_total": None,
        "rank_position": None,
        "top10_holding_pct": None,
        "top_industry_pct": None,
        "rating": None,
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

Use these AkShare functions:

- `ak.fund_open_fund_rank_em`
- `ak.fund_scale_change_em`
- `ak.fund_portfolio_hold_em`
- `ak.fund_portfolio_industry_allocation_em`
- `ak.fund_manager_em`
- `ak.fund_rating_all`

- [ ] Implement `fund_profile_service.refresh_profile()` and `get_profile()`.

- [ ] Run targeted tests:

```bash
.venv/bin/python -m pytest backend/tests/test_data_collector.py backend/tests/test_fund_profile_service.py -q
```

Expected: all pass.

## Task 4: Diagnosis Rules

**Files:**

- Create `backend/services/diagnosis_rules.py`
- Test `backend/tests/test_diagnosis_rules.py`

- [ ] Write rule tests covering thresholds:

```python
from backend.services.diagnosis_rules import level_for_drawdown, choose_decision_label, confidence_for


def test_drawdown_levels():
    assert level_for_drawdown(-0.26) == "red"
    assert level_for_drawdown(-0.16) == "yellow"
    assert level_for_drawdown(-0.10) == "green"
    assert level_for_drawdown(None) == "gray"


def test_decision_label_red_core_risk():
    lights = [{"key": "max_drawdown", "level": "red", "core": True}]
    assert choose_decision_label(lights, missing_data=[]) == "暂不碰"


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

- [ ] Implement pure rule functions:

```python
def level_for_drawdown(value: float | None) -> str: ...
def level_for_volatility(value: float | None) -> str: ...
def level_for_period_return(value: float | None) -> str: ...
def level_for_age_years(value: float | None) -> str: ...
def level_for_scale(value: float | None) -> str: ...
def level_for_concentration(value: float | None) -> str: ...
def choose_decision_label(lights: list[dict], missing_data: list[str]) -> str: ...
def confidence_for(core_complete: bool, profile_complete: bool, peers_count: int) -> str: ...
```

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
```

- [ ] Add routes:

```python
from backend.services import diagnosis_service as ds


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


@router.post("/{code}/diagnosis/refresh")
def refresh_diagnosis(code: str):
    return ds.refresh_diagnosis_data(code)
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
])
def test_operation_and_prediction_still_blocked(text):
    assert check_question(text) is False
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
```

- [ ] Add API client methods:

```ts
fundDiagnosis: (code: string, period = "1y") =>
  get<FundDiagnosis>(`/api/funds/${code}/diagnosis`, { period }),
fundPeers: (code: string, limit = 5, period = "1y") =>
  get<{ fund_code: string; peers: PeerFund[] }>(`/api/funds/${code}/peers`, { limit, period }),
refreshFundDiagnosis: (code: string) =>
  send<FundDiagnosis>("POST", `/api/funds/${encodeURIComponent(code)}/diagnosis/refresh`),
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
- Peers empty: show “暂无同类候选数据，可先刷新体检数据”.

- [ ] Add diagnosis query and mutation to fund detail page:

```ts
const diagnosis = useQuery({
  queryKey: ["fundDiagnosis", code, period],
  queryFn: () => api.fundDiagnosis(code, period),
});

const refreshDiagnosis = useMutation({
  mutationFn: () => api.refreshFundDiagnosis(code),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
    toast.push("体检数据已刷新", "success");
  },
  onError: (err) => toast.push(`体检刷新失败：${String(err)}`, "error"),
});
```

- [ ] Place card after `HoldingCard` or immediately after basic/latest NAV section, before NAV chart.

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
