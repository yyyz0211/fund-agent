# Knowledge pgvector Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Replace the unfinished Qdrant placeholder with PostgreSQL/pgvector persistence while fixing knowledge-pipeline transactions, idempotency, TTL, retry, stale matching, and frontend regression issues.

**Architecture:** Keep knowledge_documents as the source of truth, add a PostgreSQL-only knowledge_embeddings pgvector index behind VectorStoreAdapter, and use explicit structured fallback for SQLite or missing embedding configuration. Request routes own request transactions; services commit only when they create their own Session.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, PostgreSQL 16 + pgvector, SQLite fallback, LangChain OpenAI-compatible embeddings, pytest, Next.js 14, Node test runner.

## Global Constraints

- PostgreSQL uses pgvector; SQLite never requires or emulates the pgvector extension.
- Offline tests must not call a live LLM, embedding endpoint, PostgreSQL instance, or network service.
- Production code must never choose DeterministicEmbeddingProvider or InMemoryVectorStore automatically.
- Missing embedding configuration degrades to structured retrieval without preventing API startup.
- A document is indexed only when a persistent vector matches its current content hash, model, and version.
- Existing API response fields remain compatible; new health and warning fields are additive.
- Backend deployment remains restricted to one worker until distributed scheduling is designed separately.

---

## File Structure

- backend/api/deps.py: request-scoped Session lifecycle.
- backend/api/routes/knowledge.py: transaction ownership and validated inputs.
- backend/db/models.py and backend/db/repository.py: retry state and lifecycle queries.
- backend/db/init_db.py: PostgreSQL-only pgvector schema.
- backend/services/knowledge_embedding.py: embedding provider factory.
- backend/services/knowledge_pgvector.py: persistent vector adapter.
- backend/services/knowledge_vector.py: backend-neutral indexing transitions.
- backend/services/knowledge_search_service.py: hybrid retrieval and fallback.
- backend/services/knowledge_ingestion_service.py: classification idempotency.
- backend/services/knowledge_fund_profile_service.py and knowledge_match_service.py: set synchronization.
- backend/services/knowledge_reindex_jobs.py and backend/scheduler.py: observable jobs.
- backend/tests: offline and SQLite integration coverage.
- backend/tests/integration/test_pgvector_store.py: opt-in live pgvector coverage.
- docker-compose.yml and environment examples: deployment configuration.
- frontend briefing page and test: remove dead source anchor.
- README.md, backend/README.md, and DOCKER.md: operating documentation.

---

### Task 1: Correct request transactions and reindex visibility

**Files:**
- Modify: backend/api/deps.py
- Modify: backend/api/routes/knowledge.py
- Modify: backend/api/routes/market.py
- Modify: backend/api/routes/briefing.py
- Modify: backend/api/routes/cls.py
- Modify: backend/services/knowledge_reindex_jobs.py
- Test: backend/tests/test_knowledge_search_route.py
- Test: backend/tests/test_knowledge_reindex_jobs.py

**Interfaces:**
- Produces get_db_session() -> Iterator[Session], which rolls back on error and always closes.
- create_job accepts an external Session without committing it.
- The reindex route commits the pending row before starting its background thread.

- [ ] **Step 1: Write the failing API visibility test**

Add a temporary-file SQLite fixture, override get_db_session, and make the fake background function open a fresh Session:

    def test_knowledge_reindex_commits_job_before_background_start(monkeypatch, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path / 'reindex.db'}",
            connect_args={"check_same_thread": False},
        )
        init_db(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)

        def dependency():
            with sessions() as session:
                try:
                    yield session
                except Exception:
                    session.rollback()
                    raise

        seen = []
        def fake_background(job_id, *, pipeline_kwargs):
            with sessions() as check:
                seen.append(check.get(KnowledgeReindexJob, job_id) is not None)

        app.dependency_overrides[get_db_session] = dependency
        monkeypatch.setattr(
            route.knowledge_reindex_jobs,
            "run_job_in_background",
            fake_background,
        )
        try:
            response = TestClient(app).post(
                "/api/knowledge/reindex",
                headers={"X-Local-Trigger": "1"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202
        assert seen == [True]

- [ ] **Step 2: Run RED**

    .venv/bin/python -m pytest backend/tests/test_knowledge_search_route.py::test_knowledge_reindex_commits_job_before_background_start -v

Expected: FAIL because the worker starts before commit and the router uses the wrong dependency.

- [ ] **Step 3: Implement the dependency and route transaction**

    def get_db_session() -> Iterator[Session]:
        session = SessionLocal()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

Change every API route that currently declares Depends(get_session) to import and use get_db_session, including knowledge, market, briefing, and CLS routes. In reindex_knowledge:

    job = knowledge_reindex_jobs.create_job(trigger="manual", session=session)
    session.commit()
    job_id = int(job.id)
    knowledge_reindex_jobs.run_job_in_background(
        job_id,
        pipeline_kwargs=pipeline_kwargs,
    )

The search route commits only after the retrieval audit log was flushed successfully.

- [ ] **Step 4: Add dependency close/rollback tests**

Drive the dependency generator through success and exception with a fake Session. Assert close always occurs and rollback occurs on error.

- [ ] **Step 5: Run GREEN**

    .venv/bin/python -m pytest backend/tests/test_knowledge_search_route.py backend/tests/test_knowledge_reindex_jobs.py backend/tests/test_api_market.py backend/tests/test_briefing_route.py -q

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

    git add backend/api/deps.py backend/api/routes/knowledge.py backend/api/routes/market.py backend/api/routes/briefing.py backend/api/routes/cls.py backend/services/knowledge_reindex_jobs.py backend/tests/test_knowledge_search_route.py backend/tests/test_knowledge_reindex_jobs.py
    git commit -m "fix: commit knowledge jobs before background execution"

---

### Task 2: Make classification idempotent and bounded-retry

**Files:**
- Modify: backend/config/settings.py
- Modify: backend/db/models.py
- Modify: backend/db/repository.py
- Modify: backend/services/knowledge_ingestion_service.py
- Test: backend/tests/test_settings.py
- Test: backend/tests/test_knowledge_ingestion.py
- Test: backend/tests/test_knowledge_models.py

**Interfaces:**
- Produces should_classify_candidate(state, canonical_hash, prompt_version, now, max_attempts) -> tuple[bool, str].
- Adds counters skipped_unchanged and retry_deferred.
- Adds knowledge_classification_max_attempts=3 and knowledge_classification_retry_seconds=300.

- [ ] **Step 1: Write failing unchanged-content test**

    class CountingClassifier(StaticClassifier):
        def __init__(self, result):
            super().__init__(result)
            self.calls = 0

        def classify(self, candidate):
            self.calls += 1
            return super().classify(candidate)

    def test_ingest_skips_unchanged_candidate_with_same_prompt():
        engine = create_engine("sqlite:///:memory:")
        init_db(engine)
        classifier = CountingClassifier(accepted_result())
        candidate = {
            "source_type": "cls_telegraph",
            "source_id": "1",
            "title": "AI",
            "content": "same",
        }
        with Session(engine) as session:
            ingest_candidates([candidate], classifier=classifier, session=session)
            result = ingest_candidates([candidate], classifier=classifier, session=session)
        assert classifier.calls == 1
        assert result["skipped_unchanged"] == 1

Add a failed-state test at max attempts and assert the classifier is not called.

- [ ] **Step 2: Run RED**

    .venv/bin/python -m pytest backend/tests/test_knowledge_ingestion.py -k "skips_unchanged or max_attempts" -v

Expected: FAIL because every candidate is classified.

- [ ] **Step 3: Add retry columns and settings**

Add to KnowledgeClassificationState:

    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)

Add settings:

    knowledge_classification_max_attempts: int = 3
    knowledge_classification_retry_seconds: int = 300

Update repository serialization and upsert fields.

- [ ] **Step 4: Implement the pure decision function**

    def should_classify_candidate(state, canonical_hash, prompt_version, now, max_attempts):
        if state is None:
            return True, "new"
        unchanged = (
            state.canonical_content_hash == canonical_hash
            and state.prompt_version == prompt_version
        )
        if unchanged and state.status in {"accepted", "rejected"}:
            return False, "unchanged"
        if unchanged and state.status == "failed":
            if state.latest_attempt_no >= max_attempts:
                return False, "max_attempts"
            if state.next_retry_at and state.next_retry_at > now:
                return False, "retry_deferred"
        return True, "changed_or_retryable"

On failure, set last_attempt_at and next_retry_at. Success clears next_retry_at.

- [ ] **Step 5: Separate classification and index limits**

Candidate extraction uses knowledge_classification_batch_size. Vector indexing alone uses knowledge_index_batch_size.

- [ ] **Step 6: Run GREEN**

    .venv/bin/python -m pytest backend/tests/test_knowledge_ingestion.py backend/tests/test_knowledge_models.py backend/tests/test_settings.py -q

- [ ] **Step 7: Commit**

    git add backend/config/settings.py backend/db/models.py backend/db/repository.py backend/services/knowledge_ingestion_service.py backend/tests/test_settings.py backend/tests/test_knowledge_ingestion.py backend/tests/test_knowledge_models.py
    git commit -m "fix: make knowledge classification idempotent"

---

### Task 3: Enforce TTL and synchronize profiles and matches

**Files:**
- Modify: backend/services/knowledge_search_service.py
- Modify: backend/services/knowledge_fund_profile_service.py
- Modify: backend/services/knowledge_match_service.py
- Modify: backend/db/repository.py
- Test: backend/tests/test_knowledge_search_route.py
- Test: backend/tests/test_knowledge_fund_profiles.py
- Test: backend/tests/test_knowledge_fund_matches.py

**Interfaces:**
- Produces active_knowledge_predicate(now_text: str).
- Produces profile and match deletion helpers using target sets.

- [ ] **Step 1: Write failing TTL and invalid-date tests**

Create active and expired accepted documents and assert default search returns only the active one. Assert malformed date_from produces HTTP 422 and date_from later than date_to produces HTTP 400.

- [ ] **Step 2: Write failing stale-data tests**

Create two cached profiles with one Watchlist row; refresh and assert the removed profile is deleted. Seed a match whose score is now zero; refresh and assert deletion.

- [ ] **Step 3: Run RED**

    .venv/bin/python -m pytest backend/tests/test_knowledge_fund_profiles.py backend/tests/test_knowledge_fund_matches.py backend/tests/test_knowledge_search_route.py -k "expired or stale or invalid_date" -v

- [ ] **Step 4: Implement active filtering**

    def active_knowledge_predicate(now_text: str):
        return or_(
            KnowledgeDocument.effective_until.is_(None),
            KnowledgeDocument.effective_until >= now_text,
        )

Use date query types in the route and pass ISO strings to services.

- [ ] **Step 5: Implement set synchronization**

Collect target profile codes, upsert them, then delete rows not in the set. Treat an empty target as delete-all. Repeat the pattern for positive match keys and return matches_written plus matches_deleted.

- [ ] **Step 6: Enable fund_code filtering**

Remove the permanent fund_matching_enabled=False gate. No matches returns an empty result rather than HTTP 400. Replace the old rejection test.

- [ ] **Step 7: Run GREEN**

    .venv/bin/python -m pytest backend/tests/test_knowledge_fund_profiles.py backend/tests/test_knowledge_fund_matches.py backend/tests/test_knowledge_search_route.py -q

- [ ] **Step 8: Commit**

    git add backend/services/knowledge_search_service.py backend/services/knowledge_fund_profile_service.py backend/services/knowledge_match_service.py backend/db/repository.py backend/tests/test_knowledge_search_route.py backend/tests/test_knowledge_fund_profiles.py backend/tests/test_knowledge_fund_matches.py
    git commit -m "fix: expire knowledge and remove stale fund matches"

---

### Task 4: Add pgvector configuration and PostgreSQL-only schema

**Files:**
- Modify: backend/config/settings.py
- Modify: backend/db/init_db.py
- Create: backend/tests/test_knowledge_pgvector_schema.py
- Modify: backend/tests/test_settings.py
- Modify: docker-compose.yml
- Modify: .env.example
- Modify: backend/.env.example
- Modify: backend/requirements.txt

**Interfaces:**
- Produces ensure_pgvector_schema(engine: Engine, dimensions: int | None) -> bool.
- Backend values are auto, pgvector, and structured.

- [ ] **Step 1: Write failing config and SQLite no-op tests**

    def test_vector_backend_defaults_to_auto():
        assert Settings(_env_file=None).knowledge_vector_backend == "auto"

    def test_pgvector_schema_is_noop_for_sqlite():
        engine = create_engine("sqlite:///:memory:")
        assert ensure_pgvector_schema(engine, dimensions=16) is False
        assert "knowledge_embeddings" not in inspect(engine).get_table_names()

- [ ] **Step 2: Run RED**

    .venv/bin/python -m pytest backend/tests/test_settings.py backend/tests/test_knowledge_pgvector_schema.py -v

- [ ] **Step 3: Add safe settings**

    knowledge_vector_backend: Literal["auto", "pgvector", "structured"] = "auto"
    knowledge_embedding_base_url: Optional[str] = None
    knowledge_embedding_api_key: Optional[str] = None
    knowledge_embedding_model: Optional[str] = None
    knowledge_embedding_version: Optional[str] = None
    knowledge_embedding_dimensions: Optional[int] = None

Validate positive dimensions when supplied. Never reuse DeepSeek settings implicitly.

- [ ] **Step 4: Implement PostgreSQL-only DDL**

    def ensure_pgvector_schema(engine, dimensions):
        if engine.dialect.name != "postgresql" or not dimensions:
            return False
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS knowledge_embeddings ("
                "document_id BIGINT PRIMARY KEY REFERENCES knowledge_documents(id) ON DELETE CASCADE,"
                "embedding vector(" + str(int(dimensions)) + ") NOT NULL,"
                "embedding_model VARCHAR NOT NULL,"
                "embedding_version VARCHAR NOT NULL,"
                "content_hash VARCHAR(64) NOT NULL,"
                "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_knowledge_embeddings_cosine "
                "ON knowledge_embeddings USING hnsw (embedding vector_cosine_ops)"
            ))
        return True

Validate any existing vector dimension and raise a clear migration error on mismatch.

- [ ] **Step 5: Update deployment**

Change image to pgvector/pgvector:pg16, default backend to auto, add five embedding variables, and remove qdrant-client.

- [ ] **Step 6: Run GREEN and Compose validation**

    .venv/bin/python -m pytest backend/tests/test_settings.py backend/tests/test_knowledge_pgvector_schema.py backend/tests/test_models.py -q
    docker compose config --quiet

- [ ] **Step 7: Commit**

    git add backend/config/settings.py backend/db/init_db.py backend/tests/test_settings.py backend/tests/test_knowledge_pgvector_schema.py docker-compose.yml .env.example backend/.env.example backend/requirements.txt
    git commit -m "feat: add PostgreSQL pgvector knowledge schema"

---

### Task 5: Implement embedding and pgvector adapters

**Files:**
- Create: backend/services/knowledge_embedding.py
- Create: backend/services/knowledge_pgvector.py
- Modify: backend/services/knowledge_vector.py
- Create: backend/tests/test_knowledge_embedding.py
- Create: backend/tests/test_knowledge_pgvector.py
- Create: backend/tests/integration/test_pgvector_store.py

**Interfaces:**
- Produces build_embedding_provider(settings) -> EmbeddingProvider | None.
- Produces build_vector_store(session, settings) -> VectorStoreAdapter | None.
- PgVectorStore implements upsert, search, and delete.

- [ ] **Step 1: Write failing factory tests**

Incomplete configuration and structured mode return None. Complete PostgreSQL settings construct provider/store without network calls.

- [ ] **Step 2: Write failing SQL tests**

With a recording Session, assert upsert uses ON CONFLICT, search uses cosine operator, delete is parameterized, and vector values never appear in SQL text.

- [ ] **Step 3: Run RED**

    .venv/bin/python -m pytest backend/tests/test_knowledge_embedding.py backend/tests/test_knowledge_pgvector.py -v

- [ ] **Step 4: Implement embedding provider**

    class OpenAICompatibleEmbeddingProvider:
        def __init__(self, *, model, version, dimensions, api_key, base_url):
            self.model = model
            self.version = version
            self.dimensions = dimensions
            self._client = OpenAIEmbeddings(
                model=model,
                api_key=api_key,
                base_url=base_url,
                dimensions=dimensions,
            )

        def embed(self, texts):
            vectors = self._client.embed_documents(texts)
            if len(vectors) != len(texts):
                raise ValueError("embedding response count mismatch")
            if any(len(vector) != self.dimensions for vector in vectors):
                raise ValueError("embedding response dimension mismatch")
            return vectors

Construction is lazy; import never performs a request.

- [ ] **Step 5: Implement parameterized PgVectorStore**

Serialize vectors at the DB boundary:

    def vector_literal(values):
        return "[" + ",".join(format(float(value), ".12g") for value in values) + "]"

Use CAST(:embedding AS vector). Search joins knowledge_documents so filters and TTL remain authoritative.

- [ ] **Step 6: Add opt-in integration test**

Mark it pgvector and skip unless TEST_PGVECTOR_DATABASE_URL exists. Initialize schema, insert vectors, test ordering/filtering, and roll back cleanup.

- [ ] **Step 7: Run GREEN**

    .venv/bin/python -m pytest backend/tests/test_knowledge_embedding.py backend/tests/test_knowledge_pgvector.py backend/tests/test_knowledge_vector.py -q

- [ ] **Step 8: Commit**

    git add backend/services/knowledge_embedding.py backend/services/knowledge_pgvector.py backend/services/knowledge_vector.py backend/tests/test_knowledge_embedding.py backend/tests/test_knowledge_pgvector.py backend/tests/integration/test_pgvector_store.py
    git commit -m "feat: implement pgvector knowledge adapter"

---

### Task 6: Add retryable indexing and hybrid retrieval

**Files:**
- Modify: backend/db/models.py
- Modify: backend/db/repository.py
- Modify: backend/services/knowledge_vector.py
- Modify: backend/services/knowledge_search_service.py
- Modify: backend/tests/test_knowledge_vector.py
- Create: backend/tests/test_knowledge_search_service.py

**Interfaces:**
- Adds index_attempts, last_index_error, and next_index_retry_at.
- Produces merge_hybrid_candidates(..., limit) with post-merge limiting.

- [ ] **Step 1: Write failing retry test**

Use a store that fails once. Assert failed state and retry metadata, advance now, retry, then assert indexed with cleared errors.

- [ ] **Step 2: Write failing hybrid merge test**

Structured IDs are 1 and 2, vector IDs are 2 and 3, and fund match boosts 3. Assert unique output and limit after scoring.

- [ ] **Step 3: Run RED**

    .venv/bin/python -m pytest backend/tests/test_knowledge_vector.py backend/tests/test_knowledge_search_service.py -v

- [ ] **Step 4: Add index retry fields**

    index_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_index_error: Mapped[Optional[str]] = mapped_column(String)
    next_index_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)

Select pending plus retryable failed documents. Success clears retry state.

- [ ] **Step 5: Resolve runtime safely**

    provider = embedding_provider or build_embedding_provider(settings)
    store = vector_store or build_vector_store(session, settings)
    vector_available = provider is not None and store is not None

Unavailable vector runtime skips indexing without marking indexed.

- [ ] **Step 6: Implement hybrid search**

Fetch an expanded structured window, query pgvector when available and query is non-empty, union by document_id, score after union, then apply limit. On provider/store errors return structured_fallback with a warning and no fake semantic score.

- [ ] **Step 7: Run GREEN**

    .venv/bin/python -m pytest backend/tests/test_knowledge_vector.py backend/tests/test_knowledge_search_service.py backend/tests/test_knowledge_search_route.py -q

- [ ] **Step 8: Commit**

    git add backend/db/models.py backend/db/repository.py backend/services/knowledge_vector.py backend/services/knowledge_search_service.py backend/tests/test_knowledge_vector.py backend/tests/test_knowledge_search_service.py
    git commit -m "feat: add retryable hybrid knowledge retrieval"

---

### Task 7: Observe scheduled jobs and recover interrupted jobs

**Files:**
- Modify: backend/db/models.py
- Modify: backend/db/repository.py
- Modify: backend/services/knowledge_reindex_jobs.py
- Modify: backend/scheduler.py
- Modify: backend/api/app.py
- Test: backend/tests/test_knowledge_reindex_jobs.py
- Test: backend/tests/test_scheduler.py

**Interfaces:**
- Produces recover_interrupted_jobs(older_than_seconds: int) -> int.
- Scheduled runs create the same job records as manual runs.

- [ ] **Step 1: Write failing tests**

Seed old pending/running jobs and one fresh job. Recovery marks only old rows interrupted. Invoke scheduled knowledge callable and assert a scheduled job reaches completed.

- [ ] **Step 2: Run RED**

    .venv/bin/python -m pytest backend/tests/test_knowledge_reindex_jobs.py backend/tests/test_scheduler.py -k "interrupted or scheduled_job_record" -v

- [ ] **Step 3: Implement recovery**

Add interrupted terminal status and knowledge_job_stale_seconds=3600. Update only stale pending/running jobs with finished_at and a bounded error.

- [ ] **Step 4: Wrap scheduled pipeline**

Create and commit a scheduled job, acquire the existing process lock, mark running, execute, then mark completed/failed. Busy lock marks busy_skipped.

- [ ] **Step 5: Recover during startup**

Call recovery after init_db and before scheduler start. Log recovery errors without blocking API startup.

- [ ] **Step 6: Run GREEN**

    .venv/bin/python -m pytest backend/tests/test_knowledge_reindex_jobs.py backend/tests/test_scheduler.py backend/tests/test_api_app.py -q

- [ ] **Step 7: Commit**

    git add backend/db/models.py backend/db/repository.py backend/services/knowledge_reindex_jobs.py backend/scheduler.py backend/api/app.py backend/tests/test_knowledge_reindex_jobs.py backend/tests/test_scheduler.py
    git commit -m "fix: recover and observe knowledge pipeline jobs"

---

### Task 8: Remove frontend anchors and document operating modes

**Files:**
- Modify: frontend/app/briefing/page.tsx
- Modify: frontend/tests/market-evidence-ui.test.mjs
- Modify: README.md
- Modify: backend/README.md
- Modify: DOCKER.md

- [ ] **Step 1: Change the failing test first**

    test("briefing page renders evidence quality beside latest brief", async () => {
      const page = await read("../app/briefing/page.tsx");
      assert.match(page, /api\.marketEvidence/);
      assert.match(page, /证据条数/);
      assert.match(page, /数据质量/);
      assert.doesNotMatch(page, /_evidence_api_ref/);
    });

- [ ] **Step 2: Run RED**

    node --test frontend/tests/market-evidence-ui.test.mjs

Expected: FAIL because the dead anchor remains.

- [ ] **Step 3: Remove dead page code**

Delete _evidence_api_ref and its unreachable guard. Keep the real API call and 证据条数 UI.

- [ ] **Step 4: Document exact modes**

Document the pgvector image, five embedding variables, safe structured fallback, model/version reindex, dimension rebuild, and single-worker constraint.

- [ ] **Step 5: Run GREEN**

    cd frontend
    npm test
    npm run build

- [ ] **Step 6: Commit**

    git add frontend/app/briefing/page.tsx frontend/tests/market-evidence-ui.test.mjs README.md backend/README.md DOCKER.md
    git commit -m "docs: explain pgvector and structured fallback modes"

---

### Task 9: Complete verification

**Files:**
- Modify only if a verification failure reveals a defect in the preceding task.

- [ ] **Step 1: Syntax and diff checks**

    git diff --check
    .venv/bin/python -m compileall -q backend

- [ ] **Step 2: Complete backend suite**

    .venv/bin/python -m pytest backend/tests -q

Expected: all offline tests pass; live pgvector test skips unless configured.

- [ ] **Step 3: Complete frontend suite and build**

    cd frontend
    npm test
    npm run build

- [ ] **Step 4: Compose validation**

    docker compose config --quiet

- [ ] **Step 5: Optional live pgvector integration**

    TEST_PGVECTOR_DATABASE_URL=postgresql+psycopg2://... .venv/bin/python -m pytest backend/tests/integration/test_pgvector_store.py -m pgvector -v

Expected: extension, upsert, cosine search, filtering, and cascade tests pass.

- [ ] **Step 6: Re-run original transaction reproduction**

The API test must prove POST /reindex creates a row visible to a fresh Session before background execution. The previous 202 response followed by get_job(None) must no longer occur.

- [ ] **Step 7: Inspect final scope**

    git status --short
    git diff --check

Report pre-existing changes separately. Never reset or discard them.

---

## Plan Self-Review

- Every approved design acceptance criterion maps to a task.
- PostgreSQL behavior has offline unit boundaries and an opt-in live integration test.
- SQLite never imports or initializes pgvector.
- Embedding configuration is independent from DeepSeek chat settings.
- Transaction ownership is explicit.
- Classification, TTL, matching, vector retry, and hybrid retrieval each have RED/GREEN cycles.
- No task queue, distributed lock, Alembic migration, or authentication work was added beyond the approved scope.
