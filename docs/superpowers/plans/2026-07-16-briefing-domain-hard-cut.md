# Briefing Domain Hard Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Briefing domain into focused type, collector, module, composer, persistence, workflow, job, and state modules, switch every consumer to those narrow entries, and delete the two legacy service modules without changing observable behavior.

**Architecture:** `workflow.run_daily_briefing` remains the synchronous application use case and orchestrates evidence, collection, composition, and short-transaction persistence. `jobs` owns process-local asynchronous submission and business singleflight, while private `_state` provides cycle-free thread-safe state shared with `workflow`. API, Scheduler, and market tools import `jobs`, `workflow`, and `persistence` directly; the package initializer exposes no broad facade.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, PostgreSQL 16 + pgvector, FastAPI, APScheduler, `ThreadPoolExecutor`, pytest, AST contract tests.

## Global Constraints

- This is a pure structural migration: do not change prompts, model choice, model parameters, output parsing, module order, warning/error aggregation, persistence fields, API responses, or Scheduler configuration.
- Delete `backend/services/briefing/briefing_service.py` and `backend/services/briefing/module_briefing.py`; do not retain aliases, re-exports, deprecation shims, or duplicate implementations.
- `backend/services/briefing/__init__.py` must not eagerly import domain modules or become a new facade.
- Preserve the exact signatures of `collect_watchlist_snapshot`, `compose_briefing`, `compose_briefing_v2`, `run_daily_briefing`, `read_briefing`, and `start_run_async` except for their module paths.
- Models are explicitly injected. Briefing service modules must not import `backend.graph` or `backend.agent` implementations.
- Network, market-data, and LLM calls must execute without a long-lived database transaction.
- When `run_daily_briefing` receives no external Session, evidence ingest, evidence search, and Briefing persistence use the existing independent short transactions.
- When an external Session is supplied, repository writes only `flush()`; the caller owns commit and rollback.
- Repository functions must not call `commit()`, `rollback()`, `close()`, or construct Sessions.
- Preserve process-local Briefing singleflight. Do not add PostgreSQL advisory locks, task-table claims, Redis, Celery, or cross-process guarantees.
- Use ordinary process locks only for in-memory state. Do not add SQLite locks, retry helpers, fixtures, pragmas, pools, URLs, or compatibility branches.
- PostgreSQL is the only database for the complete backend regression. `TEST_DATABASE_URL` must point to a disposable database whose name ends in `_test`.
- Tasks 1–6 are RED/GREEN checkpoints but are not committed separately. Because this is a hard cut, create one atomic implementation commit only after Task 7 and the full verification pass.

---

## File Map

### Briefing domain

- `backend/services/briefing/types.py`: Protocols, existing DTOs, `BriefTypeProfile`, and `ModuleSection`; imports no other Briefing business module.
- `backend/services/briefing/modules.py`: brief-type profile registry, deterministic builders, module runner, quick summary, and data statement.
- `backend/services/briefing/collectors.py`: data-quality calculation, watchlist/market snapshot collection, and narrow market-evidence functions.
- `backend/services/briefing/composer.py`: `compose_briefing` and `compose_briefing_v2`, prompt rendering, injected-model calls, and existing output fallbacks.
- `backend/services/briefing/persistence.py`: `persist_briefing` and `read_briefing`.
- `backend/services/briefing/_state.py`: process-local last-run and active-job state protected by locks.
- `backend/services/briefing/workflow.py`: synchronous `run_daily_briefing` orchestration and last-run update.
- `backend/services/briefing/jobs.py`: `start_run_async`, `get_last_run`, and `reset_for_tests`.
- `backend/services/briefing/prompts.py`: unchanged.
- `backend/services/briefing/__init__.py`: package documentation only, with an empty `__all__`.

### Consumers and contracts

- `backend/api/routes/briefing.py`: calls `briefing.jobs.start_run_async`.
- `backend/scheduler/scheduler.py`: calls `briefing.workflow.run_daily_briefing`.
- `backend/tools/market_tools.py`: calls `briefing.persistence.read_briefing`.
- `backend/services/__init__.py`: removes the two legacy compatibility mappings.
- `backend/tests/test_briefing_domain_contract.py`: hard-cut paths, old import/patch strings, dependency direction, and package-facade contracts.
- `backend/tests/test_service_import_compatibility.py`: removes only the two Briefing legacy aliases; all unrelated compatibility coverage stays intact.
- `backend/tests/test_service_layer_import_boundaries.py`: checks injected-model signatures on `workflow` and `composer`.
- `backend/tests/test_market_evidence_service.py`: checks the new Briefing modules for graph/model reverse imports.

### Test ownership

- `backend/tests/test_briefing_types.py`: stable DTO and dataclass ownership.
- `backend/tests/test_briefing_modules.py`: profile selection and deterministic module builders.
- `backend/tests/test_briefing_collectors.py`: snapshot collection and data quality.
- `backend/tests/test_briefing_composer.py`: prompt/model behavior and output parsing.
- `backend/tests/test_briefing_persistence.py`: ORM characterization, persistence helper, and read deserialization.
- `backend/tests/test_briefing_workflow.py`: synchronous orchestration, transaction phases, failure aggregation, and last-run state.
- `backend/tests/test_briefing_jobs.py`: async submission, process-local singleflight, release, and reset.
- Delete `backend/tests/test_briefing_service.py` after all its tests have moved.

---

### Task 1: Make `types.py` and `modules.py` the real deterministic domain boundary

**Files:**
- Modify: `backend/services/briefing/types.py`
- Modify: `backend/services/briefing/modules.py`
- Create: `backend/tests/test_briefing_modules.py`
- Modify: `backend/tests/test_briefing_types.py`
- Source to delete in Task 7: `backend/services/briefing/module_briefing.py:17-1043`

**Interfaces:**
- Produces: `BriefTypeProfile`, `ModuleSection`, all existing DTOs, and model Protocols from `backend.services.briefing.types`.
- Produces: `get_brief_type_profile`, nine deterministic builders, `_builder_for_module`, `run_module_builders`, `run_quick_summary_module`, and `run_data_statement_module` from `backend.services.briefing.modules`.
- Does not produce: `compose_briefing_v2`; that belongs to Task 3.

- [ ] **Step 1: Change the type test to require runtime ownership in `types.py`**

Replace `test_briefing_profile_types_are_still_reexported` with:

```python
def test_briefing_profile_types_are_owned_by_types_module():
    from backend.services.briefing import types

    assert types.BriefTypeProfile.__module__ == types.__name__
    assert types.ModuleSection.__module__ == types.__name__
    assert hasattr(types.BriefTypeProfile, "__dataclass_fields__")
    assert hasattr(types.ModuleSection, "__dataclass_fields__")

    profile = types.BriefTypeProfile.post_market()
    section = types.ModuleSection(key="market_state", title="市场状态")

    assert profile.brief_type == "post_market"
    assert section.to_dict()["status"] == "ready"
```

Add a leaf-module check:

```python
def test_types_module_does_not_import_other_briefing_modules():
    import ast
    import inspect

    from backend.services.briefing import types

    tree = ast.parse(inspect.getsource(types))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(
        name.startswith("backend.services.briefing.")
        for name in imported
    )
```

- [ ] **Step 2: Move the existing module characterization to the new test file**

Move `TestBriefingV2Modules` from `backend/tests/test_briefing_service.py` into
`backend/tests/test_briefing_modules.py`. Use this import and call surface:

```python
from backend.services.briefing import modules


def test_pre_market_overnight_module_uses_evidence():
    profile, warnings = modules.get_brief_type_profile("pre_market")
    built, order, module_warnings = modules.run_module_builders(
        profile=profile,
        snapshot={},
        evidence=[{
            "id": 1,
            "category": "overnight",
            "title": "美股上涨",
            "summary": "纳指收涨",
            "source": "wire",
        }],
        context={},
    )

    assert warnings == []
    assert "overnight" in built
    assert "overnight" in order
    assert built["overnight"].key == "overnight"
    assert isinstance(module_warnings, list)
```

Add a source-ownership assertion so the current re-export cannot pass:

```python
def test_modules_owns_builders_without_legacy_reexport():
    import inspect

    from backend.services.briefing import modules

    source = inspect.getsource(modules)
    assert "module_briefing" not in source
    assert modules.run_module_builders.__module__ == modules.__name__
```

- [ ] **Step 3: Run the tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q \
  backend/tests/test_briefing_types.py \
  backend/tests/test_briefing_modules.py
```

Expected: FAIL because the dataclasses are unavailable at runtime from `types.py`, and `modules.py` still re-exports the legacy implementation.

- [ ] **Step 4: Move the two dataclasses into `types.py`**

Remove `TYPE_CHECKING` and the legacy import. Add `asdict` and `Literal`, then move the existing class bodies unchanged:

```python
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional, Protocol, TypeVar


@dataclass
class BriefTypeProfile:
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
                "quick_summary", "market_state", "themes_and_flows",
                "watchlist_impact", "risk_radar", "key_evidence",
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
                "quick_summary", "overnight", "key_evidence",
                "watchlist_impact", "risk_radar", "data_statement",
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
                "quick_summary", "market_state", "themes_and_flows",
                "intraday_anomaly", "watchlist_impact", "risk_radar",
                "data_statement",
            ],
            optional_modules=["key_evidence"],
            forbidden_modules=["overnight"],
            data_window="intraday",
            max_markdown_words=600,
        )


@dataclass
class ModuleSection:
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
```

The values above are the existing profile contract and must remain byte-for-byte equivalent after the move.

- [ ] **Step 5: Replace `modules.py` re-exports with the deterministic implementation**

Move these exact existing definitions from `module_briefing.py` into `modules.py`, preserving every body and execution order:

```text
_PROFILES
_init_profiles
get_brief_type_profile
_THEME_KEYWORD_MAP
_match_fund_theme
build_market_state_module
build_themes_and_flows_module
_infer_trend
build_watchlist_impact_module
build_risk_radar_module
build_key_evidence_module
build_data_statement_module
build_quick_summary_module
build_overnight_module
build_intraday_anomaly_module
_builder_for_module
run_module_builders
run_quick_summary_module
run_data_statement_module
```

Use only these cross-module imports:

```python
from typing import Any

from backend.services.briefing.types import BriefTypeProfile, ModuleSection
```

Set `__all__` to the public deterministic surface:

```python
__all__ = [
    "build_data_statement_module",
    "build_intraday_anomaly_module",
    "build_key_evidence_module",
    "build_market_state_module",
    "build_overnight_module",
    "build_quick_summary_module",
    "build_risk_radar_module",
    "build_themes_and_flows_module",
    "build_watchlist_impact_module",
    "get_brief_type_profile",
    "run_data_statement_module",
    "run_module_builders",
    "run_quick_summary_module",
]
```

- [ ] **Step 6: Run the deterministic-domain tests and confirm GREEN**

Run the command from Step 3.

Expected: all tests PASS and `rg -n "module_briefing" backend/services/briefing/types.py backend/services/briefing/modules.py` returns no matches.

---

### Task 2: Move snapshot collection and data quality into `collectors.py`

**Files:**
- Modify: `backend/services/briefing/collectors.py`
- Create: `backend/tests/test_briefing_collectors.py`
- Modify later: `backend/tests/test_briefing_service.py`
- Source to delete in Task 7: `backend/services/briefing/briefing_service.py:41-329`

**Interfaces:**
- Produces: `compute_data_quality(snapshot: dict, evidence: list[dict]) -> dict`.
- Produces: `collect_watchlist_snapshot(*, fund_codes: list[str] | None = None, session=None) -> dict`.
- Produces narrow evidence call points: `collect_and_run_for_brief_type` and `search_evidence`.
- Keeps `_collect_market_snapshot`, `_collect_market_breadth`, `_collect_sector_snapshot`, `_lookup_fund_name`, and `_safe_get` private.

- [ ] **Step 1: Move collector characterization tests to the new module path**

Move `TestCollectWatchlistSnapshot` from `test_briefing_service.py` to
`test_briefing_collectors.py`. Replace dependency targets using this exact map:

```text
briefing_service                         → collectors
briefing_service._collect_market_snapshot → collectors._collect_market_snapshot
briefing_service._collect_market_breadth  → collectors._collect_market_breadth
briefing_service._collect_sector_snapshot → collectors._collect_sector_snapshot
backend.services.briefing.briefing_service.settings
                                         → backend.services.briefing.collectors.settings
```

Add focused data-quality coverage:

```python
def test_compute_data_quality_complete_when_core_data_and_evidence_exist():
    from backend.services.briefing.collectors import compute_data_quality

    result = compute_data_quality(
        {
            "market_snapshot": [{"symbol": "000300"}],
            "market_breadth": {"up": 1, "down": 1},
            "industry_sectors": [{"name": "银行"}],
            "errors": [],
            "collect_meta": {"data_sources_last_updated": {"market_snapshot": "now"}},
        },
        [
            {"category": "policy"},
            {"category": "announcement"},
            {"category": "macro"},
        ],
    )

    assert result["data_quality"] == "complete"
    assert result["confidence"] == "high"
    assert result["missing_data"] == []
```

- [ ] **Step 2: Run the collector tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q backend/tests/test_briefing_collectors.py
```

Expected: FAIL because `collectors.py` does not yet define snapshot collection or data quality.

- [ ] **Step 3: Replace the collector re-export shell with the exact existing logic**

Move these symbols from `briefing_service.py` without changing their bodies:

```text
_DATA_DIMENSIONS
compute_data_quality
settings
_get_settings
_today
_lookup_fund_name
collect_watchlist_snapshot
_collect_market_snapshot
_collect_market_breadth
_collect_sector_snapshot
_safe_get
```

Use these imports:

```python
from datetime import datetime
from typing import Any

from backend.config import settings as app_settings
from backend.services.fund import fund_service
from backend.services.market import data_collector as dc
from backend.services.market import market_evidence_service
from backend.services.market import market_service
from backend.services.watchlist import watchlist_service

collect_and_run_for_brief_type = market_evidence_service.collect_and_run_for_brief_type
search_evidence = market_evidence_service.search_evidence
settings = app_settings.get_settings()
```

Export only the capability surface:

```python
__all__ = [
    "collect_and_run_for_brief_type",
    "collect_watchlist_snapshot",
    "compute_data_quality",
    "search_evidence",
]
```

- [ ] **Step 4: Run collector tests and confirm GREEN**

Run the command from Step 2.

Expected: all tests PASS, including the existing max-fund cap and graceful source fallbacks.

---

### Task 3: Make `composer.py` own both injected-model composers

**Files:**
- Modify: `backend/services/briefing/composer.py`
- Create: `backend/tests/test_briefing_composer.py`
- Modify later: `backend/tests/test_briefing_service.py`
- Source to delete in Task 7: `backend/services/briefing/briefing_service.py:339-496`
- Source to delete in Task 7: `backend/services/briefing/module_briefing.py:1045-1134`

**Interfaces:**
- Produces: `compose_briefing(snapshot, evidence=None, *, model=None, profile=None) -> dict`.
- Produces: `compose_briefing_v2(profile, modules, quick_summary_mod, data_statement_mod, snapshot, evidence, *, model=None) -> dict`.
- Consumes: `collectors.compute_data_quality`, deterministic `modules`, `types.ChatModel`, and `BRIEFING_PROMPT_TEMPLATE_V2`.

- [ ] **Step 1: Move composer characterization tests and require real ownership**

Move `TestComposeBriefing` from `test_briefing_service.py` into
`test_briefing_composer.py`. Replace imports and patches with:

```python
from backend.services.briefing import composer
```

Every old call `briefing_service.compose_briefing(...)` becomes
`composer.compose_briefing(...)`. Add:

```python
def test_composer_owns_both_functions_without_legacy_reexport():
    import inspect

    from backend.services.briefing import composer

    source = inspect.getsource(composer)
    assert "briefing_service" not in source
    assert "module_briefing" not in source
    assert composer.compose_briefing.__module__ == composer.__name__
    assert composer.compose_briefing_v2.__module__ == composer.__name__


def test_compose_briefing_requires_injected_model():
    import pytest

    from backend.services.briefing.composer import compose_briefing

    with pytest.raises(RuntimeError, match="requires `model`"):
        compose_briefing({})
```

- [ ] **Step 2: Run composer tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q backend/tests/test_briefing_composer.py
```

Expected: FAIL because `composer.py` has no `compose_briefing` and still re-exports the V2 function.

- [ ] **Step 3: Move both composer implementations**

Move the current `compose_briefing` and `compose_briefing_v2` bodies byte-for-byte, changing only dependency references:

```text
module_briefing.get_brief_type_profile  → modules.get_brief_type_profile
module_briefing.run_module_builders     → modules.run_module_builders
module_briefing.run_quick_summary_module → modules.run_quick_summary_module
module_briefing.run_data_statement_module → modules.run_data_statement_module
compute_data_quality                    → collectors.compute_data_quality
```

Use these module imports so tests patch actual boundaries:

```python
import json
from datetime import datetime

from backend.config import settings as app_settings
from backend.services.briefing import collectors, modules
from backend.services.briefing.prompts import BRIEFING_PROMPT_TEMPLATE_V2
from backend.services.briefing.types import BriefTypeProfile, ChatModel, ModuleSection

settings = app_settings.get_settings()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")
```

Do not import `backend.graph`, `workflow`, or `jobs`. Export:

```python
__all__ = ["compose_briefing", "compose_briefing_v2"]
```

- [ ] **Step 4: Run composer and prompt tests and confirm GREEN**

Run:

```bash
.venv/bin/pytest -q \
  backend/tests/test_briefing_composer.py \
  backend/tests/test_briefing_prompts.py
```

Expected: composer and prompt tests PASS.

---

### Task 4: Move Briefing persistence into `persistence.py`

**Files:**
- Modify: `backend/services/briefing/persistence.py`
- Create: `backend/tests/test_briefing_persistence.py`
- Modify later: `backend/tests/test_briefing_service.py`
- Existing repository: `backend/db/repositories/briefing.py`
- Source to delete in Task 7: `backend/services/briefing/briefing_service.py:705-766`

**Interfaces:**
- Produces: `persist_briefing(session, *, briefing_date: str, payload: dict, brief_type: str = "post_market") -> Briefing`.
- Produces: `read_briefing(brief_date: str | None = None, brief_type: str = "post_market") -> dict | None`.
- Consumes: `briefing_repository.upsert_briefing` and `session_scope`.

- [ ] **Step 1: Move ORM characterization tests and add persistence service tests**

Move `TestBriefingModel` from `test_briefing_service.py` to
`test_briefing_persistence.py`. Add a helper-delegation test:

```python
def test_persist_briefing_delegates_to_flush_only_repository(monkeypatch, db_session):
    from backend.services.briefing import persistence

    captured = {}
    sentinel = object()

    def fake_upsert(session, briefing_date, payload, brief_type="post_market"):
        captured.update(
            session=session,
            briefing_date=briefing_date,
            payload=payload,
            brief_type=brief_type,
        )
        return sentinel

    monkeypatch.setattr(persistence.briefing_repository, "upsert_briefing", fake_upsert)

    result = persistence.persist_briefing(
        db_session,
        briefing_date="2026-07-16",
        payload={"title": "测试"},
        brief_type="pre_market",
    )

    assert result is sentinel
    assert captured == {
        "session": db_session,
        "briefing_date": "2026-07-16",
        "payload": {"title": "测试"},
        "brief_type": "pre_market",
    }
```

Add read deserialization coverage using a patched scope bound to the worker Session:

```python
def test_read_briefing_decodes_sections_and_missing_data(monkeypatch, db_session):
    import json
    from contextlib import contextmanager

    from backend.db.models import Briefing
    from backend.services.briefing import persistence

    row = Briefing(
        briefing_date="2026-07-16",
        brief_type="post_market",
        title="测试简报",
        markdown="# 测试",
        sections_json=json.dumps({
            "modules": {
                "data_statement": {
                    "content": {
                        "failed_modules": [{"module": "macro"}],
                        "data_sources_last_updated": {"market": "now"},
                    },
                },
            },
        }),
        missing_data_json='["macro_evidence"]',
        evidence_count=0,
    )
    db_session.add(row)
    db_session.flush()

    @contextmanager
    def fake_scope():
        yield db_session

    monkeypatch.setattr(persistence, "session_scope", fake_scope)

    result = persistence.read_briefing("2026-07-16")

    assert result["missing_data"] == ["macro_evidence"]
    assert result["failed_modules"] == [{"module": "macro"}]
    assert result["data_sources_last_updated"] == {"market": "now"}
```

- [ ] **Step 2: Run persistence tests and confirm RED**

Run:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  .venv/bin/pytest -q backend/tests/test_briefing_persistence.py
```

Expected: FAIL because `persistence.py` does not define `persist_briefing` or `read_briefing`.

- [ ] **Step 3: Implement the narrow write helper**

```python
from backend.db.repositories import briefing as briefing_repository


def persist_briefing(
    session,
    *,
    briefing_date: str,
    payload: dict,
    brief_type: str = "post_market",
) -> Briefing:
    return briefing_repository.upsert_briefing(
        session,
        briefing_date=briefing_date,
        payload=payload,
        brief_type=brief_type,
    )
```

Do not call `flush()` again; the repository already flushes.

- [ ] **Step 4: Move `read_briefing` unchanged**

Move the existing query, JSON decoding, V2/legacy data-statement extraction, and returned keys from
`briefing_service.py:705-766`. Use:

```python
import json

from sqlalchemy import select

from backend.db.models import Briefing
from backend.db.session_scope import session_scope
```

Export only:

```python
__all__ = ["persist_briefing", "read_briefing"]
```

- [ ] **Step 5: Run persistence and transaction ownership tests and confirm GREEN**

Run:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  .venv/bin/pytest -q \
    backend/tests/test_briefing_persistence.py \
    backend/tests/test_transaction_ownership_contract.py
```

Expected: all tests PASS and the repository contract reports no commit, rollback, close, or Session construction.

---

### Task 5: Isolate process-local runtime state

**Files:**
- Create: `backend/services/briefing/_state.py`
- Create: `backend/tests/test_briefing_jobs.py`
- Source to delete in Task 7: `backend/services/briefing/briefing_service.py:139-166,697-702,769-776`

**Interfaces:**
- Produces privately: `_state.update_last_run`, `_state.get_last_run`, `_state.claim_active_job`, `_state.release_active_job`, and `_state.reset_for_tests`.
- Consumes no Briefing business module.
- Provides state primitives used by workflow and jobs in Task 6.

- [ ] **Step 1: Add direct state tests**

Create `backend/tests/test_briefing_jobs.py`:

```python
from __future__ import annotations

from backend.services.briefing import _state


def setup_function():
    _state.reset_for_tests()


def teardown_function():
    _state.reset_for_tests()


def test_get_last_run_returns_empty_snapshot():
    assert _state.get_last_run() == {
        "last_run_at": None,
        "trigger": None,
        "total_funds": 0,
        "succeeded": 0,
        "failed": 0,
        "failures": [],
    }


def test_last_run_is_copied_on_write_and_read():
    snapshot = {
        "last_run_at": "2026-07-16T12:00:00",
        "trigger": "test",
        "total_funds": 1,
        "succeeded": 1,
        "failed": 0,
        "failures": [],
    }
    _state.update_last_run(snapshot)

    result = _state.get_last_run()
    result["trigger"] = "mutated"

    assert _state.get_last_run()["trigger"] == "test"


def test_active_job_claim_release_and_reset():
    assert _state.claim_active_job("job-a") is None
    assert _state.claim_active_job("job-b") == "job-a"

    _state.release_active_job("job-b")
    assert _state.claim_active_job("job-c") == "job-a"

    _state.release_active_job("job-a")
    assert _state.claim_active_job("job-c") is None

    _state.reset_for_tests()
    assert _state.claim_active_job("job-d") is None
```

- [ ] **Step 2: Run state tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q backend/tests/test_briefing_jobs.py
```

Expected: FAIL because `_state.py` does not exist.

- [ ] **Step 3: Implement `_state.py` with no domain imports**

```python
"""Thread-safe process-local Briefing runtime state."""
from __future__ import annotations

from threading import Lock

_last_run_lock = Lock()
_active_job_lock = Lock()
_last_run: dict = {}
_active_job_id: str | None = None


def _empty_snapshot() -> dict:
    return {
        "last_run_at": None,
        "trigger": None,
        "total_funds": 0,
        "succeeded": 0,
        "failed": 0,
        "failures": [],
    }


def update_last_run(snapshot: dict) -> None:
    with _last_run_lock:
        _last_run.clear()
        _last_run.update(snapshot)


def get_last_run() -> dict:
    with _last_run_lock:
        if not _last_run or _last_run.get("last_run_at") is None:
            return _empty_snapshot()
        return dict(_last_run)


def claim_active_job(job_id: str) -> str | None:
    global _active_job_id
    with _active_job_lock:
        if _active_job_id is not None:
            return _active_job_id
        _active_job_id = job_id
        return None


def release_active_job(job_id: str) -> None:
    global _active_job_id
    with _active_job_lock:
        if _active_job_id == job_id:
            _active_job_id = None


def reset_for_tests() -> None:
    global _active_job_id
    with _last_run_lock:
        _last_run.clear()
    with _active_job_lock:
        _active_job_id = None
```

- [ ] **Step 4: Run state tests and confirm GREEN**

Run the command from Step 2.

Expected: all tests PASS and `_state.py` imports only stdlib locking support.

---

### Task 6: Move synchronous orchestration into `workflow.py`

**Files:**
- Create: `backend/services/briefing/workflow.py`
- Modify: `backend/services/briefing/jobs.py`
- Create: `backend/tests/test_briefing_workflow.py`
- Modify: `backend/tests/test_briefing_jobs.py`
- Modify later: `backend/tests/test_briefing_service.py`
- Source to delete in Task 7: `backend/services/briefing/briefing_service.py:499-694,780-815`

**Interfaces:**
- Produces: `run_daily_briefing(*, trigger="scheduled", session=None, brief_type="post_market", model=None) -> dict`.
- Produces: `jobs.start_run_async(*, trigger="manual", brief_type="post_market", model=None) -> dict`, `jobs.get_last_run() -> dict`, and `jobs.reset_for_tests() -> None`.
- Consumes: `collectors`, `composer`, `persistence`, `modules`, `_state`, and `session_scope`.
- `workflow` must not import `jobs`; `jobs` imports `workflow` and `_state`.

- [ ] **Step 1: Move workflow characterization tests to real dependency boundaries**

Move `TestRunDailyBriefing` from `test_briefing_service.py` into
`test_briefing_workflow.py`. Use:

```python
from backend.services.briefing import _state, workflow
```

Apply this exact patch-target map:

```text
briefing_service.collect_watchlist_snapshot
  → workflow.collectors.collect_watchlist_snapshot
briefing_service.compose_briefing
  → workflow.composer.compose_briefing
briefing_service.market_evidence_service.collect_and_run_for_brief_type
  → workflow.collectors.collect_and_run_for_brief_type
briefing_service.market_evidence_service.search_evidence
  → workflow.collectors.search_evidence
briefing_service.run_daily_briefing
  → workflow.run_daily_briefing
briefing_service.reset_for_tests
  → _state.reset_for_tests
briefing_service.get_last_run
  → _state.get_last_run
```

Correct the evidence test's fake composer so it preserves the final signature:

```python
lambda snap, evidence=None, *, profile=None, model=None: {
    "markdown": "# 测试简报",
    "sections": {},
    "warnings": [],
    "llm_model": "test",
}
```

- [ ] **Step 2: Add a no-long-transaction orchestration assertion**

Add a unit test that records scope boundaries and network/model calls:

```python
def test_owned_workflow_closes_each_short_scope_before_collect_and_compose(monkeypatch):
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from backend.services.briefing import workflow

    events = []
    scope_depth = 0

    @contextmanager
    def fake_scope():
        nonlocal scope_depth
        scope_depth += 1
        events.append("scope_enter")
        try:
            yield object()
        finally:
            events.append("scope_exit")
            scope_depth -= 1

    monkeypatch.setattr(workflow, "session_scope", fake_scope)
    monkeypatch.setattr(
        workflow.collectors,
        "collect_and_run_for_brief_type",
        lambda **_: events.append("ingest"),
    )
    monkeypatch.setattr(
        workflow.collectors,
        "search_evidence",
        lambda **_: [],
    )

    def collect(**_):
        assert scope_depth == 0
        events.append("collect")
        return {
            "market_snapshot": [{"market_date": "2026-07-16"}],
            "watchlist_changes": [{"fund_code": "000001"}],
            "errors": [],
            "collect_meta": {},
        }

    def compose(*_args, **_kwargs):
        assert scope_depth == 0
        events.append("compose")
        return {"markdown": "ok", "sections": {}, "warnings": []}

    monkeypatch.setattr(workflow.collectors, "collect_watchlist_snapshot", collect)
    monkeypatch.setattr(workflow.composer, "compose_briefing", compose)
    monkeypatch.setattr(
        workflow.persistence,
        "persist_briefing",
        lambda session, **_: events.append("persist"),
    )

    workflow.run_daily_briefing(trigger="test", model=MagicMock())

    assert events == [
        "scope_enter", "ingest", "scope_exit",
        "scope_enter", "scope_exit",
        "collect", "compose",
        "scope_enter", "persist", "scope_exit",
    ]
```

- [ ] **Step 3: Run workflow tests and confirm RED**

Run:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  .venv/bin/pytest -q backend/tests/test_briefing_workflow.py
```

Expected: FAIL because `workflow.py` does not yet contain the real orchestration.

- [ ] **Step 4: Move `run_daily_briefing` and replace only dependency references**

Move the existing body from `briefing_service.py:499-694` without altering failure payloads,
placeholder markdown, counters, title/source values, evidence limit, profile fallback, or payload fields.
Use:

```python
import json
from datetime import datetime

from backend.db.session_scope import session_scope
from backend.services.briefing import _state, collectors, composer, modules, persistence
from backend.services.briefing.types import ChatModel


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
```

Replace the legacy calls exactly:

```text
module_briefing.get_brief_type_profile → modules.get_brief_type_profile
market_evidence_service.collect_and_run_for_brief_type
  → collectors.collect_and_run_for_brief_type
market_evidence_service.search_evidence → collectors.search_evidence
collect_watchlist_snapshot → collectors.collect_watchlist_snapshot
compute_data_quality → collectors.compute_data_quality
compose_briefing → composer.compose_briefing
upsert_briefing → persistence.persist_briefing
_last_run clear/update under _lock → _state.update_last_run(snap)
```

The persistence phase must call:

```python
persistence.persist_briefing(
    target_session,
    briefing_date=today,
    payload={**payload, "brief_type": effective_brief_type},
    brief_type=effective_brief_type,
)
```

where `target_session` is the short-scope Session in owned mode or the supplied Session in caller-owned mode.
Export:

```python
__all__ = ["run_daily_briefing"]
```

- [ ] **Step 5: Add asynchronous job tests after workflow exists**

Append to `backend/tests/test_briefing_jobs.py`:

```python
from backend.services.briefing import jobs


class CapturingExecutor:
    def __init__(self):
        self.tasks = []

    def submit(self, fn):
        self.tasks.append(fn)
        return object()


def test_start_run_async_is_singleflight_and_releases_after_task(monkeypatch):
    executor = CapturingExecutor()
    calls = []
    monkeypatch.setattr(jobs, "_async_executor", executor)
    monkeypatch.setattr(
        jobs.workflow,
        "run_daily_briefing",
        lambda **kwargs: calls.append(kwargs),
    )

    first = jobs.start_run_async(
        trigger="manual",
        brief_type="pre_market",
        model="model",
    )
    duplicate = jobs.start_run_async(brief_type="pre_market", model="model")

    assert first["status"] == "started"
    assert duplicate == {
        "status": "running",
        "job_id": first["job_id"],
        "brief_type": "pre_market",
    }
    assert len(executor.tasks) == 1

    executor.tasks[0]()

    assert calls == [{
        "trigger": "manual",
        "brief_type": "pre_market",
        "model": "model",
    }]
    third = jobs.start_run_async(brief_type="pre_market", model="model")
    assert third["status"] == "started"


def test_start_run_async_releases_claim_when_workflow_raises(monkeypatch):
    import pytest

    executor = CapturingExecutor()
    monkeypatch.setattr(jobs, "_async_executor", executor)

    def fail(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs.workflow, "run_daily_briefing", fail)
    first = jobs.start_run_async(model="model")

    with pytest.raises(RuntimeError, match="boom"):
        executor.tasks[0]()

    second = jobs.start_run_async(model="model")
    assert first["job_id"] != second["job_id"]


def test_public_status_and_reset_delegate_to_state():
    _state.update_last_run({
        "last_run_at": "2026-07-16T12:00:00",
        "trigger": "test",
        "total_funds": 0,
        "succeeded": 0,
        "failed": 0,
        "failures": [],
    })

    assert jobs.get_last_run()["trigger"] == "test"

    jobs.reset_for_tests()
    assert jobs.get_last_run()["last_run_at"] is None
```

- [ ] **Step 6: Replace the jobs placeholder with the async wrapper**

```python
"""Briefing asynchronous submission and public runtime status."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from backend.services.briefing import _state, workflow
from backend.services.briefing.types import ChatModel

_async_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="briefing-run",
)


def get_last_run() -> dict:
    return _state.get_last_run()


def reset_for_tests() -> None:
    _state.reset_for_tests()


def start_run_async(
    *,
    trigger: str = "manual",
    brief_type: str = "post_market",
    model: ChatModel | None = None,
) -> dict:
    job_id = uuid.uuid4().hex[:8]
    active_job_id = _state.claim_active_job(job_id)
    if active_job_id is not None:
        return {
            "status": "running",
            "job_id": active_job_id,
            "brief_type": brief_type,
        }

    def _task() -> None:
        try:
            workflow.run_daily_briefing(
                trigger=trigger,
                brief_type=brief_type,
                model=model,
            )
        finally:
            _state.release_active_job(job_id)

    _async_executor.submit(_task)
    return {
        "status": "started",
        "trigger": trigger,
        "brief_type": brief_type,
        "job_id": job_id,
    }


__all__ = ["get_last_run", "reset_for_tests", "start_run_async"]
```

- [ ] **Step 7: Run workflow, jobs, and persistence tests and confirm GREEN**

Run:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  .venv/bin/pytest -q \
    backend/tests/test_briefing_workflow.py \
    backend/tests/test_briefing_jobs.py \
    backend/tests/test_briefing_persistence.py
```

Expected: all tests PASS, including the no-long-transaction event order.

---

### Task 7: Hard-switch consumers, add structural contracts, and delete legacy modules

**Files:**
- Create: `backend/tests/test_briefing_domain_contract.py`
- Modify: `backend/api/routes/briefing.py`
- Modify: `backend/scheduler/scheduler.py`
- Modify: `backend/tools/market_tools.py`
- Modify: `backend/services/briefing/__init__.py`
- Modify: `backend/services/__init__.py`
- Modify: `backend/tests/test_briefing_route.py`
- Modify: `backend/tests/test_scheduler_briefing.py`
- Modify: `backend/tests/test_tools.py`
- Modify: `backend/tests/test_market_evidence_service.py`
- Modify: `backend/tests/test_service_import_compatibility.py`
- Modify: `backend/tests/test_service_layer_import_boundaries.py`
- Delete: `backend/services/briefing/briefing_service.py`
- Delete: `backend/services/briefing/module_briefing.py`
- Delete: `backend/tests/test_briefing_service.py`

**Interfaces:**
- API consumes: `jobs.start_run_async`.
- Scheduler consumes: `workflow.run_daily_briefing`.
- Market tool consumes: `persistence.read_briefing`.
- Produces: no legacy Briefing service import or patch path anywhere in Python source.

- [ ] **Step 1: Add the RED hard-cut and dependency contract**

Create `backend/tests/test_briefing_domain_contract.py`:

```python
"""Briefing domain hard-cut and dependency-direction contracts."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit
BRIEFING_ROOT = Path("backend/services/briefing")
LEGACY_NAMES = {"briefing_service", "module_briefing"}
LEGACY_PATHS = tuple(
    f"backend.services.briefing.{name}" for name in sorted(LEGACY_NAMES)
)


def _imports(path: Path) -> list[tuple[str, set[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append((node.module or "", {alias.name for alias in node.names}))
        elif isinstance(node, ast.Import):
            imports.extend((alias.name, set()) for alias in node.names)
    return imports


def test_legacy_briefing_modules_are_removed():
    assert not (BRIEFING_ROOT / "briefing_service.py").exists()
    assert not (BRIEFING_ROOT / "module_briefing.py").exists()


@pytest.mark.parametrize(
    "path",
    sorted(Path("backend").rglob("*.py")),
    ids=str,
)
def test_python_sources_do_not_reference_legacy_briefing_modules(path: Path):
    if path.name == "test_briefing_domain_contract.py":
        return
    source = path.read_text(encoding="utf-8")
    assert all(token not in source for token in LEGACY_PATHS), path
    for module, names in _imports(path):
        assert not (
            module == "backend.services.briefing" and names & LEGACY_NAMES
        ), path


@pytest.mark.parametrize(
    ("module_name", "forbidden"),
    [
        ("types.py", ("backend.services.briefing",)),
        ("collectors.py", (
            "backend.services.briefing.composer",
            "backend.services.briefing.workflow",
            "backend.services.briefing.jobs",
            "backend.api",
        )),
        ("composer.py", (
            "backend.services.briefing.workflow",
            "backend.services.briefing.jobs",
            "backend.api",
            "backend.graph",
            "backend.agent",
        )),
        ("workflow.py", ("backend.services.briefing.jobs",)),
        ("_state.py", ("backend.services.briefing",)),
    ],
)
def test_briefing_dependency_direction(module_name: str, forbidden: tuple[str, ...]):
    imports = _imports(BRIEFING_ROOT / module_name)
    imported_modules = [module for module, _ in imports]
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported_modules
        for prefix in forbidden
    )


def test_package_initializer_is_not_a_facade():
    path = BRIEFING_ROOT / "__init__.py"
    imports = [
        module for module, _ in _imports(path)
        if module != "__future__"
    ]
    assert imports == []
```

- [ ] **Step 2: Run the hard-cut contract and confirm RED**

Run:

```bash
.venv/bin/pytest -q backend/tests/test_briefing_domain_contract.py
```

Expected: FAIL because both old files and old imports still exist.

- [ ] **Step 3: Switch the three production consumers**

In `backend/api/routes/briefing.py`:

```python
from backend.services.briefing import jobs as briefing_jobs
```

and:

```python
return briefing_jobs.start_run_async(
    trigger="manual",
    brief_type=brief_type,
    model=model,
)
```

In `backend/scheduler/scheduler.py`:

```python
from backend.services.briefing import workflow as briefing_workflow
```

and:

```python
briefing_workflow.run_daily_briefing(trigger="scheduled", model=model)
```

In `backend/tools/market_tools.py`:

```python
from backend.services.briefing import persistence as briefing_persistence
```

and:

```python
snap = briefing_persistence.read_briefing(
    brief_date or None,
    brief_type=brief_type or "post_market",
)
```

- [ ] **Step 4: Update route, Scheduler, and tool patch targets**

Use imports of the consumer module itself so patching follows runtime lookup:

```python
# test_briefing_route.py
from backend.api.routes import briefing as briefing_route
with patch.object(briefing_route.briefing_jobs, "start_run_async", mock_run):
    response = client.post(
        "/api/briefing/run",
        headers={"X-Local-Trigger": "1"},
    )

# test_tools.py
monkeypatch.setattr(mt.briefing_persistence, "read_briefing", fake_read_briefing)
```

Keep `test_scheduler_briefing.py` registration assertions unchanged. If a test invokes the scheduled
callable, patch `sched_module.briefing_workflow.run_daily_briefing`.

- [ ] **Step 5: Update service contracts to the new public modules**

Remove these two dictionary entries from both `backend/services/__init__.py` and
`backend/tests/test_service_import_compatibility.py`:

```python
"briefing_service": "briefing.briefing_service",
"module_briefing": "briefing.module_briefing",
```

Update signatures in `test_service_layer_import_boundaries.py`:

```python
from backend.services.briefing import composer, workflow

assert "model" in inspect.signature(workflow.run_daily_briefing).parameters
assert "model" in inspect.signature(composer.compose_briefing).parameters
assert "model" in inspect.signature(composer.compose_briefing_v2).parameters
```

Replace the two old circular-import tests in `test_market_evidence_service.py` with:

```python
from pathlib import Path


def test_briefing_modules_import_without_graph_cycle():
    from backend.services.briefing import composer, persistence, workflow

    assert composer is not None
    assert persistence is not None
    assert workflow is not None


@pytest.mark.parametrize("module", ["composer.py", "workflow.py"])
def test_briefing_composition_modules_do_not_import_graph_model(module):
    path = Path("backend/services/briefing") / module
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("backend.graph")
    ]
    assert offenders == []
```

Retain the rest of the market-evidence tests unchanged.

- [ ] **Step 6: Make the package initializer narrow and delete legacy files**

Replace `backend/services/briefing/__init__.py` with:

```python
"""Briefing domain package.

Import concrete capabilities from ``types``, ``collectors``, ``modules``,
``composer``, ``persistence``, ``workflow``, or ``jobs``.
"""
from __future__ import annotations

__all__: list[str] = []
```

Delete:

```text
backend/services/briefing/briefing_service.py
backend/services/briefing/module_briefing.py
backend/tests/test_briefing_service.py
```

Before deleting the test file, verify every class moved exactly once:

```text
TestBriefingModel            → test_briefing_persistence.py
TestCollectWatchlistSnapshot → test_briefing_collectors.py
TestComposeBriefing          → test_briefing_composer.py
TestBriefingV2Modules        → test_briefing_modules.py
TestRunDailyBriefing         → test_briefing_workflow.py
```

- [ ] **Step 7: Run the full Briefing and consumer regression**

Run:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  .venv/bin/pytest -q \
    backend/tests/test_briefing_types.py \
    backend/tests/test_briefing_modules.py \
    backend/tests/test_briefing_collectors.py \
    backend/tests/test_briefing_composer.py \
    backend/tests/test_briefing_persistence.py \
    backend/tests/test_briefing_workflow.py \
    backend/tests/test_briefing_jobs.py \
    backend/tests/test_briefing_prompts.py \
    backend/tests/test_briefing_route.py \
    backend/tests/test_scheduler_briefing.py \
    backend/tests/test_tools.py \
    backend/tests/test_market_evidence_service.py \
    backend/tests/test_service_import_compatibility.py \
    backend/tests/test_service_layer_import_boundaries.py \
    backend/tests/test_transaction_ownership_contract.py \
    backend/tests/test_briefing_domain_contract.py
```

Expected: all selected tests PASS.

- [ ] **Step 8: Run static and hard-cut gates**

Run:

```bash
.venv/bin/python -m compileall -q backend
git diff --check
test ! -e backend/services/briefing/briefing_service.py
test ! -e backend/services/briefing/module_briefing.py
! rg -n \
  'backend\.services\.briefing\.(briefing_service|module_briefing)|from backend\.services\.briefing import (briefing_service|module_briefing)' \
  backend --glob '*.py' \
  --glob '!backend/tests/test_briefing_domain_contract.py'
! rg -n 'sqlite|StaticPool|NullPool|PRAGMA|call_with_sqlite_retry' \
  backend/services/briefing backend/tests/test_briefing_*.py
```

Expected: every command exits 0 and the two negated `rg` gates print no matches.

- [ ] **Step 9: Run the complete PostgreSQL backend suite**

Start the disposable PostgreSQL service if needed:

```bash
docker compose --profile test up -d postgres-test
```

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
  .venv/bin/pytest -q backend/tests
```

Expected: the complete suite PASSes with only documented skips and warnings; no test uses SQLite.

- [ ] **Step 10: Review the final diff as one hard-cut unit**

Run:

```bash
git status --short
git diff --stat
git diff --name-status
```

Expected:

- both legacy service modules and `test_briefing_service.py` are deleted;
- eight focused Briefing implementation files and seven focused test files are created or materially implemented;
- all three production consumers use narrow imports;
- no unrelated file is changed.

- [ ] **Step 11: Create the atomic implementation commit**

```bash
git add \
  backend/services/briefing \
  backend/services/__init__.py \
  backend/api/routes/briefing.py \
  backend/scheduler/scheduler.py \
  backend/tools/market_tools.py \
  backend/tests/test_briefing_domain_contract.py \
  backend/tests/test_briefing_types.py \
  backend/tests/test_briefing_modules.py \
  backend/tests/test_briefing_collectors.py \
  backend/tests/test_briefing_composer.py \
  backend/tests/test_briefing_persistence.py \
  backend/tests/test_briefing_workflow.py \
  backend/tests/test_briefing_jobs.py \
  backend/tests/test_briefing_service.py \
  backend/tests/test_briefing_route.py \
  backend/tests/test_scheduler_briefing.py \
  backend/tests/test_tools.py \
  backend/tests/test_market_evidence_service.py \
  backend/tests/test_service_import_compatibility.py \
  backend/tests/test_service_layer_import_boundaries.py
git commit -m "refactor: hard cut briefing domain modules"
```

Expected: one commit contains the complete implementation, consumer switch, tests, contracts, and legacy deletions.
