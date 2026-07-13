# Knowledge Stabilization Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the runtime gaps left after the pgvector stabilization work without expanding beyond the current single-worker architecture.

**Architecture:** Keep the existing request/session, scheduler lock, and vector adapter boundaries. Make tests hermetic, make interval jitter effective, requeue stale indexed documents, expose additive health details, and add an explicit confirmed vector-table rebuild operation.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, APScheduler 3.x, PostgreSQL 16 + pgvector, SQLite, pytest, Next.js 14.

## Global Constraints

- Preserve existing API fields; health fields are additive.
- Do not call external LLM, embedding, PostgreSQL, or network services in default tests.
- Do not introduce Celery, Redis, Alembic, authentication, or multi-worker scheduling.
- Ordinary reindex must never drop the vector table.
- Test cleanup may delete only clearly identified never-started test jobs.
- The user approved regression tests without a strict RED/GREEN TDD cycle for this small follow-up.

---

### Task 1: Isolate reindex route tests and clean test residue

**Files:**
- Modify: `backend/tests/test_knowledge_search_route.py`
- Modify: `backend/tests/conftest.py` if a shared isolated database fixture is required
- Data: `backend/data/fund_agent.db`

**Interfaces:**
- Test requests override `backend.api.deps.get_db_session` with a temporary SQLite session factory.
- Cleanup targets only `KnowledgeReindexJob(trigger="manual", status="pending", started_at=None, finished_at=None, result_json=None, error_message=None)` records attributable to test executions.

- [ ] Update the local-trigger route test to use a temporary database dependency.
- [ ] Run `backend/tests/test_knowledge_search_route.py` twice and verify the development database job count does not change.
- [ ] Inspect candidate pending rows, delete only confirmed test residue, and report deleted IDs.

### Task 2: Fix scheduler jitter and first-run collision

**Files:**
- Modify: `backend/scheduler.py`
- Modify: `backend/tests/test_scheduler.py`

**Interfaces:**
- `_interval_trigger(minutes, tz, *, jitter=0, start_delay_seconds=0) -> IntervalTrigger`
- `_seconds_interval_trigger(seconds, tz, *, jitter=0, start_delay_seconds=0) -> IntervalTrigger`

- [ ] Pass jitter into `IntervalTrigger` construction.
- [ ] Give the knowledge pipeline a deterministic first-run offset from CLS sync.
- [ ] Remove ineffective `jitter=` arguments from `add_job()` calls using trigger objects.
- [ ] Add assertions for trigger jitter and different start dates.
- [ ] Run scheduler tests.

### Task 3: Requeue stale indexed documents and reset classification attempts

**Files:**
- Modify: `backend/services/knowledge_vector.py`
- Modify: `backend/services/knowledge_ingestion_service.py`
- Modify: `backend/tests/test_knowledge_vector.py`
- Modify: `backend/tests/test_knowledge_ingestion.py`

**Interfaces:**
- Index selection treats model/version mismatch as work even when `index_status="indexed"`.
- `_next_attempt_no(state, canonical_hash, prompt_version) -> int` resets on content or prompt changes.

- [ ] Extend vector selection with provider model/version mismatch predicates.
- [ ] Keep successful upsert and document status updates in the same transaction.
- [ ] Reset classification attempt numbering when canonical hash changes.
- [ ] Add regression tests and run the two test modules.

### Task 4: Add explicit vector rebuild and additive health

**Files:**
- Modify: `backend/db/init_db.py`
- Modify: `backend/api/app.py`
- Modify: `backend/api/routes/knowledge.py`
- Modify: `backend/services/knowledge_pgvector.py` or create a focused health helper if needed
- Modify: `backend/tests/test_knowledge_pgvector_schema.py`
- Modify: `backend/tests/test_api_app.py`
- Modify: `backend/tests/test_knowledge_search_route.py`

**Interfaces:**
- `rebuild_pgvector_schema(engine, dimensions, *, confirmed: bool) -> int` drops and recreates only `knowledge_embeddings`, then marks knowledge documents pending.
- `POST /api/knowledge/vector-schema/rebuild?confirm=true` is protected by `X-Local-Trigger` and returns the number of requeued documents.
- `/api/health` keeps `status` and adds local-only component details without remote calls.

- [ ] Implement confirmed PostgreSQL-only rebuild with a single transaction.
- [ ] Add the protected management route; reject absent confirmation or trigger.
- [ ] Implement database/vector/scheduler health snapshots.
- [ ] Add SQLite/offline tests and optional PostgreSQL integration coverage.
- [ ] Correct DOCKER documentation for model/version and dimension changes.

### Task 5: Complete verification

**Files:**
- Modify only if verification exposes a defect.

- [ ] Run `git diff --check` and `.venv/bin/python -m compileall -q backend`.
- [ ] Run `.venv/bin/python -m pytest -q` and report pass/skip/warning counts.
- [ ] Run `npm test` and `npm run build` in `frontend/`.
- [ ] Run the optional live pgvector test only when `TEST_PGVECTOR_DATABASE_URL` exists.
- [ ] Run `docker compose config --quiet` only if Docker is installed.
- [ ] Confirm `git status` contains no unintended files and that the original staged plan remains preserved.

