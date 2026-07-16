# Repository Domain Hard Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic `backend.db.repository` module with six domain repository modules, migrate every in-repository consumer, and delete the legacy import path without changing persistence behavior.

**Architecture:** Each domain module owns its ORM imports, private serializers, constants, and public persistence functions. Consumers import the narrow domain module (usually as `*_repo`) so tests can continue monkeypatching module attributes. The migration is delivered as one atomic implementation commit: no compatibility facade and no duplicate implementation survives.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, PostgreSQL 16 + pgvector, pytest, AST contract tests.

## Global Constraints

- PostgreSQL is the only runtime and test database; do not add SQLite compatibility.
- Repository functions accept a caller-owned `Session` and may `flush()`, but may not `commit()`, `rollback()`, `close()`, or construct a Session.
- Preserve every SQL predicate, join, ordering, limit, upsert key, return shape, exception, and serialization rule.
- Do not rename public repository functions or their parameters.
- Delete `backend/db/repository.py`; do not retain a re-export or deprecation layer.
- Update all production, script, API, and test imports in the same implementation change.
- The implementation is one atomic commit after all tasks and verification pass.

---

### Task 1: Add hard-cut structure contracts

**Files:**
- Create: `backend/tests/test_repository_domain_contract.py`
- Modify: `backend/tests/test_transaction_ownership_contract.py`

**Interfaces:**
- Consumes: repository source paths below `backend/db/repositories/`.
- Produces: a guard that rejects the legacy file/import path and scans every domain repository for forbidden transaction calls.

- [ ] **Step 1: Add the failing hard-cut contract**

Create `backend/tests/test_repository_domain_contract.py` with repository-root-relative AST checks:

```python
from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPOSITORY_MODULES = (
    "briefing",
    "fund",
    "jobs",
    "knowledge",
    "market",
    "watchlist",
)


def _python_sources() -> list[Path]:
    return sorted(Path("backend").rglob("*.py"))


def test_legacy_repository_module_is_removed() -> None:
    assert not Path("backend/db/repository.py").exists()


@pytest.mark.parametrize("path", _python_sources(), ids=str)
def test_python_sources_do_not_import_legacy_repository(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "backend.db.repository", path
            assert not (
                node.module == "backend.db"
                and any(alias.name == "repository" for alias in node.names)
            ), path
        elif isinstance(node, ast.Import):
            assert all(alias.name != "backend.db.repository" for alias in node.names), path


@pytest.mark.parametrize("module_name", REPOSITORY_MODULES)
def test_domain_repository_imports(module_name: str) -> None:
    __import__(f"backend.db.repositories.{module_name}")
```

- [ ] **Step 2: Run the new contract and confirm RED**

Run:

```bash
.venv/bin/pytest -q backend/tests/test_repository_domain_contract.py
```

Expected: failures report that `backend/db/repository.py` exists and current source files import the legacy path.

- [ ] **Step 3: Generalize the transaction ownership contract**

Replace the single-file repository scan with parametrization over the six domain files:

```python
@pytest.mark.parametrize(
    "repo_path",
    sorted(Path("backend/db/repositories").glob("*.py")),
    ids=str,
)
def test_repository_does_not_commit_session(repo_path: Path) -> None:
    source = repo_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(repo_path))
    for fn in _method_bodies(tree):
        violation = _has_forbidden_call(fn.body)
        assert violation is None, (
            f"{repo_path}:{fn.name}() calls {violation}; repository 仅允许 flush"
        )
```

- [ ] **Step 4: Run the ownership contract**

Run:

```bash
.venv/bin/pytest -q backend/tests/test_transaction_ownership_contract.py
```

Expected: PASS before and after the move; the current re-export modules contain no forbidden calls.

---

### Task 2: Move fund and watchlist implementations

**Files:**
- Modify: `backend/db/repositories/fund.py`
- Modify: `backend/db/repositories/watchlist.py`
- Source to delete later: `backend/db/repository.py:32-639,1289-1335`

**Interfaces:**
- Produces `fund.py`: `upsert_fund`, fund profile functions, NAV functions, transaction functions, and `upsert_fund_watchlist_profile`.
- Produces `watchlist.py`: watchlist CRUD, preload update, fund-name backfill, investment-plan CRUD, and pending-buy CRUD.

- [ ] **Step 1: Move watchlist-owned models, constants, helpers, and functions**

Replace re-exports with the exact implementations from the legacy module. Move these private symbols with their callers:

```python
_WATCHLIST_PATCH_FIELDS
_watchlist_to_dict
_investment_plan_to_dict
_pending_buy_to_dict
_patch_to_set
```

Import only the SQLAlchemy expressions and ORM models used by those functions. Preserve the existing `__all__` list.

- [ ] **Step 2: Move fund-owned models, helpers, and functions**

Replace re-exports with the exact implementations from the legacy module. Move these private symbols with their callers:

```python
_profile_to_dict
_tx_to_dict
_nav_to_dict
_fund_watchlist_profile_to_dict
```

Keep `upsert_fund_watchlist_profile` in `fund.py`, matching the approved design and current public domain API.

- [ ] **Step 3: Compile the two modules**

Run:

```bash
.venv/bin/python -m py_compile \
  backend/db/repositories/fund.py \
  backend/db/repositories/watchlist.py
```

Expected: exit code 0.

---

### Task 3: Move market and briefing implementations

**Files:**
- Modify: `backend/db/repositories/market.py`
- Modify: `backend/db/repositories/briefing.py`
- Source to delete later: `backend/db/repository.py:640-833`

**Interfaces:**
- Produces `market.py`: `upsert_market_snapshot`, `upsert_market_evidence`, and `search_market_evidence`.
- Produces `briefing.py`: `upsert_briefing`.

- [ ] **Step 1: Replace briefing re-export with its exact implementation**

Move the `Briefing` model import and `upsert_briefing` body unchanged. Keep:

```python
__all__ = ["upsert_briefing"]
```

- [ ] **Step 2: Replace market re-exports with exact implementations**

Move `_evidence_to_dict` together with the three public market functions. Preserve PostgreSQL upsert behavior, evidence deduplication, filters, ordering, and limit semantics.

- [ ] **Step 3: Compile the two modules**

Run:

```bash
.venv/bin/python -m py_compile \
  backend/db/repositories/briefing.py \
  backend/db/repositories/market.py
```

Expected: exit code 0.

---

### Task 4: Move knowledge and jobs implementations

**Files:**
- Modify: `backend/db/repositories/knowledge.py`
- Modify: `backend/db/repositories/jobs.py`
- Modify: `backend/db/repositories/__init__.py`
- Source to delete later: `backend/db/repository.py:834-1288,1336-1379`

**Interfaces:**
- Produces `knowledge.py`: CLS telegraph, classification state/log, knowledge document/source, queue status, and knowledge-fund match persistence.
- Produces `jobs.py`: `list_knowledge_reindex_jobs`.
- Produces package API: six domain modules only.

- [ ] **Step 1: Move knowledge helpers and functions**

Move these private helpers with the public functions that consume them:

```python
_json_loads
_cls_telegraph_to_dict
_cls_state_to_dict
_knowledge_document_to_dict
_classification_state_to_dict
_source_link_to_dict
_knowledge_fund_match_to_dict
```

Move the matching ORM imports and SQLAlchemy expressions. Remove `list_knowledge_reindex_jobs` from `knowledge.__all__`.

- [ ] **Step 2: Implement the jobs repository**

Move the existing query unchanged and expose it explicitly:

```python
from sqlalchemy import select

from backend.db.models import KnowledgeReindexJob


def list_knowledge_reindex_jobs(
    s,
    limit: int = 20,
) -> list[KnowledgeReindexJob]:
    """返回最近 N 条知识库重建任务,按 id 倒序。"""
    return list(s.scalars(
        select(KnowledgeReindexJob)
        .order_by(KnowledgeReindexJob.id.desc())
        .limit(max(1, int(limit)))
    ).all())


__all__ = ["list_knowledge_reindex_jobs"]
```

- [ ] **Step 3: Simplify the package initializer**

Keep only module exports:

```python
from backend.db.repositories import briefing, fund, jobs, knowledge, market, watchlist

__all__ = ["briefing", "fund", "jobs", "knowledge", "market", "watchlist"]
```

- [ ] **Step 4: Compile all repository modules**

Run:

```bash
.venv/bin/python -m compileall -q backend/db/repositories
```

Expected: exit code 0.

---

### Task 5: Migrate every consumer and delete the legacy module

**Files:**
- Modify: `backend/db/init_db.py`
- Modify: `backend/api/routes/watchlist.py`
- Modify: `backend/services/briefing/briefing_service.py`
- Modify: `backend/services/briefing/persistence.py`
- Modify: `backend/services/fund/fund_profile_service.py`
- Modify: `backend/services/fund/fund_service.py`
- Modify: `backend/services/fund/pnl_service.py`
- Modify: `backend/services/knowledge/cls_telegraph_sync_service.py`
- Modify: `backend/services/knowledge/knowledge_fund_profile_service.py`
- Modify: `backend/services/knowledge/knowledge_ingestion_service.py`
- Modify: `backend/services/knowledge/knowledge_match_service.py`
- Modify: `backend/services/knowledge/knowledge_reindex_jobs.py`
- Modify: `backend/services/knowledge/knowledge_search_service.py`
- Modify: `backend/services/market/market_evidence_ingestion.py`
- Modify: `backend/services/market/market_evidence_service.py`
- Modify: `backend/services/market/market_intel_service.py`
- Modify: `backend/services/shared/diagnosis_service.py`
- Modify: `backend/services/watchlist/transaction_service.py`
- Modify: `backend/services/watchlist/watchlist_preload_jobs.py`
- Modify: `backend/services/watchlist/watchlist_service.py`
- Modify: `backend/tests/test_api_funds.py`
- Modify: `backend/tests/test_api_portfolio.py`
- Modify: `backend/tests/test_api_watchlist.py`
- Modify: `backend/tests/test_cls_telegraph_sync_service.py`
- Modify: `backend/tests/test_diagnosis_service.py`
- Modify: `backend/tests/test_fund_service.py`
- Modify: `backend/tests/test_market_intel_service.py`
- Modify: `backend/tests/test_pnl.py`
- Modify: `backend/tests/test_portfolio_history.py`
- Modify: `backend/tests/test_repository.py`
- Modify: `backend/tests/test_transactions.py`
- Modify: `backend/tests/test_watchlist_fund_name.py`
- Modify: `backend/tests/test_watchlist_preload_jobs.py`
- Modify: `backend/tests/test_what_if_service.py`
- Delete: `backend/db/repository.py`

**Interfaces:**
- Consumes: six domain module APIs from Tasks 2–4.
- Produces: a repository with no importable legacy entry point.

- [ ] **Step 1: Replace module-style production imports by domain**

Use narrow aliases consistently:

```python
from backend.db.repositories import fund as fund_repo
from backend.db.repositories import watchlist as watchlist_repo
from backend.db.repositories import market as market_repo
from backend.db.repositories import knowledge as knowledge_repo
from backend.db.repositories import jobs as jobs_repo
```

Update every `repo.<function>` reference to the matching alias. A file using functions from multiple domains imports multiple domain modules rather than the package initializer as a facade.

- [ ] **Step 2: Replace direct function imports**

Examples:

```python
from backend.db.repositories.briefing import upsert_briefing
from backend.db.repositories.market import upsert_market_evidence
from backend.db.repositories.watchlist import backfill_watchlist_fund_names
```

Do not change caller signatures or control flow.

- [ ] **Step 3: Update tests and monkeypatch targets**

Tests that currently patch `repo.<name>` must import and patch the corresponding domain module. Split mixed repository tests only at the import level unless a test naturally needs two aliases:

```python
from backend.db.repositories import fund as fund_repo
from backend.db.repositories import watchlist as watchlist_repo
```

Preserve every assertion and fixture.

- [ ] **Step 4: Delete the legacy implementation**

Delete `backend/db/repository.py` only after all consumers compile.

- [ ] **Step 5: Run hard-cut contract and compile checks**

Run:

```bash
.venv/bin/pytest -q \
  backend/tests/test_repository_domain_contract.py \
  backend/tests/test_transaction_ownership_contract.py
.venv/bin/python -m compileall -q backend
rg -n 'backend\.db\.repository|from backend\.db import repository' \
  backend --glob '*.py'
```

Expected: tests PASS, compile exits 0, and `rg` returns no matches.

---

### Task 6: Run domain and full PostgreSQL regression

**Files:**
- Verify: all files changed in Tasks 1–5; do not add unrelated fixes.

**Interfaces:**
- Consumes: completed hard cut.
- Produces: verification evidence for the atomic implementation commit.

- [ ] **Step 1: Run focused repository and service tests**

Run:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/pytest -q \
  backend/tests/test_repository.py \
  backend/tests/test_transactions.py \
  backend/tests/test_api_funds.py \
  backend/tests/test_api_portfolio.py \
  backend/tests/test_api_watchlist.py \
  backend/tests/test_cls_telegraph_sync_service.py \
  backend/tests/test_diagnosis_service.py \
  backend/tests/test_fund_service.py \
  backend/tests/test_market_intel_service.py \
  backend/tests/test_pnl.py \
  backend/tests/test_portfolio_history.py \
  backend/tests/test_watchlist_fund_name.py \
  backend/tests/test_watchlist_preload_jobs.py \
  backend/tests/test_what_if_service.py
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run the complete backend suite**

Run:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/pytest -q backend/tests
```

Expected: no failures. Use a disposable database whose name ends in `_test` and whose worker schema can be dropped.

- [ ] **Step 3: Run final static gates**

Run:

```bash
.venv/bin/python -m compileall -q backend
git diff --check
rg -n 'backend\.db\.repository|from backend\.db import repository' \
  backend --glob '*.py'
git status --short
```

Expected: compile and diff checks pass, old-import search is empty, and status contains only planned implementation files.

- [ ] **Step 4: Review the complete diff**

Confirm that the diff contains only exact implementation moves, import/patch-target changes, the legacy deletion, and contract tests. Reject any SQL, function-signature, return-shape, or transaction-boundary change.

- [ ] **Step 5: Create the atomic implementation commit**

```bash
git add backend/db/repositories backend/db/repository.py backend/services \
  backend/api backend/tests backend/db/init_db.py
git commit -m "refactor: hard cut repositories by domain"
```

Expected: one implementation commit after all verification passes.
