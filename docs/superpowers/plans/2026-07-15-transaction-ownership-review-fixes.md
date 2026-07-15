# Transaction Ownership Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the Phase 1.2 transaction ownership regressions while preserving externally injected SQLAlchemy sessions and keeping network, LLM, and embedding calls outside active database transactions.

**Architecture:** Public services own a transaction only when `session=None`; injected sessions are flush-only. Slow external work is performed before any SQL transaction, followed by focused read/write helpers and short `session_scope()` blocks.

**Tech Stack:** Python, SQLAlchemy 2.x, PostgreSQL, pytest, AST contract tests.

## Global Constraints

- PostgreSQL is the only runtime and test database; do not add SQLite branches or fixtures.
- Repository functions may flush but never commit, rollback, or close a session.
- Services must not commit, rollback, or close an injected session.
- Preserve existing API response schemas and business calculations.
- Keep genuine multi-table operations atomic at the outer transaction boundary.

---

### Task 1: Watchlist Transaction Ownership and AST Contract

**Files:**
- Modify: `backend/services/watchlist/transaction_service.py`
- Modify: `backend/services/watchlist/watchlist_service.py`
- Modify: `backend/tests/test_transaction_ownership_contract.py`
- Test: `backend/tests/test_transactions.py`

**Interfaces:**
- Produces: `recalc_holding(fund_code: str, session=None) -> dict | None`, with no `commit` argument.
- Produces: watchlist write services that flush injected sessions and rely on the outer owner to commit.

- [ ] **Step 1: Write failing regression tests**

Add a recording-session or PostgreSQL rollback test proving that `recalc_holding`, `add_transaction`, `remove_transaction`, `set_initial_holding`, and `confirm_pending_buy` do not call commit on an injected session. Change the AST contract so a non-whitelisted function in any service file is scanned rather than skipping the file.

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest -q backend/tests/test_transaction_ownership_contract.py backend/tests/test_transactions.py`

Expected: failure reporting watchlist/transaction service commit calls or unexpected persistence after rollback.

- [ ] **Step 3: Implement flush-only ownership**

Replace the current body shape with:

```python
def recalc_holding(fund_code: str, session=None) -> dict | None:
    if session is None:
        with session_scope() as s:
            return _recalc_holding_impl(s, fund_code)
    return _recalc_holding_impl(session, fund_code)
```

Move the calculation into `_recalc_holding_impl`, call `session.flush()` after mutations, remove `commit` parameters and explicit watchlist commits, and make the AST contract reject any `.commit()`, `.rollback()`, or `.close()` inside service/repository functions without whole-file skips.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `pytest -q backend/tests/test_transaction_ownership_contract.py backend/tests/test_transactions.py`

Expected: all collected tests pass with no watchlist file skips.

### Task 2: Fund Refresh Session Compatibility

**Files:**
- Modify: `backend/services/fund/fund_service.py`
- Modify: `backend/services/fund/fund_profile_service.py`
- Test: `backend/tests/test_fund_service.py`
- Test: `backend/tests/test_fund_profile_service.py`

**Interfaces:**
- Produces: `refresh_fund(fund_code: str, session=None) -> dict`.
- Produces: `refresh_profile(fund_code: str, session=None) -> dict`.

- [ ] **Step 1: Extend tests to assert injected-session behavior**

Use the existing PostgreSQL `session` fixture and monkeypatched collectors. Assert the refresh functions accept `session=`, return the existing payload, and leave commit ownership to the fixture/caller.

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest -q backend/tests/test_fund_service.py backend/tests/test_fund_profile_service.py`

Expected: `TypeError` for the removed `session` keyword once the PostgreSQL test environment is active.

- [ ] **Step 3: Restore the optional session and isolate writes**

Implement a pure write helper for each service:

```python
if session is not None:
    result = _persist_refresh(session, fund_code, payload)
else:
    with session_scope() as s:
        result = _persist_refresh(s, fund_code, payload)
```

Collectors must run before either branch. Helpers may call repository functions and flush but do not commit.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `pytest -q backend/tests/test_fund_service.py backend/tests/test_fund_profile_service.py`

Expected: all tests pass under the PostgreSQL fixture.

### Task 3: Knowledge Slow-Call Transaction Separation

**Files:**
- Modify: `backend/services/knowledge/knowledge_ingestion_service.py`
- Modify: `backend/services/knowledge/knowledge_search_service.py`
- Test: `backend/tests/test_knowledge_ingestion.py`
- Test: `backend/tests/test_knowledge_search_service.py`

**Interfaces:**
- Preserves: `ingest_candidates(candidates, *, classifier=None, session=None) -> dict`.
- Preserves: `search_knowledge(..., session=None, vector_store=None, embedding_provider=None) -> dict`.

- [ ] **Step 1: Write transaction-state regression tests**

Add classifiers/providers that assert their callback runs before the owning service starts SQL. For ingestion, cover state read, classification, state revalidation, and result write. For search, assert embedding occurs before match/document queries and preserve structured fallback on provider failure.

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest -q backend/tests/test_knowledge_ingestion.py backend/tests/test_knowledge_search_service.py`

Expected: classifier/provider observes an active transaction or SQL recorded before the slow callback.

- [ ] **Step 3: Split ingestion into short-read / classify / short-write phases**

Read the batch state in a short transaction, close it, classify the entire batch, then start persistence. Re-read each state in the write phase and skip stale work when the latest state no longer permits the attempted classification. An injected session is used only after all LLM callbacks finish, so the first write cannot keep its transaction open during later classifications.

- [ ] **Step 4: Move query embedding before session creation**

Build the embedding provider and compute `query_vector` before opening an owned session. Pass the computed vector into `_fetch_search_results`; that helper performs only SQL/vector-store work. Keep retrieval logging in a separate write transaction for owned calls.

- [ ] **Step 5: Run the tests and verify GREEN**

Run: `pytest -q backend/tests/test_knowledge_ingestion.py backend/tests/test_knowledge_search_service.py`

Expected: all tests pass and fallback behavior remains unchanged.

### Task 4: Market Snapshot Cache-Miss Boundary

**Files:**
- Modify: `backend/services/market/market_intel_service.py`
- Test: `backend/tests/test_market_intel_service.py`

**Interfaces:**
- Preserves: `get_market_snapshot(trade_date=None, snapshot_type="post_market", session=None) -> dict`.

- [ ] **Step 1: Write a failing cache-miss test**

Record the session passed to `collect_market_intel`. For an owned cache lookup miss, assert collection happens after the lookup context closes and receives no queried session. For an injected-session miss, assert collection does not reuse that session.

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest -q backend/tests/test_market_intel_service.py::test_get_market_snapshot_cache_miss_does_not_reuse_query_session`

Expected: collector receives the already queried session.

- [ ] **Step 3: Separate cached read from refresh**

Extract a cache-row serialization helper. End the owned lookup context before calling `collect_market_intel(td, snapshot_type)` without a session. The external-session miss path must likewise avoid passing the queried session to network collection.

- [ ] **Step 4: Run market tests and verify GREEN**

Run: `pytest -q backend/tests/test_market_intel_routes.py backend/tests/test_market_qa_tools.py backend/tests/test_market_intel_service.py`

Expected: all tests pass.

### Task 5: Documentation and Final Verification

**Files:**
- Modify: `docs/superpowers/decisions/0002-transaction-ownership.md`
- Modify: relevant Phase 1.2 ledger/review report if it contains obsolete skip counts or follow-ups.

**Interfaces:**
- Produces documentation matching the enforced transaction contract and actual test state.

- [ ] **Step 1: Update ADR and progress records**

Remove whole-file whitelist claims, the known refresh signature failure, and inaccurate statements that slow calls are already outside transactions. Record the new exact contract and verification commands.

- [ ] **Step 2: Run focused verification**

Run:

```bash
pytest -q \
  backend/tests/test_transaction_ownership_contract.py \
  backend/tests/test_session_scope.py \
  backend/tests/test_api_deps.py \
  backend/tests/test_transactions.py \
  backend/tests/test_fund_service.py \
  backend/tests/test_fund_profile_service.py \
  backend/tests/test_knowledge_ingestion.py \
  backend/tests/test_knowledge_search_service.py
```

Expected: zero failures under the configured PostgreSQL/Python environment.

- [ ] **Step 3: Run repository checks**

Run `git diff --check`, inspect `git diff --stat` and `git diff`, then run the broadest PostgreSQL-backed test command supported by the workspace. Record any unrelated environment or baseline failures separately rather than masking them.
