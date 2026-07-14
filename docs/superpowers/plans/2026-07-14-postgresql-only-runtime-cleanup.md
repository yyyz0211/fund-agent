# PostgreSQL-Only Runtime Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 SQLite 专用运行时代码和全局写锁，同时保留按业务键隔离的单进程单飞语义。

**Architecture:** PostgreSQL 是唯一数据库；知识流水线直接执行，不再经过 SQLite retry。原先面向 SQLite 写竞争的 Scheduler 锁替换为 `process_singleflight(key)`：相同业务 key 互斥，不同 key 可以并发。当前单 backend worker 不引入 advisory lock；跨连接一致性继续依赖事务、唯一约束和任务状态表。

**Tech Stack:** Python 3.11、SQLAlchemy 2.x、PostgreSQL 16、pytest、APScheduler。

## Global Constraints

- 不恢复任何 SQLite 降级路径。
- 不改变 API、LangGraph tool schema、Scheduler job ID 或触发时间。
- 不使用一个全局 Lock 串行化不同业务任务。
- PostgreSQL advisory lock 留到多 backend worker 需求成立时。
- 不覆盖工作区中与本计划无关的已有修改。

---

### Task 1: 删除 SQLite retry 包装器

**Files:**
- Delete: `backend/services/shared/db_retry.py`
- Delete: `backend/tests/test_db_retry.py`
- Modify: `backend/services/knowledge/knowledge_search_service.py`
- Modify: `backend/services/shared/__init__.py`
- Modify: `backend/services/__init__.py`
- Create: `backend/tests/test_postgresql_only_runtime.py`

**Interfaces:**
- `run_knowledge_pipeline_once(...)` 直接调用 `_run_knowledge_pipeline_once_inner(...)`。
- 删除 `call_with_sqlite_retry(...)` 和 `backend.services.db_retry` 兼容别名。

- [ ] **Step 1: 添加失败测试**

```python
def test_runtime_has_no_sqlite_retry_module():
    import importlib.util
    from pathlib import Path

    assert importlib.util.find_spec("backend.services.shared.db_retry") is None
    source = Path("backend/services/knowledge/knowledge_search_service.py").read_text()
    assert "call_with_sqlite_retry" not in source
```

- [ ] **Step 2: 验证 RED**

Run: `DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test .venv/bin/python -m pytest backend/tests/test_postgresql_only_runtime.py -q`

Expected: FAIL，因为旧模块仍存在。

- [ ] **Step 3: 删除包装并直接调用 inner**

```python
return _run_knowledge_pipeline_once_inner(
    trigger=trigger,
    settings=settings,
    classification_limit=classification_limit,
    index_limit=index_limit,
    started=started,
    session=session,
    owns_session=session is None,
    classifier=classifier,
    embedding_provider=embedding_provider,
    vector_store=vector_store,
)
```

- [ ] **Step 4: 验证 GREEN**

Run: `DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test .venv/bin/python -m pytest backend/tests/test_postgresql_only_runtime.py backend/tests/test_knowledge_search_service.py -q`

- [ ] **Step 5: 独立提交**

```bash
git add backend/services backend/tests/test_postgresql_only_runtime.py backend/tests/test_db_retry.py
git commit -m "refactor: remove sqlite retry compatibility"
```

### Task 2: 固化 PostgreSQL-only engine 契约

**Files:**
- Modify: `backend/tests/test_settings.py`
- Modify: `backend/requirements.txt`
- Verify: `backend/db/session.py`

**Interfaces:**
- `make_engine(url)` 拒绝非 PostgreSQL URL。
- PostgreSQL engine 使用标准 QueuePool，不设置 PRAGMA、WAL、StaticPool 或 NullPool。

- [ ] **Step 1: 用 PostgreSQL 契约替换 SQLite PRAGMA 测试**

```python
@pytest.mark.parametrize("url", ["sqlite:///:memory:", "mysql://localhost/test"])
def test_make_engine_rejects_non_postgresql(url):
    with pytest.raises(ValueError, match="Only PostgreSQL"):
        make_engine(url)


def test_make_engine_has_no_sqlite_pool_options(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "backend.db.session.create_engine",
        lambda url, **kwargs: captured.update(url=url, **kwargs) or object(),
    )
    make_engine("postgresql+psycopg2://user@localhost/fund_agent_test")
    assert captured["pool_pre_ping"] is True
    assert "poolclass" not in captured
    assert "connect_args" not in captured
```

- [ ] **Step 2: 运行测试，确认旧默认值和 PRAGMA 断言失败**

Run: `DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test .venv/bin/python -m pytest backend/tests/test_settings.py -q`

- [ ] **Step 3: 删除旧测试与 requirements 中本地 SQLite 注释**

- [ ] **Step 4: 验证 GREEN**

Run: `DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test .venv/bin/python -m pytest backend/tests/test_settings.py backend/tests/test_postgresql_only_runtime.py -q`

- [ ] **Step 5: 独立提交**

```bash
git add backend/db/session.py backend/tests/test_settings.py backend/requirements.txt
git commit -m "test: enforce postgresql-only engine contract"
```

### Task 3: 用 keyed process singleflight 替换全局 Scheduler 锁

**Files:**
- Create: `backend/services/shared/process_singleflight.py`
- Create: `backend/tests/test_process_singleflight.py`
- Modify: `backend/scheduler/scheduler.py`
- Modify: `backend/services/knowledge/knowledge_reindex_jobs.py`
- Modify: `backend/services/shared/__init__.py`
- Modify: `backend/services/__init__.py`
- Delete: `backend/services/shared/scheduler_lock.py`
- Delete: `backend/tests/test_scheduler_lock.py`
- Modify: `backend/tests/test_scheduler.py`
- Modify: `backend/tests/test_knowledge_reindex_jobs.py`

**Interfaces:**
- `process_singleflight(key: str, *, timeout_seconds: float = 0.0) -> ContextManager[None]`。
- `SingleflightBusy(key: str)`。
- 删除 `scheduler_lock`、`SchedulerLockBusy` 和 SQLite 锁所有者状态。

- [ ] **Step 1: 添加相同 key 互斥测试**

```python
def test_same_key_is_singleflight():
    with process_singleflight("knowledge_reindex"):
        with pytest.raises(SingleflightBusy):
            with process_singleflight("knowledge_reindex"):
                pass
```

- [ ] **Step 2: 添加不同 key 可并发测试**

```python
def test_different_keys_do_not_block_each_other():
    with process_singleflight("knowledge_reindex"):
        with process_singleflight("cls_sync"):
            pass
```

- [ ] **Step 3: 验证 RED**

Run: `DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test .venv/bin/python -m pytest backend/tests/test_process_singleflight.py -q`

Expected: FAIL，因为模块尚不存在。

- [ ] **Step 4: 实现 keyed lock registry**

```python
_registry_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}

@contextmanager
def process_singleflight(key: str, *, timeout_seconds: float = 0.0):
    with _registry_guard:
        lock = _locks.setdefault(key, threading.Lock())
    if not lock.acquire(timeout=max(0.0, timeout_seconds)):
        raise SingleflightBusy(key)
    try:
        yield
    finally:
        lock.release()
```

- [ ] **Step 5: 调整 Scheduler 粒度**

`_safe_job(label, fn, ...)` 使用 `process_singleflight(f"scheduler.{label}")`。保留 APScheduler `max_instances=1`，但不同 label 不互相阻塞。

- [ ] **Step 6: 调整知识重建窗口**

`run_job_in_background()` 在整个 pipeline 外层持有固定 key `knowledge_reindex`；重复任务标记 `busy_skipped`。状态写入不再反复获取 SQLite 全局锁。

- [ ] **Step 7: 验证 GREEN**

Run: `DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test .venv/bin/python -m pytest backend/tests/test_process_singleflight.py backend/tests/test_scheduler.py backend/tests/test_scheduler_briefing.py backend/tests/test_knowledge_reindex_jobs.py -q`

- [ ] **Step 8: 独立提交**

```bash
git add backend/scheduler backend/services backend/tests
git commit -m "refactor: replace sqlite scheduler lock with keyed singleflight"
```

### Task 4: 增加运行时代码删除门禁

**Files:**
- Modify: `backend/tests/test_postgresql_only_runtime.py`
- Modify: `backend/db/models.py`
- Modify: `backend/db/repository.py`
- Modify: `backend/services/knowledge/knowledge_reindex_jobs.py`
- Modify: `backend/db/alembic/versions/add_pg_jsonb.py`

**Interfaces:**
- 自动扫描运行时代码，阻止 SQLite 实现重新进入。

- [ ] **Step 1: 添加扫描测试**

```python
FORBIDDEN = ("sqlite://", "PRAGMA ", "StaticPool", "NullPool", "call_with_sqlite_retry")

def test_backend_runtime_has_no_sqlite_implementation():
    roots = [Path("backend/api"), Path("backend/db"), Path("backend/services"), Path("backend/scheduler")]
    offenders = []
    for root in roots:
        for path in root.rglob("*.py"):
            for token in FORBIDDEN:
                if token in path.read_text():
                    offenders.append(f"{path}: {token}")
    assert offenders == []
```

- [ ] **Step 2: 运行并记录 offender**

Run: `DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test .venv/bin/python -m pytest backend/tests/test_postgresql_only_runtime.py -q`

- [ ] **Step 3: 删除 SQLite 实现和误导性运行时注释**

历史迁移说明允许保留在 `docs/` 和 CHANGELOG；运行时代码只描述当前 PostgreSQL 行为。

- [ ] **Step 4: 验收**

```bash
rg -n "sqlite://|PRAGMA|StaticPool|NullPool|call_with_sqlite_retry|scheduler_lock" backend --glob '!tests/**'
.venv/bin/python -m compileall -q backend
git diff --check
DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test SCHEDULER_ENABLED=false \
  .venv/bin/python -m pytest backend/tests/test_postgresql_only_runtime.py \
  backend/tests/test_process_singleflight.py backend/tests/test_scheduler.py -q
```

- [ ] **Step 5: 独立提交**

```bash
git add backend
git commit -m "chore: remove remaining sqlite runtime paths"
```
