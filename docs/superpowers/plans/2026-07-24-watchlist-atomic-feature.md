# Atomic Watchlist Entry Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把普通“新增自选”改为一个原子、提交后才派发预热任务的纵向切片，并让前端通过唯一 HTTP transport、Feature API 和服务端确认后的缓存更新消费该行为。

**Architecture:** PostgreSQL Repository 用 `INSERT ... ON CONFLICT DO NOTHING RETURNING` 提供原子 create-if-absent；Watchlist Application 拥有事务和提交后副作用；Route 只做协议映射；前端 Watchlist Feature 拥有 add/preload DTO、mutation、polling 和跨资源缓存效果，现有全局 API 与 Feature 共用一个类型化 transport。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2、PostgreSQL、pytest、Next.js 14、React 18、TypeScript strict、TanStack React Query 5、Vitest、React Testing Library、jsdom。

## Global Constraints

- 先完成 `2026-07-24-scheduler-akshare-safety.md`；其完整 unit partition
  未通过前不得开始本计划。
- 保持公开路径 `POST /api/watchlist`、HTTP 200 和现有成功字段。内部 `created` 不得进入 JSON。
- 首次添加只创建一行，且只在事务成功提交后派发一次 preload；重复添加返回第一次数据，不用新 payload 覆盖。
- `is_holding=None` 与 `is_focus=None` 不得显式写入非空列；Repository 必须让模型/数据库默认值 `False` 生效。
- Repository 只 flush，不 commit/rollback/close。Route 不访问 Repository、Session、ORM 或 preload adapter。
- Application 可以直接使用现有 `session_scope()`；本切片不创建通用 UoW、Command Bus、DI 容器或泛型 Repository。
- preload pending 写入失败时，未公开的 job snapshot 和 active claim 必须删除；executor submit 失败时，已公开的 snapshot 和 DB 状态必须尽力收敛为 `failed`，并释放 claim。
- preload 派发失败不回滚已经提交的 Watchlist；HTTP 仍返回 200、已提交行和响应语义
  `preload_status=failed`，不返回不存在的 `preload_job`。即使 pending 写或 failed-cleanup
  写本身失败，Application 也使用已提交的 row 构造这一响应，不再依赖第二次数据库读取；
  持久化状态仍由 preload adapter 尽力收敛。
- Graph/fund 兼容调用继续使用 `watchlist_service`；initial-holding、edit、transaction、investment plan、pending buy 均不迁移。
- 前端普通 add 与 preload 才进入 Feature。initial-holding 和 edit 继续使用全局 `api`。
- confirmed cache update 发生在服务端成功响应后，不是 optimistic update。失败时不得修改 cache。
- cache `undefined` 与已初始化空数组 `[]` 必须区分：前者只 invalidate，后者可以 append。
- preload 保持 1.5 秒间隔、最多 120 次、`retry=false`、后台 tab 继续、Drawer 关闭继续、宿主卸载停止。
- 不创建通用 `settleMembershipChange()`；本切片只允许动作级 `applyAddSucceeded()` 与 `applyPreloadTerminal()`。
- 现有全局 `api.ts` 与新 Watchlist Feature 必须在同一提交切到 `http.ts`；不得保留两套 fetch/error parser。
- 只为本 Feature 引入 Vitest/RTL；现有 `.mjs` Node tests 保持，并只删除当前 Feature 内等价的源码形状断言。
- `tsc --noEmit` 与 `next build` 串行运行，避免同时写 `.next/types`。
- Repository primitive、Application 和首个 Route 调用方必须在同一个
  backend vertical-slice commit 接通；不得提交暂时没有生产调用方的空边界。
- 每个 checkpoint 的 `git diff --cached --name-status` 必须只包含该命令后
  明确列出的路径；出现额外路径时停止提交。所有 checkpoint 使用
  `git commit --only -- <exact paths>`，不得消费并行存在的用户暂存修改。

---

## File Map

**Create — backend**

- `backend/application/__init__.py`
- `backend/application/watchlist/__init__.py`
- `backend/application/watchlist/add_entry.py`
- `backend/tests/test_watchlist_preload_dispatch.py`
- `backend/tests/test_watchlist_add_entry.py`
- `backend/tests/test_watchlist_atomic_repository.py`
- `backend/tests/test_watchlist_slice_contract.py`

**Modify — backend**

- `backend/services/watchlist/watchlist_preload_jobs.py`
- `backend/db/repositories/watchlist.py`
- `backend/api/routes/watchlist.py`
- `backend/tests/test_api_watchlist.py`
- `docs/superpowers/decisions/0002-transaction-ownership.md`

**Create — frontend**

- `frontend/src/lib/http.ts`
- `frontend/src/features/watchlist/contracts.ts`
- `frontend/src/features/watchlist/api.ts`
- `frontend/src/features/watchlist/use-add-entry.ts`
- `frontend/src/features/watchlist/use-preload-job.ts`
- `frontend/src/features/watchlist/index.ts`
- `frontend/vitest.config.ts`
- `frontend/tests/vitest.setup.ts`
- `frontend/tests/http.test.ts`
- `frontend/tests/watchlist-contracts.test.ts`
- `frontend/tests/watchlist-add.test.tsx`
- `frontend/tests/watchlist-preload.test.tsx`
- `frontend/tests/transport-consumers.test.ts`
- `.github/workflows/frontend-tests.yml`

**Modify — frontend**

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/src/lib/api.ts`
- `frontend/src/types/api.ts`
- `frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts`
- `frontend/src/components/watchlist-drawer/WatchlistDrawer.tsx`
- `frontend/tests/api-client.test.mjs`
- `frontend/tests/watchlist-drawer-structure.test.mjs`

**Delete — frontend**

- `frontend/src/components/watchlist-drawer/hooks/useWatchlistPreloadPolling.ts`

**Do not modify**

- `backend/services/watchlist/watchlist_service.py`
- Initial-holding、transaction、investment-plan、pending-buy 的后端接口和前端 Feature 归属。
- 全局 Query key 值、polling interval/max-attempt 常量。
- 其他前端领域 DTO 或页面。

---

### Task 1: Record the slice baseline

**Files:**

- Inspect: backend and frontend files in the File Map.

- [ ] **Step 1: Confirm the prerequisite and worktree boundary**

Run:

```bash
git status --short
if rg -n \
  'async def (start_scheduler|shutdown_scheduler)|await .*start_scheduler|await .*shutdown_scheduler|asyncio\.to_thread' \
  backend/scheduler backend/api/app.py; then
  echo "Scheduler safety prerequisite is incomplete"
  exit 1
fi

if rg -n \
  'ThreadPoolExecutor|future\.result|cancel_futures|_PROFILE_FETCH_WORKERS|_PROFILE_SOURCE_TIMEOUT_SECONDS|_REFRESH_FETCH_WORKERS' \
  backend/services/fund/fund_service.py \
  backend/services/market/data_collector.py; then
  echo "AkShare fan-out safety prerequisite is incomplete"
  exit 1
fi

if rg -n \
  'SIGALRM|setitimer|_with_retry_and_timeout|multiprocessing|ProcessPoolExecutor' \
  backend/services/market/data_collector.py; then
  echo "AkShare timeout safety prerequisite is incomplete"
  exit 1
fi
```

Expected: all three guards exit 0. If any prints a match, stop this plan and
finish the full safety baseline first.

Then run the safety plan's complete executable gate:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q backend/tests -m unit
```

Expected: all unit tests pass, including scheduler lifecycle/exports,
contended AkShare serialization, lock observability and worker-thread timeout
compatibility. Any failure stops this plan; source-shape checks alone do not
prove that the prerequisite is complete.

Require an empty index before this slice stages its first file:

```bash
if ! git diff --cached --quiet; then
  echo "index contains changes outside the Watchlist slice"
  exit 1
fi
```

Expected: exit 0. Preserve unrelated unstaged/untracked user files and never add
them to this slice.

- [ ] **Step 2: Record the existing frontend baseline**

Run in order:

```bash
cd frontend
npm test
npx tsc --noEmit
npm run build
```

Expected: current Node tests, strict typecheck, and production build pass before new Feature tests are added.

- [ ] **Step 3: Record the current backend route/preload baseline**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_api_watchlist.py \
  backend/tests/test_watchlist_preload_jobs.py
```

Expected: existing successful and partial preload behavior passes against a disposable database ending in `_test`.

---

### Task 2: Make preload startup failures release their claims

**Files:**

- Create: `backend/tests/test_watchlist_preload_dispatch.py`
- Modify: `backend/services/watchlist/watchlist_preload_jobs.py`
- Verify: `backend/tests/test_watchlist_preload_jobs.py`

- [ ] **Step 1: Add an isolated job-state fixture and RED submit-failure test**

Create `backend/tests/test_watchlist_preload_dispatch.py` with an autouse fixture that, while holding `jobs._lock`, clears `_jobs` and `_active_by_code` before and after each test. Replace `_executor` with a stub; never shut down the production executor.

Add:

```python
def test_submit_failure_releases_claim_and_marks_snapshot_failed(
    monkeypatch,
):
    from backend.services.watchlist import watchlist_preload_jobs as jobs

    statuses: list[str] = []

    class RejectingExecutor:
        def submit(self, *_args, **_kwargs):
            raise RuntimeError("executor rejected")

    monkeypatch.setattr(jobs, "_executor", RejectingExecutor())
    monkeypatch.setattr(
        jobs,
        "_set_watchlist_preload",
        lambda _code, *, status=None: statuses.append(status),
    )

    with pytest.raises(RuntimeError, match="executor rejected"):
        jobs.start_preload_job("110011")

    with jobs._lock:
        assert "110011" not in jobs._active_by_code
        snapshots = list(jobs._jobs.values())

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["status"] == "failed"
    assert snapshot["finished_at"] is not None
    assert snapshot["errors"] == [
        "preload dispatch failed: executor rejected",
    ]
    assert statuses == ["pending", "failed"]
```

Add a second test where the `status="failed"` DB update raises. Capture logs and assert:

```python
assert record.fund_code == "110011"
assert record.stage == "preload_dispatch_cleanup"
assert "110011" not in jobs._active_by_code
```

Then replace `_executor` with an accepting stub and call `start_preload_job("110011")` again. Assert the second call obtains a different `job_id`, proving the rejected claim is not permanent.

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_watchlist_preload_dispatch.py
```

Expected RED: the current implementation leaves a pending snapshot and active claim.

- [ ] **Step 2: Add a RED pending-write failure test**

Add:

```python
def test_pending_write_failure_discards_unpublished_snapshot(
    monkeypatch,
):
    from backend.services.watchlist import watchlist_preload_jobs as jobs

    monkeypatch.setattr(
        jobs,
        "_set_watchlist_preload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("pending write failed")
        ),
    )

    with pytest.raises(RuntimeError, match="pending write failed"):
        jobs.start_preload_job("110011")

    with jobs._lock:
        assert jobs._active_by_code == {}
        assert jobs._jobs == {}
```

Expected RED: the current implementation has already populated both maps.

- [ ] **Step 3: Implement separate unpublished and submit-rejected cleanup**

Add a module logger and these private helpers to `watchlist_preload_jobs.py`:

```python
import logging


logger = logging.getLogger(__name__)


def _discard_unpublished_job(job_id: str, fund_code: str) -> None:
    with _lock:
        if _active_by_code.get(fund_code) == job_id:
            _active_by_code.pop(fund_code, None)
        _jobs.pop(job_id, None)


def _mark_dispatch_failed(
    job_id: str,
    fund_code: str,
    exc: Exception,
) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["status"] = "failed"
            job["finished_at"] = _now()
            job["errors"] = [
                f"preload dispatch failed: {exc}",
            ]
        if _active_by_code.get(fund_code) == job_id:
            _active_by_code.pop(fund_code, None)

    try:
        _set_watchlist_preload(fund_code, status="failed")
    except Exception:  # noqa: BLE001
        logger.exception(
            "watchlist preload dispatch cleanup failed",
            extra={
                "fund_code": fund_code,
                "job_id": job_id,
                "stage": "preload_dispatch_cleanup",
            },
        )
```

Replace the tail of `start_preload_job` after publishing the in-memory job:

```python
    try:
        _set_watchlist_preload(fund_code, status="pending")
    except Exception:
        _discard_unpublished_job(job_id, fund_code)
        logger.exception(
            "watchlist preload pending write failed",
            extra={
                "fund_code": fund_code,
                "job_id": job_id,
                "stage": "preload_pending_write",
            },
        )
        raise

    if run_inline:
        _run_preload(job_id)
        return get_preload_job(fund_code, job_id)

    try:
        _executor.submit(_run_preload, job_id)
    except Exception as exc:
        _mark_dispatch_failed(job_id, fund_code, exc)
        raise

    return _snapshot(job)
```

- [ ] **Step 4: Run GREEN preload dispatch tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_watchlist_preload_dispatch.py
```

Then:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_watchlist_preload_jobs.py \
  backend/tests/test_watchlist_preload_dispatch.py
```

Expected GREEN: rejected startup never leaves a permanent active claim; existing inline done/partial behavior is unchanged.

- [ ] **Step 5: Commit the preload lifecycle fix**

```bash
git add backend/services/watchlist/watchlist_preload_jobs.py \
  backend/tests/test_watchlist_preload_dispatch.py
git diff --cached --name-status
git diff --cached --check
git commit --only -m "fix: clean up rejected watchlist preload submissions" -- \
  backend/services/watchlist/watchlist_preload_jobs.py \
  backend/tests/test_watchlist_preload_dispatch.py
```

---

### Task 3: Add the atomic PostgreSQL repository primitive

**Files:**

- Create: `backend/tests/test_watchlist_atomic_repository.py`
- Modify: `backend/db/repositories/watchlist.py`

**Interface:**

- `create_if_absent(session, fund_code, attrs)` accepts a caller-owned
  `Session`, a code, and `Mapping[str, object | None]`.
- It returns `tuple[dict[str, Any], bool]`, where the boolean is true only when
  this statement's `RETURNING` produced a row.
- The exact implementation is in Step 3 below.

- [ ] **Step 1: Add RED create/duplicate/rollback tests**

Create `backend/tests/test_watchlist_atomic_repository.py`, mark it `pytest.mark.db_multiconnection`, and add:

```python
def test_create_if_absent_returns_created_true_and_full_row(
    db_multiconnection_engine,
):
    Session = sessionmaker(
        bind=db_multiconnection_engine,
        expire_on_commit=False,
    )
    with Session.begin() as session:
        row, created = watchlist_repo.create_if_absent(
            session,
            "110011",
            {
                "note": "first",
                "is_holding": None,
                "is_focus": None,
                "holding_amount": 12000.5,
            },
        )

    assert created is True
    assert row["fund_code"] == "110011"
    assert row["note"] == "first"
    assert row["is_holding"] is False
    assert row["is_focus"] is False
    assert row["holding_amount"] == 12000.5
```

Add:

- `test_create_if_absent_duplicate_returns_created_false_without_overwrite`
- `test_create_if_absent_does_not_commit_and_is_removed_by_rollback`

The duplicate test must assert the second note/flags are ignored and both calls return the same `id`.

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_watchlist_atomic_repository.py
```

Expected RED: `create_if_absent` does not exist.

- [ ] **Step 2: Add the RED two-connection concurrency test**

Use two independent `Session` instances and `threading.Barrier(2)`. Each worker enters `Session.begin()`, waits at the barrier, calls `create_if_absent`, exits to commit, and returns the outcome.

Assert:

```python
assert sorted(created for _row, created in outcomes) == [False, True]
assert outcomes[0][0]["id"] == outcomes[1][0]["id"]

with Session() as session:
    count = session.scalar(
        select(func.count()).select_from(Watchlist)
        .where(Watchlist.fund_code == "110011")
    )
assert count == 1
```

Do not use the single-connection `db_session` fixture for this test.

- [ ] **Step 3: Implement PostgreSQL INSERT/RETURNING**

Update imports in `backend/db/repositories/watchlist.py`:

```python
from typing import Any, Mapping

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
```

Add:

```python
def create_if_absent(
    session: Session,
    fund_code: str,
    attrs: Mapping[str, object | None],
) -> tuple[dict[str, Any], bool]:
    """原子新增自选；冲突时返回同一事务内读到的原行。"""
    initial = _patch_to_set(dict(attrs))
    for key in ("is_holding", "is_focus"):
        if initial.get(key) is None:
            initial.pop(key, None)

    statement = (
        pg_insert(Watchlist)
        .values(fund_code=fund_code, **initial)
        .on_conflict_do_nothing(
            index_elements=[Watchlist.fund_code],
        )
        .returning(Watchlist)
    )
    inserted = session.scalar(statement)
    if inserted is not None:
        return _watchlist_to_dict(inserted), True

    existing = session.scalar(
        select(Watchlist).where(
            Watchlist.fund_code == fund_code,
        )
    )
    if existing is None:
        raise RuntimeError(
            f"watchlist conflict row disappeared for {fund_code}"
        )
    return _watchlist_to_dict(existing), False
```

Do not call commit, rollback, close, `session_scope`, network code, or preload code here.

- [ ] **Step 4: Run GREEN repository tests**

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_watchlist_atomic_repository.py
```

Expected GREEN: create, duplicate, rollback and concurrent get-or-create tests pass.

- [ ] **Step 5: Keep the primitive uncommitted until the vertical slice is connected**

```bash
git diff --check -- \
  backend/db/repositories/watchlist.py \
  backend/tests/test_watchlist_atomic_repository.py
git status --short -- \
  backend/db/repositories/watchlist.py \
  backend/tests/test_watchlist_atomic_repository.py
```

Expected: the primitive and its PostgreSQL tests are GREEN and clean under
`git diff --check`, but no commit is created. Continue immediately through
Tasks 4–5; Repository, Application and Route land together as one usable
vertical slice.

---

### Task 4: Put transaction and post-commit dispatch in the Application use case

**Files:**

- Create: `backend/application/__init__.py`
- Create: `backend/application/watchlist/__init__.py`
- Create: `backend/application/watchlist/add_entry.py`
- Create: `backend/tests/test_watchlist_add_entry.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class WatchlistCreateInput:
    fund_code: str
    note: str | None = None
    is_holding: bool | None = None
    is_focus: bool | None = None
    holding_amount: float | None = None
    holding_share: float | None = None
    cost_nav: float | None = None
    buy_date: str | None = None


@dataclass(frozen=True, slots=True)
class WatchlistCreateOutcome:
    row: dict[str, Any]
    created: bool
```

`add_watchlist_entry(payload)` accepts `WatchlistCreateInput` and returns
`WatchlistCreateOutcome`; its exact implementation is in Step 2 below.

- [ ] **Step 1: Add RED transaction-order and duplicate tests**

Create `backend/tests/test_watchlist_add_entry.py` with pure fakes for `session_scope`, Repository and preload adapter. Add:

- `test_dispatch_occurs_after_session_scope_clean_exit`
- `test_duplicate_does_not_dispatch_or_overwrite`
- `test_repository_failure_propagates_without_dispatch`
- `test_commit_failure_does_not_dispatch`
- `test_dispatch_failure_returns_committed_failed_row_without_job`
- `test_pending_write_failure_returns_committed_failed_row_without_job`
- `test_failed_cleanup_write_failure_still_returns_committed_failed_row`

The success-order fake must produce:

```python
assert events == ["repository", "commit", "dispatch"]
```

The commit-failure test must assert:

```python
with pytest.raises(RuntimeError, match="commit failed"):
    add_entry.add_watchlist_entry(payload)
assert dispatch_calls == []
```

The dispatch-failure tests must start from the row returned by the successfully
committed first `session_scope()`:

```python
{
    "fund_code": "110011",
    "preload_status": None,
}
```

Then assert:

```python
assert outcome.created is True
assert outcome.row["preload_status"] == "failed"
assert "preload_job" not in outcome.row
assert record.fund_code == "110011"
assert record.stage == "preload_dispatch"
assert session_scope_entries == 1
```

Make `start_preload_job()` separately raise a pending-write error and a
submit-rejection whose failed-status cleanup also failed. Both cases must return
the committed row with response status `failed`; neither may re-enter
`session_scope()` or let a cleanup/read exception turn the HTTP path into 500.

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_watchlist_add_entry.py
```

Expected RED: the Application package does not exist.

- [ ] **Step 2: Implement the narrow Application use case**

Create empty package markers and implement `backend/application/watchlist/add_entry.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any

from backend.db.repositories import watchlist as watchlist_repo
from backend.db.session_scope import session_scope
from backend.services.watchlist import watchlist_preload_jobs as preload_jobs


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WatchlistCreateInput:
    fund_code: str
    note: str | None = None
    is_holding: bool | None = None
    is_focus: bool | None = None
    holding_amount: float | None = None
    holding_share: float | None = None
    cost_nav: float | None = None
    buy_date: str | None = None


@dataclass(frozen=True, slots=True)
class WatchlistCreateOutcome:
    row: dict[str, Any]
    created: bool


def add_watchlist_entry(
    payload: WatchlistCreateInput,
) -> WatchlistCreateOutcome:
    attrs = asdict(payload)
    attrs.pop("fund_code")

    with session_scope() as session:
        row, created = watchlist_repo.create_if_absent(
            session,
            payload.fund_code,
            attrs,
        )

    if not created:
        return WatchlistCreateOutcome(
            row=row,
            created=False,
        )

    try:
        job = preload_jobs.start_preload_job(
            payload.fund_code,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "watchlist preload dispatch failed",
            extra={
                "fund_code": payload.fund_code,
                "stage": "preload_dispatch",
            },
        )
        failed_row = {
            **row,
            "preload_status": "failed",
        }
        failed_row.pop("preload_job", None)
        return WatchlistCreateOutcome(
            row=failed_row,
            created=True,
        )

    if job:
        row = {
            **row,
            "preload_status": job.get("status"),
            "preload_job": job,
        }
    return WatchlistCreateOutcome(
        row=row,
        created=True,
    )
```

The preload adapter owns persisted failed-status cleanup. Application never
re-reads after dispatch failure; it normalizes the already committed row to a
failed/no-job response so cleanup or database-read failures cannot turn this
post-commit condition into HTTP 500.

- [ ] **Step 3: Run GREEN Application tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_watchlist_add_entry.py \
  backend/tests/test_watchlist_preload_dispatch.py
```

Expected GREEN: commit precedes dispatch, duplicate/transaction failure never dispatches, and submit rejection returns the committed failed row.

---

### Task 5: Make the POST Route a protocol-only adapter

**Files:**

- Modify: `backend/api/routes/watchlist.py`
- Modify: `backend/tests/test_api_watchlist.py`
- Create: `backend/tests/test_watchlist_slice_contract.py`
- Modify: `docs/superpowers/decisions/0002-transaction-ownership.md`

- [ ] **Step 1: Rewrite Route behavior tests to patch the Application adapter**

In `backend/tests/test_api_watchlist.py`, patch:

```python
from backend.application.watchlist import add_entry
```

and replace Route-level `preload_jobs` monkeypatches with:

```python
monkeypatch.setattr(
    add_entry,
    "preload_jobs",
    SimpleNamespace(start_preload_job=_fake_start),
)
```

Preserve or add assertions for:

- first POST: 200, all existing top-level row fields, `preload_status=pending`, and `preload_job`;
- duplicate POST: original note/flags, no dispatch, no job;
- submit failure: 200, committed row, `preload_status=failed`, no job;
- pending-write failure: 200, committed row, response `preload_status=failed`,
  no job;
- submit failure whose failed-status DB cleanup also fails: still 200 with the
  same committed/failed response, not 500;
- `created` never appears in JSON;
- bad date, negative amount and extra fields remain 422.

Run the newly added submit-failure route case. Expected RED: Route still calls `ws.get_one()`/`ws.add_full()`/`preload_jobs` directly.

- [ ] **Step 2: Add a Pydantic-to-Application mapper and thin Route**

At the import section of `backend/api/routes/watchlist.py`, import:

```python
from backend.application.watchlist import add_entry
```

Add:

```python
def _add_input(
    payload: WatchlistUpsert,
) -> add_entry.WatchlistCreateInput:
    values = _add_payload(payload)
    return add_entry.WatchlistCreateInput(
        fund_code=payload.fund_code,
        note=values.get("note"),
        is_holding=values.get("is_holding"),
        is_focus=values.get("is_focus"),
        holding_amount=values.get("holding_amount"),
        holding_share=values.get("holding_share"),
        cost_nav=values.get("cost_nav"),
        buy_date=values.get("buy_date"),
    )
```

Replace only `add_watchlist`:

```python
@router.post("", status_code=200)
def add_watchlist(payload: WatchlistUpsert) -> dict:
    """原子幂等添加；公开响应保持现有顶层 row 形状。"""
    outcome = add_entry.add_watchlist_entry(
        _add_input(payload),
    )
    return outcome.row
```

Delete the POST function’s calls to `ws.get_one`, `ws.add_full`, and `preload_jobs.start_preload_job`. Do not alter other routes.

- [ ] **Step 3: Add slice-scoped architecture guards**

Create `backend/tests/test_watchlist_slice_contract.py`, mark it `pytest.mark.unit`, parse only the migrated function/module, and assert:

- `backend/application/watchlist/add_entry.py` does not import `backend.api`, `backend.db.models`, or SQLAlchemy query/build APIs;
- `add_watchlist()` contains no reference to `ws`, Repository, Session or `preload_jobs`;
- Repository/Application source contains no direct `.commit()`, `.rollback()` or `.close()`;
- Application returns `WatchlistCreateOutcome`, while Route returns only `outcome.row`.

Do not scan the entire Route for ORM because the un-migrated enriched GET still uses `select(Fund)`.

- [ ] **Step 4: Update ADR-002 with the local replacement rule**

Append a dated section to `docs/superpowers/decisions/0002-transaction-ownership.md`:

```markdown
## 2026-07-24 局部修订：已迁移写用例

对于已经迁移到 `backend/application/` 的写用例：

- Delivery 不获取 Session，也不编排跨 Service 副作用；
- 顶层 Application 函数通过具体 `session_scope()` 拥有事务；
- 跨事务副作用只能在 `session_scope()` 成功退出后触发；
- Repository 仍只 flush，不 commit/rollback/close；
- 尚未迁移的旧路由继续维持本 ADR 原有契约，不把新规则伪装为全仓已完成。

首个采用该规则的路径是 `POST /api/watchlist` →
`backend.application.watchlist.add_entry.add_watchlist_entry()`。
```

- [ ] **Step 5: Run backend GREEN gates**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_watchlist_add_entry.py \
  backend/tests/test_watchlist_slice_contract.py \
  backend/tests/test_watchlist_preload_dispatch.py
```

Run:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_watchlist_atomic_repository.py \
  backend/tests/test_api_watchlist.py \
  backend/tests/test_watchlist_preload_jobs.py
```

Expected GREEN: protocol compatibility, atomic concurrency, post-commit dispatch and lifecycle cleanup all pass.

- [ ] **Step 6: Commit the backend vertical slice**

```bash
git add backend/application/__init__.py \
  backend/application/watchlist/__init__.py \
  backend/application/watchlist/add_entry.py \
  backend/db/repositories/watchlist.py \
  backend/api/routes/watchlist.py \
  backend/tests/test_watchlist_add_entry.py \
  backend/tests/test_watchlist_atomic_repository.py \
  backend/tests/test_watchlist_slice_contract.py \
  backend/tests/test_api_watchlist.py \
  docs/superpowers/decisions/0002-transaction-ownership.md
git diff --cached --name-status
git diff --cached --check
git commit --only -m "feat: add watchlist entries through an application use case" -- \
  backend/application/__init__.py \
  backend/application/watchlist/__init__.py \
  backend/application/watchlist/add_entry.py \
  backend/db/repositories/watchlist.py \
  backend/api/routes/watchlist.py \
  backend/tests/test_watchlist_add_entry.py \
  backend/tests/test_watchlist_atomic_repository.py \
  backend/tests/test_watchlist_slice_contract.py \
  backend/tests/test_api_watchlist.py \
  docs/superpowers/decisions/0002-transaction-ownership.md
```

---

### Task 6: Extract the one shared typed HTTP transport

**Files:**

- Create: `frontend/src/lib/http.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/tests/api-client.test.mjs`
- Create: `frontend/tests/http.test.ts`
- Create: `frontend/tests/transport-consumers.test.ts`

**Interface:**

```ts
export type QueryValue =
  | string
  | number
  | boolean
  | null
  | undefined;

export interface HttpRequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  params?: Record<string, QueryValue>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly details: unknown;
  readonly path: string;
}

export async function request<T>(
  path: string,
  options: HttpRequestOptions = {},
): Promise<T>;
```

- [ ] **Step 1: Install the Feature-scoped behavior-test runtime**

Run:

```bash
cd frontend
npm install --save-dev \
  vitest \
  jsdom \
  @testing-library/react \
  @testing-library/jest-dom
```

Expected: `package.json` and `package-lock.json` update. Add scripts:

```json
{
  "test": "node --test",
  "test:component": "vitest run",
  "typecheck": "tsc --noEmit"
}
```

- [ ] **Step 2: Add deterministic Vitest configuration**

Create `frontend/vitest.config.ts`:

```ts
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/vitest.setup.ts"],
    clearMocks: true,
    restoreMocks: true,
  },
});
```

Create `frontend/tests/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 3: Add RED transport behavior tests**

Create `frontend/tests/http.test.ts` and test:

- GET omits `""`, `null`, and `undefined` params but keeps `false` and `0`;
- base selection remains `NEXT_PUBLIC_API_BASE_URL ?? NEXT_PUBLIC_API_BASE ?? localhost`;
- POST serializes JSON and merges custom headers;
- 204 returns `undefined`;
- `{error:{code,message,details}}` becomes `ApiError`;
- `{detail:"invalid input"}` becomes `ApiError` with `code=null`;
- a FastAPI validation
  `{detail:[{"loc":["body"],"msg":"invalid"}]}` body keeps the array in
  `details` and uses its JSON representation as the readable message;
- `signal` is passed to `fetch`;
- a fetch-thrown `AbortError` remains the same object.

Typed error assertions:

```ts
expect(error).toBeInstanceOf(ApiError);
expect(error.status).toBe(409);
expect(error.code).toBe("database_conflict");
expect(error.details).toEqual({ fund_code: "110011" });
expect(error.message).toBe("already exists");
expect(String(error)).toContain(
  "/api/watchlist -> already exists",
);
```

Run:

```bash
cd frontend
npm run test:component -- tests/http.test.ts
```

Expected RED: `src/lib/http.ts` does not exist.

- [ ] **Step 4: Implement `request<T>()` and `ApiError`**

Create `frontend/src/lib/http.ts` with:

```ts
const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://localhost:8000";

export type QueryValue =
  | string
  | number
  | boolean
  | null
  | undefined;

export interface HttpRequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  params?: Record<string, QueryValue>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly details: unknown;
  readonly path: string;

  constructor({
    path,
    status,
    message,
    code = null,
    details = null,
  }: {
    path: string;
    status: number;
    message: string;
    code?: string | null;
    details?: unknown;
  }) {
    super(message);
    this.name = "ApiError";
    this.path = path;
    this.status = status;
    this.code = code;
    this.details = details;
  }

  override toString(): string {
    return `${this.name}: ${this.path} -> ${this.message}`;
  }
}

async function apiError(
  response: Response,
  path: string,
): Promise<ApiError> {
  let message = `${response.status} ${response.statusText}`;
  let code: string | null = null;
  let details: unknown = null;
  try {
    const data = await response.json();
    if (
      data?.error &&
      typeof data.error.message === "string"
    ) {
      message = data.error.message;
      code = typeof data.error.code === "string"
        ? data.error.code
        : null;
      details = data.error.details ?? null;
    } else if (typeof data?.detail === "string") {
      message = data.detail;
      details = data.detail;
    } else if (Array.isArray(data?.detail)) {
      details = data.detail;
      message = JSON.stringify(data.detail);
    }
  } catch {
    // Non-JSON error body keeps the HTTP status text.
  }
  return new ApiError({
    path,
    status: response.status,
    message,
    code,
    details,
  });
}

export async function request<T>(
  path: string,
  options: HttpRequestOptions = {},
): Promise<T> {
  const {
    method = "GET",
    params,
    body,
    headers = {},
    signal,
  } = options;
  const url = new URL(BASE + path);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== "" && value !== null && value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url, {
    method,
    headers: body === undefined
      ? headers
      : {
          "Content-Type": "application/json",
          ...headers,
        },
    body: body === undefined
      ? undefined
      : JSON.stringify(body),
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw await apiError(response, path);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}
```

- [ ] **Step 5: Mechanically delegate every legacy endpoint**

In `frontend/src/lib/api.ts`:

- import `request` from `@/lib/http`;
- delete local `BASE`, `parseError`, `get`, `send`, and `post`;
- translate every GET to `request(path, { params })`;
- translate every write to `request(path, { method, body })`;
- migrate `briefingRun` to:

```ts
briefingRun: (briefType = "post_market") =>
  request<BriefingRunResponse>("/api/briefing/run", {
    method: "POST",
    headers: { "X-Local-Trigger": "1" },
    body: { brief_type: briefType },
  }),
```

Keep `api.watchlistAdd` and `api.watchlistPreloadJob` temporarily, and delegate
them to `request()` like every other endpoint. Existing Drawer consumers still
need them until Task 8 switches both ordinary add and shared polling in one
type-safe step. They are deleted only in Task 8.

In `frontend/src/types/api.ts`:

- keep `WatchlistAddResponse`, `WatchlistUpsertPayload`,
  `WatchlistPatchPayload`, `WatchlistPreloadStatus`, and
  `WatchlistPreloadJob` unchanged until Task 8;
- do not weaken or duplicate their shapes while both legacy consumers still
  compile.

- [ ] **Step 6: Update the existing VM loader without weakening endpoint tests**

In `frontend/tests/api-client.test.mjs`, transpile `http.ts` first and supply it through a custom CommonJS resolver when `api.ts` requires `@/lib/http`. Keep all existing URL/method/header assertions, including the temporary `api.watchlistAdd` and `api.watchlistPreloadJob` coverage. Task 8 removes those two tests only after all production consumers have moved.

Create `frontend/tests/transport-consumers.test.ts` using `vi.mock("@/lib/http")` and assert `api.fund()` and `api.briefingRun()` both call the one `request` spy. Extend this test with Watchlist Feature consumers after Task 7.

- [ ] **Step 7: Run GREEN transport tests**

Run:

```bash
cd frontend
npm run test:component -- \
  tests/http.test.ts \
  tests/transport-consumers.test.ts
npm test -- tests/api-client.test.mjs
npm run typecheck
```

Expected GREEN: typed errors, cancellation, headers and all legacy endpoint contracts pass through the one transport.

---

### Task 7: Build the Watchlist add/preload Feature

**Files:**

- Create: `frontend/src/features/watchlist/contracts.ts`
- Create: `frontend/src/features/watchlist/api.ts`
- Create: `frontend/src/features/watchlist/use-add-entry.ts`
- Create: `frontend/src/features/watchlist/use-preload-job.ts`
- Create: `frontend/src/features/watchlist/index.ts`
- Create: `frontend/tests/watchlist-contracts.test.ts`
- Create: `frontend/tests/watchlist-add.test.tsx`
- Create: `frontend/tests/watchlist-preload.test.tsx`
- Modify: `frontend/tests/transport-consumers.test.ts`

- [ ] **Step 1: Add RED response-normalization tests**

Create `frontend/tests/watchlist-contracts.test.ts` with one job and one no-job response. Assert:

```ts
expect(outcome.row).not.toHaveProperty("preload_job");
expect(outcome.preloadJob).toEqual(job);
expect(withoutJob.preloadJob).toBeNull();
```

Expected RED: Feature contracts do not exist.

- [ ] **Step 2: Implement Feature contracts and normalization**

Create `frontend/src/features/watchlist/contracts.ts`:

```ts
import type {
  WatchlistPreloadJob,
  WatchlistRow,
} from "@/types/api";

export interface AddWatchlistPayload {
  fund_code: string;
  note?: string | null;
  is_holding?: boolean | null;
  is_focus?: boolean | null;
  holding_amount?: number | null;
  holding_share?: number | null;
  cost_nav?: number | null;
  buy_date?: string | null;
}

export type AddWatchlistWireResponse = WatchlistRow & {
  preload_job?: WatchlistPreloadJob | null;
};

export interface AddWatchlistOutcome {
  row: WatchlistRow;
  preloadJob: WatchlistPreloadJob | null;
}

export function normalizeAddWatchlistResponse(
  response: AddWatchlistWireResponse,
): AddWatchlistOutcome {
  const {
    preload_job: preloadJob = null,
    ...row
  } = response;
  return {
    row,
    preloadJob,
  };
}
```

- [ ] **Step 3: Implement the Feature API as the second transport consumer**

Create `frontend/src/features/watchlist/api.ts`:

```ts
import { request } from "@/lib/http";
import type { WatchlistPreloadJob } from "@/types/api";
import {
  normalizeAddWatchlistResponse,
  type AddWatchlistPayload,
  type AddWatchlistWireResponse,
  type AddWatchlistOutcome,
} from "./contracts";

export const watchlistApi = {
  async addEntry(
    payload: AddWatchlistPayload,
    signal?: AbortSignal,
  ): Promise<AddWatchlistOutcome> {
    const response = await request<AddWatchlistWireResponse>(
      "/api/watchlist",
      {
        method: "POST",
        body: payload,
        signal,
      },
    );
    return normalizeAddWatchlistResponse(response);
  },

  preloadJob(
    fundCode: string,
    jobId: string,
    signal?: AbortSignal,
  ): Promise<WatchlistPreloadJob> {
    return request<WatchlistPreloadJob>(
      `/api/watchlist/${encodeURIComponent(
        fundCode,
      )}/preload/${encodeURIComponent(jobId)}`,
      { signal },
    );
  },
};
```

Extend `transport-consumers.test.ts` to call both methods and assert the same mocked `request` is used by legacy `api` and Feature API.

- [ ] **Step 4: Add RED confirmed-cache and mutation-order tests**

In `frontend/tests/watchlist-add.test.tsx`, use a fresh `QueryClient` per test and cover:

- existing same code: length unchanged, `{...cachedRow, ...responseRow}`, enriched GET-only fields retained;
- absent code: append exactly once; applying twice still yields one row;
- cache `undefined`: stays undefined and only invalidates;
- cache `[]`: appends the row;
- success event order:

```ts
expect(events).toEqual([
  "cache",
  "invalidate",
  "success-toast",
  "onSaved",
  "info-toast",
  "polling",
  "close",
]);
```

- inject a `startPreloadPolling` spy into `useAddEntry`; do not mock a second
  `usePreloadJob()` instance inside the mutation hook;
- no job skips info/polling;
- API rejection leaves cache unchanged, performs no invalidate/callback/poll/close, and emits the current error toast.

Expected RED: cache action and mutation hook do not exist.

- [ ] **Step 5: Implement confirmed cache update and add mutation**

In `frontend/src/features/watchlist/use-add-entry.ts`, import both
`WatchlistRow` and `WatchlistPreloadJob` from `@/types/api`, then implement:

```ts
export function applyAddSucceeded(
  queryClient: QueryClient,
  responseRow: WatchlistRow,
): void {
  const cached = queryClient.getQueryData<WatchlistRow[]>(
    queryKeys.watchlist.all,
  );

  if (cached !== undefined) {
    const index = cached.findIndex(
      (row) => row.fund_code === responseRow.fund_code,
    );
    const next = index === -1
      ? [...cached, responseRow]
      : cached.map((row, rowIndex) =>
          rowIndex === index
            ? { ...row, ...responseRow }
            : row
        );
    queryClient.setQueryData(
      queryKeys.watchlist.all,
      next,
    );
  }

  void queryClient.invalidateQueries({
    queryKey: queryKeys.watchlist.all,
  });
}
```

Implement:

```ts
export function useAddEntry({
  onSaved,
  onClose,
  startPreloadPolling,
}: {
  onSaved?: (row: WatchlistRow) => void;
  onClose: () => void;
  startPreloadPolling: (
    job: WatchlistPreloadJob,
  ) => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();

  return useMutation({
    mutationFn: (payload: AddWatchlistPayload) =>
      watchlistApi.addEntry(payload),
    onSuccess: ({ row, preloadJob }) => {
      applyAddSucceeded(queryClient, row);
      toast.push(
        `${row.fund_code} 已加入自选池`,
        "success",
      );
      onSaved?.(row);
      if (preloadJob) {
        toast.push(
          `${row.fund_code} 正在后台同步基金数据`,
          "info",
        );
        startPreloadPolling(preloadJob);
      }
      onClose();
    },
    onError: (error: Error) => {
      toast.push(`保存失败：${String(error)}`, "error");
    },
  });
}
```

`useAddEntry()` does not create its own polling hook. The Drawer composition
root injects the one `startPreloadPolling` function in Task 8, so ordinary add,
initial-holding and edit-with-initial-holding all share one active observer.

- [ ] **Step 6: Add RED preload behavior tests**

In `frontend/tests/watchlist-preload.test.tsx`, use fake timers and cover:

- first request occurs at 1,500 ms, not before;
- React Query `signal` is forwarded to `watchlistApi.preloadJob`;
- `done`, `partial`, `failed`, and `missing` stop further requests;
- each terminal state invokes every cache invalidation exactly once;
- query error stops and emits the existing error toast;
- `open=false` on a host wrapper does not stop polling while the hook remains mounted;
- unmount stops the observer;
- existing `frontend/tests/polling.test.mjs` remains the source of truth for max 120 attempts and terminal predicates.

- [ ] **Step 7: Move preload polling and its semantic cache effect**

Create `frontend/src/features/watchlist/use-preload-job.ts` by moving the current hook behavior. Export:

```ts
export type StartPreloadPolling = (
  job: WatchlistPreloadJob,
) => void;

export function applyPreloadTerminal(
  queryClient: QueryClient,
  fundCode: string,
): void {
  void queryClient.invalidateQueries({
    queryKey: queryKeys.watchlist.all,
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.fund.summaryForFund(fundCode),
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.fund.detail(fundCode),
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.fund.navForFund(fundCode),
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.fund.navHistoryForFund(fundCode),
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.fund.metrics(fundCode),
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.portfolio.pnl([fundCode]),
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.portfolio.pnl([]),
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.fund.diagnosisForFund(fundCode),
  });
}
```

Keep the current `ActivePreloadJob`, `PreloadPollingTick`, attempt counting, query policy, terminal predicates and toast messages. Replace the query function call with:

```ts
queryFn: async ({ signal }) => {
  if (!active) {
    return {
      startedAt: 0,
      snapshot: null,
      attempts: 0,
    };
  }
  if (
    Date.now() - active.startedAt <
    queryPolicy.watchlistPreload.intervalMs
  ) {
    return {
      startedAt: active.startedAt,
      snapshot: null,
      attempts: attemptsRef.current,
    };
  }
  attemptsRef.current += 1;
  const snapshot = await watchlistApi.preloadJob(
    active.job.fund_code,
    active.job.job_id,
    signal,
  );
  return {
    startedAt: active.startedAt,
    snapshot,
    attempts: attemptsRef.current,
  };
},
```

Call `applyPreloadTerminal` exactly once when reaching a terminal state or exhaustion/error.

- [ ] **Step 8: Add the narrow Feature public entry**

Create `frontend/src/features/watchlist/index.ts`:

```ts
export { watchlistApi } from "./api";
export {
  normalizeAddWatchlistResponse,
  type AddWatchlistOutcome,
  type AddWatchlistPayload,
} from "./contracts";
export {
  applyAddSucceeded,
  useAddEntry,
} from "./use-add-entry";
export {
  applyPreloadTerminal,
  type StartPreloadPolling,
  usePreloadJob,
} from "./use-preload-job";
```

- [ ] **Step 9: Run Feature GREEN tests**

Run:

```bash
cd frontend
npm run test:component -- \
  tests/watchlist-contracts.test.ts \
  tests/watchlist-add.test.tsx \
  tests/watchlist-preload.test.tsx \
  tests/transport-consumers.test.ts
npm run typecheck
```

Expected GREEN: normalization, confirmed cache, success/error order, polling
lifecycle, shared callback typing and single transport consumers pass.

---

### Task 8: Wire only ordinary add into the Feature

**Files:**

- Modify: `frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts`
- Modify: `frontend/src/components/watchlist-drawer/WatchlistDrawer.tsx`
- Delete: `frontend/src/components/watchlist-drawer/hooks/useWatchlistPreloadPolling.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/tests/api-client.test.mjs`
- Modify: `frontend/tests/watchlist-drawer-structure.test.mjs`

- [ ] **Step 1: Refactor `useWatchlistSave` without migrating legacy paths**

Import `useAddEntry`, `usePreloadJob`, and `AddWatchlistPayload` from the
Feature. Remove the old polling hook import. Create one polling owner at the
Drawer save-hook level and inject it into ordinary add:

At hook setup:

```ts
const { startPreloadPolling } = usePreloadJob();
const addEntry = useAddEntry({
  onSaved,
  onClose,
  startPreloadPolling,
});
```

At the top of `submit`, replace the old guard with:

```ts
if (submitting || addEntry.isPending) return;
```

After validation and before setting legacy `submitting`, handle only ordinary add:

```ts
if (
  mode === "add" &&
  !(needsInitialHolding && initialHoldingDraft)
) {
  const payload: AddWatchlistPayload = {
    fund_code: fundCode,
    note: form.note || null,
    is_holding: form.is_holding,
    is_focus: form.is_focus,
    holding_amount: null,
  };
  addEntry.mutate(payload);
  return;
}
```

Delete the old `api.watchlistAdd` branch. Keep initial-holding and edit request
paths, cache invalidations and messages unchanged. Their existing
`startPreloadPolling(preloadJob)` calls now use the Feature-owned function
created above; do not delete those calls.

Return:

```ts
const isSubmitting = submitting || addEntry.isPending;
const saveDisabled = isSubmitting || (
  needsInitialHolding &&
  (selectedNavLoading || initialHoldingDraft == null)
);

return {
  submit,
  saveDisabled,
  isSubmitting,
};
```

- [ ] **Step 2: Use the unified pending flag in the Drawer**

In `WatchlistDrawer.tsx`, replace only save/close guards and save text that currently read `state.submitting` with `save.isSubmitting`:

- Escape guard;
- backdrop close;
- header close button;
- footer cancel button;
- `"保存中..."` label.

State for legacy operations remains in `useWatchlistDrawerState`; no other action’s pending logic changes.

- [ ] **Step 3: Delete superseded global endpoints, types and the old polling hook**

Delete `frontend/src/components/watchlist-drawer/hooks/useWatchlistPreloadPolling.ts`.

In `frontend/src/lib/api.ts`, now that production consumers have moved:

- remove only `api.watchlistAdd` and `api.watchlistPreloadJob`;
- remove their now-unused type imports;
- keep initial-holding, update and every other Watchlist endpoint.

In `frontend/src/types/api.ts`:

- remove `WatchlistAddResponse` and `WatchlistUpsertPayload`;
- replace `WatchlistPatchPayload` with an explicit partial/interface containing
  `note`, `is_holding`, `is_focus`, `holding_amount`, `holding_share`,
  `cost_nav`, and `buy_date`;
- retain `WatchlistPreloadStatus` and `WatchlistPreloadJob`, because the
  initial-holding response and Feature polling still use them.

In `frontend/tests/api-client.test.mjs`, remove only the two tests for the
deleted global endpoints. The Feature transport and behavior tests are now
their executable replacements.

In `frontend/tests/watchlist-drawer-structure.test.mjs`:

- remove the deleted path from `requiredFiles`;
- remove the test that matches `useQuery`, query key and import text in that old file;
- do not replace it with regexes for the new Feature directory, because Vitest behavior tests now cover ownership.

Keep the hard-cut/public-entry/presentational-boundary tests.

- [ ] **Step 4: Run all frontend tests and static checks**

Run in order:

```bash
cd frontend
npm run test:component
npm test
npm run typecheck
npm run build
```

Expected: Vitest Feature behavior, existing Node tests, strict typecheck and production build all pass.

- [ ] **Step 5: Commit the frontend vertical slice**

```bash
git add frontend/package.json frontend/package-lock.json \
  frontend/vitest.config.ts frontend/tests/vitest.setup.ts \
  frontend/src/lib/http.ts frontend/src/lib/api.ts \
  frontend/src/types/api.ts \
  frontend/src/features/watchlist/contracts.ts \
  frontend/src/features/watchlist/api.ts \
  frontend/src/features/watchlist/use-add-entry.ts \
  frontend/src/features/watchlist/use-preload-job.ts \
  frontend/src/features/watchlist/index.ts \
  frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts \
  frontend/src/components/watchlist-drawer/hooks/useWatchlistPreloadPolling.ts \
  frontend/src/components/watchlist-drawer/WatchlistDrawer.tsx \
  frontend/tests/api-client.test.mjs \
  frontend/tests/watchlist-drawer-structure.test.mjs \
  frontend/tests/http.test.ts \
  frontend/tests/watchlist-contracts.test.ts \
  frontend/tests/watchlist-add.test.tsx \
  frontend/tests/watchlist-preload.test.tsx \
  frontend/tests/transport-consumers.test.ts
git diff --cached --name-status
git diff --cached --check
git commit --only -m "feat: move watchlist add and preload into a feature" -- \
  frontend/package.json frontend/package-lock.json \
  frontend/vitest.config.ts frontend/tests/vitest.setup.ts \
  frontend/src/lib/http.ts frontend/src/lib/api.ts \
  frontend/src/types/api.ts \
  frontend/src/features/watchlist/contracts.ts \
  frontend/src/features/watchlist/api.ts \
  frontend/src/features/watchlist/use-add-entry.ts \
  frontend/src/features/watchlist/use-preload-job.ts \
  frontend/src/features/watchlist/index.ts \
  frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts \
  frontend/src/components/watchlist-drawer/hooks/useWatchlistPreloadPolling.ts \
  frontend/src/components/watchlist-drawer/WatchlistDrawer.tsx \
  frontend/tests/api-client.test.mjs \
  frontend/tests/watchlist-drawer-structure.test.mjs \
  frontend/tests/http.test.ts \
  frontend/tests/watchlist-contracts.test.ts \
  frontend/tests/watchlist-add.test.tsx \
  frontend/tests/watchlist-preload.test.tsx \
  frontend/tests/transport-consumers.test.ts
```

The deleted old polling path must be staged as a deletion.

---

### Task 9: Add the frontend CI guard

**Files:**

- Create: `.github/workflows/frontend-tests.yml`

- [ ] **Step 1: Add the ordered CI workflow**

Create:

```yaml
name: frontend-tests

on:
  push:
  pull_request:

jobs:
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm test
      - run: npm run test:component
      - run: npm run typecheck
      - run: npm run build
```

- [ ] **Step 2: Validate the same commands locally**

Run:

```bash
cd frontend
npm ci
npm test
npm run test:component
npm run typecheck
npm run build
```

Expected: all commands pass in the same order as CI.

- [ ] **Step 3: Commit the CI guard**

```bash
git add .github/workflows/frontend-tests.yml
git diff --cached --name-status
git diff --cached --check
git commit --only -m "ci: verify frontend behavior and production build" -- \
  .github/workflows/frontend-tests.yml
```

---

### Task 10: Verify the complete atomic Watchlist slice

**Files:**

- Verify: all files in this plan.

- [ ] **Step 1: Run backend unit/architecture gates**

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_watchlist_add_entry.py \
  backend/tests/test_watchlist_slice_contract.py \
  backend/tests/test_watchlist_preload_dispatch.py \
  backend/tests/test_transaction_ownership_contract.py
```

Expected: all pass.

- [ ] **Step 2: Run PostgreSQL integration and concurrency gates**

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_watchlist_atomic_repository.py \
  backend/tests/test_api_watchlist.py \
  backend/tests/test_watchlist_preload_jobs.py
```

Expected: one row under concurrent POST semantics, correct rollback, and unchanged public responses.

- [ ] **Step 3: Run complete frontend gates**

```bash
npm --prefix frontend test
npm --prefix frontend run test:component
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: all pass serially.

- [ ] **Step 4: Run static backend verification**

```bash
.venv/bin/python -m compileall -q backend
git diff --check
```

Expected: both exit 0.

- [ ] **Step 5: Confirm ownership and compatibility with search**

Run:

```bash
if rg -n \
  '\.watchlistAdd\(|\.watchlistPreloadJob\(|useWatchlistPreloadPolling' \
  frontend/src frontend/app; then
  echo "removed Watchlist add/preload path still has a consumer"
  exit 1
fi
```

Expected: the guard exits 0 without a production match.

Run:

```bash
rg -n \
  'get_one|add_full|start_preload_job' \
  backend/api/routes/watchlist.py
```

Expected: the migrated `add_watchlist()` function contains none of these operations; any match must belong to an explicitly un-migrated route and be reviewed.

- [ ] **Step 6: Review scope and final commit graph**

```bash
git status --short
git log --oneline --stat HEAD~4..HEAD
git diff --stat HEAD~4..HEAD
git diff --check HEAD~4..HEAD
git diff HEAD~4..HEAD
```

Expected: the four planned commits contain no empty Repository/Application
boundary, generic UoW/job framework,
unrelated Watchlist action, second transport, or user-owned unrelated change.
