# PostgreSQL Test Fixture Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用安全、可并行的 PostgreSQL worker schema fixture 替代所有 SQLite 测试数据库，覆盖普通事务、多连接后台线程和 DDL/pgvector 测试。

**Architecture:** 每个 pytest-xdist worker 创建唯一 schema，连接统一设置 `search_path=<worker_schema>,public`，每个 worker 执行一次 Alembic migration。普通 DB 测试使用外层事务回滚；多连接测试允许真实 commit 并在前后 TRUNCATE；DDL/pgvector 测试使用独立 schema 串行执行。

**Tech Stack:** PostgreSQL 16、pgvector、SQLAlchemy 2.x、Alembic、pytest、pytest-xdist、Docker Compose。

## Global Constraints

- 测试只读取 `TEST_DATABASE_URL`，不得 fallback 到 `DATABASE_URL`。
- 数据库名必须以 `_test` 结尾，否则 pytest session 立即失败。
- schema 名只能由 `master` 或 `gwN` worker ID 生成。
- fixture 只删除当前 worker schema，不删除 database 或 `public` schema。
- 后台线程必须在 teardown 前 join。
- `public` 只承载数据库级 `vector` extension，测试表位于 worker schema。

---

### Task 1: postgres-test 服务、URL 安全校验和 marker

**Files:**
- Modify: `docker-compose.yml`
- Modify: `pytest.ini`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Create: `backend/tests/test_database_safety.py`
- Create: `backend/tests/postgres_fixtures.py`

**Interfaces:**
- Compose profile: `postgres-test`，宿主默认端口 `55432`。
- `validate_test_database_url(url: str) -> URL`。
- markers: `unit`、`db`、`db_multiconnection`、`db_ddl`。

- [ ] **Step 1: 添加 URL 安全失败测试**

```python
@pytest.mark.parametrize("url", [
    "postgresql+psycopg2://u:p@localhost/fund_agent",
    "sqlite:///:memory:",
    "",
])
def test_rejects_unsafe_test_database_url(url):
    with pytest.raises(pytest.UsageError):
        validate_test_database_url(url)
```

- [ ] **Step 2: 运行并确认 RED**

Run: `.venv/bin/python -m pytest backend/tests/test_database_safety.py -q`

- [ ] **Step 3: 添加测试服务**

```yaml
postgres-test:
  profiles: ["test"]
  image: pgvector/pgvector:pg16
  environment:
    POSTGRES_DB: fund_agent_test
    POSTGRES_USER: fund_test
    POSTGRES_PASSWORD: fund_test
  ports:
    - "${POSTGRES_TEST_PORT:-55432}:5432"
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U fund_test -d fund_agent_test"]
    interval: 2s
    timeout: 3s
    retries: 20
```

- [ ] **Step 4: 实现 URL 校验并声明 marker**

只接受 PostgreSQL URL，解析后的 database 必须以 `_test` 结尾。删除 `TEST_PGVECTOR_DATABASE_URL`，pgvector 测试统一使用 `TEST_DATABASE_URL`。

- [ ] **Step 5: 验证 GREEN 并提交**

```bash
.venv/bin/python -m pytest backend/tests/test_database_safety.py -q
git add docker-compose.yml pytest.ini .env.example backend/.env.example backend/tests
git commit -m "test: add disposable postgresql test service"
```

### Task 2: Alembic worker schema 支持

**Files:**
- Modify: `backend/db/alembic/env.py`
- Create: `backend/tests/test_alembic_worker_schema.py`

**Interfaces:**
- 读取 `config.attributes["connection"]` 可选外部 Connection。
- 读取 `config.attributes["version_table_schema"]`。
- migration 表和 `alembic_version` 创建在 worker schema。

- [ ] **Step 1: 添加空 schema upgrade 测试**

```python
@pytest.mark.db_ddl
def test_alembic_upgrades_worker_schema(postgres_admin_engine, worker_schema):
    run_alembic_upgrade(postgres_admin_engine, worker_schema)
    with postgres_admin_engine.connect() as conn:
        tables = conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=:schema"
        ), {"schema": worker_schema}).scalars().all()
    assert "alembic_version" in tables
    assert "fund" in tables
```

- [ ] **Step 2: 验证 RED**

Run: `TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test .venv/bin/python -m pytest backend/tests/test_alembic_worker_schema.py -q`

- [ ] **Step 3: 修改 Alembic online 配置**

```python
external_connection = config.attributes.get("connection")
version_table_schema = config.attributes.get("version_table_schema")

def configure(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=version_table_schema,
        include_schemas=False,
    )
```

有外部连接时直接迁移；没有时保持部署命令创建 engine 的路径。

- [ ] **Step 4: 验证 GREEN 并提交**

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
  .venv/bin/python -m pytest backend/tests/test_alembic_worker_schema.py -q
git add backend/db/alembic/env.py backend/tests/test_alembic_worker_schema.py
git commit -m "test: support alembic worker schemas"
```

### Task 3: Session factory 最小测试接缝

**Files:**
- Modify: `backend/db/session.py`
- Create: `backend/tests/test_session_factory_override.py`

**Interfaces:**
- `set_session_factory(factory: Callable[[], Session]) -> Token`。
- `reset_session_factory(token: Token) -> None`。
- `get_session()` 从当前 ContextVar factory 创建 Session。

- [ ] **Step 1: 添加 override/reset 失败测试**

```python
def test_session_factory_override_is_scoped():
    sentinel = object()
    token = set_session_factory(lambda: sentinel)
    try:
        assert get_session() is sentinel
    finally:
        reset_session_factory(token)
    assert get_session() is not sentinel
```

- [ ] **Step 2: 验证 RED**

Run: `DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test .venv/bin/python -m pytest backend/tests/test_session_factory_override.py -q`

- [ ] **Step 3: 使用 ContextVar 实现**

```python
_session_factory_override = ContextVar("session_factory_override", default=None)

def get_session() -> Session:
    factory = _session_factory_override.get() or SessionLocal
    return factory()
```

后台线程不应隐式继承请求 Session；多连接 fixture 在线程入口显式设置 engine-bound factory。

- [ ] **Step 4: 验证 GREEN 并提交**

```bash
DATABASE_URL=postgresql+psycopg2://review@localhost/fund_agent_test \
  .venv/bin/python -m pytest backend/tests/test_session_factory_override.py backend/tests/test_api_deps.py -q
git add backend/db/session.py backend/tests
git commit -m "refactor: add scoped session factory seam"
```

### Task 4: worker schema 与普通事务 fixture

**Files:**
- Replace: `backend/tests/conftest.py`
- Modify: `backend/tests/postgres_fixtures.py`
- Modify: `backend/tests/test_database_safety.py`

**Interfaces:**
- Session fixtures: `test_database_url`、`worker_schema`、`postgres_engine`。
- Function fixture: `db_session`。
- `@pytest.mark.db` 测试自动使用 connection-bound Session factory。

- [ ] **Step 1: 添加 worker schema 纯函数测试**

```python
@pytest.mark.parametrize(("worker_id", "expected"), [
    ("master", "test_master"), ("gw0", "test_gw0"),
])
def test_worker_schema_name(worker_id, expected):
    assert worker_schema_name(worker_id) == expected

@pytest.mark.parametrize("worker_id", ["../public", "gw0;drop schema public", "worker"])
def test_worker_schema_rejects_uncontrolled_names(worker_id):
    with pytest.raises(ValueError):
        worker_schema_name(worker_id)
```

- [ ] **Step 2: 实现 session 生命周期**

Session 开始时验证 URL、创建 schema、设置 `search_path`、执行 `CREATE EXTENSION IF NOT EXISTS vector` 并运行一次 Alembic。结束时 dispose engine，并在 finally 中删除当前 worker schema。

- [ ] **Step 3: 实现普通事务 fixture**

```python
@pytest.fixture
def db_session(postgres_engine):
    connection = postgres_engine.connect()
    outer = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    token = set_session_factory(factory)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        reset_session_factory(token)
        outer.rollback()
        connection.close()
```

- [ ] **Step 4: 验证被测代码 commit 后仍可回滚**

连续两个测试：第一个 insert + commit，第二个断言记录不存在。

- [ ] **Step 5: 验证并提交**

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
  .venv/bin/python -m pytest backend/tests/test_database_safety.py -q
git add backend/tests
git commit -m "test: add transactional postgresql worker fixture"
```

### Task 5: 多连接与 DDL fixtures

**Files:**
- Modify: `backend/tests/postgres_fixtures.py`
- Create: `backend/tests/test_postgres_multiconnection_fixture.py`

**Interfaces:**
- `db_multiconnection_engine`：允许真实独立连接 commit。
- `db_ddl_schema`：每测试唯一 schema，串行使用。

- [ ] **Step 1: 添加跨连接可见性测试**

连接 A commit 后连接 B 必须立即读到记录；fixture teardown 后下一测试读不到记录。

- [ ] **Step 2: 实现确定性清理**

从 `Base.metadata.sorted_tables` 构造受控表列表，测试前后执行 `TRUNCATE ... RESTART IDENTITY CASCADE`。不得作用于 public schema。

- [ ] **Step 3: 实现 DDL schema**

schema 名为 `test_<worker>_ddl_<uuidhex>`，正则验证后创建和迁移，在 finally 中删除。`db_ddl` marker 在 CI 中 `-n 0` 串行运行。

- [ ] **Step 4: 验证并提交**

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
  .venv/bin/python -m pytest backend/tests/test_postgres_multiconnection_fixture.py -q
git add backend/tests
git commit -m "test: add multiconnection and ddl postgres fixtures"
```

### Task 6: 迁移普通 DB 测试

**Files:**
- Modify: `backend/tests/test_api_funds.py`
- Modify: `backend/tests/test_api_market.py`
- Modify: `backend/tests/test_api_portfolio.py`
- Modify: `backend/tests/test_api_watchlist.py`
- Modify: `backend/tests/test_briefing_service.py`
- Modify: `backend/tests/test_cls_telegraph_sync_service.py`
- Modify: `backend/tests/test_diagnosis_service.py`
- Modify: `backend/tests/test_fund_profile_service.py`
- Modify: `backend/tests/test_fund_service.py`
- Modify: `backend/tests/test_knowledge_fund_matches.py`
- Modify: `backend/tests/test_knowledge_fund_profiles.py`
- Modify: `backend/tests/test_knowledge_ingestion.py`
- Modify: `backend/tests/test_knowledge_search_service.py`
- Modify: `backend/tests/test_market_evidence_ingestion.py`
- Modify: `backend/tests/test_market_intel_service.py`
- Modify: `backend/tests/test_market_service.py`
- Modify: `backend/tests/test_pnl.py`
- Modify: `backend/tests/test_portfolio_history.py`
- Modify: `backend/tests/test_repository.py`
- Modify: `backend/tests/test_scheduled_refresh.py`
- Modify: `backend/tests/test_transactions.py`
- Modify: `backend/tests/test_watchlist_fund_name.py`
- Modify: `backend/tests/test_watchlist_preload_jobs.py`
- Modify: `backend/tests/test_watchlist_service.py`
- Modify: `backend/tests/test_what_if_service.py`

**Interfaces:**
- 使用 `db_session`；文件标记 `pytestmark = pytest.mark.db`。
- 删除本地 engine、`Base.metadata.create_all()` 和逐模块 Session monkeypatch。

- [ ] **Step 1: 每批最多 5 个文件迁移**

原 `session` fixture 改为返回 `db_session`；API dependency override 返回同一 session。不得加入 SQLite 条件分支。

- [ ] **Step 2: 每批运行目标测试**

Run: `TEST_DATABASE_URL=... .venv/bin/python -m pytest <本批文件> -q`

- [ ] **Step 3: 每个领域单独提交**

提交格式：`test: migrate <domain> tests to postgresql`。

- [ ] **Step 4: 验收全部普通 DB 测试**

Run: `TEST_DATABASE_URL=... .venv/bin/python -m pytest -m db -q`

### Task 7: 迁移多连接、后台线程和 lifespan 测试

**Files:**
- Modify: `backend/tests/test_briefing_route.py`
- Modify: `backend/tests/test_knowledge_reindex_jobs.py`
- Modify: `backend/tests/test_knowledge_search_route.py`
- Modify: `backend/tests/test_scheduler.py`

**Interfaces:**
- 使用 `db_multiconnection_engine`。
- 线程入口显式设置 engine-bound Session factory。
- marker: `db_multiconnection`。

- [ ] **Step 1: 删除 StaticPool/共享 SQLite connection**

- [ ] **Step 2: 所有线程增加 join 门禁**

```python
thread.join(timeout=5)
assert not thread.is_alive(), "background thread leaked past test teardown"
```

- [ ] **Step 3: 验证 pending → running → completed/failed 跨连接可见**

Run: `TEST_DATABASE_URL=... .venv/bin/python -m pytest -m db_multiconnection -q`

- [ ] **Step 4: 独立提交**

```bash
git add backend/tests
git commit -m "test: migrate background jobs to postgresql connections"
```

### Task 8: 迁移 DDL、models 和 pgvector 测试

**Files:**
- Modify: `backend/tests/integration/test_pgvector_store.py`
- Modify: `backend/tests/test_knowledge_models.py`
- Modify: `backend/tests/test_knowledge_pgvector.py`
- Modify: `backend/tests/test_knowledge_pgvector_schema.py`
- Modify: `backend/tests/test_knowledge_vector.py`
- Modify: `backend/tests/test_models.py`

**Interfaces:**
- 使用 `db_ddl_schema` 或已迁移的 worker schema。
- 统一使用 `TEST_DATABASE_URL`。

- [ ] **Step 1: 删除 SQLite pgvector no-op/reject 测试**

替换为 PostgreSQL extension 缺失、dimension mismatch 和 transactional rebuild 测试。

- [ ] **Step 2: 将 PRAGMA 索引检查改为 pg catalog**

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = :schema AND tablename = :table
```

- [ ] **Step 3: pgvector 测试不再在 import 时读取 URL或自行建 engine**

- [ ] **Step 4: 串行验证并提交**

```bash
TEST_DATABASE_URL=... .venv/bin/python -m pytest -m db_ddl -q -n 0
git add backend/tests
git commit -m "test: migrate schema and pgvector tests to postgresql"
```

### Task 9: 将可纯化测试改成 unit

**Files:**
- Modify: `backend/tests/test_api_app.py`
- Modify: `backend/tests/test_market_qa_tools.py`
- Modify: `backend/tests/test_what_if_tools.py`
- Modify: `backend/tests/test_knowledge_vector.py`

**Interfaces:**
- 使用 fake Engine/Session/Repository，不连接数据库。
- marker: `unit`。

- [ ] **Step 1: 用窄 fake 替换仅为 dialect 或转发创建的 SQLite engine**

health 使用 `SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))`；tool 转发测试注入 fake session factory。

- [ ] **Step 2: 无测试数据库运行 unit**

Run: `env -u TEST_DATABASE_URL DATABASE_URL=postgresql+psycopg2://unused@localhost/fund_agent_test .venv/bin/python -m pytest -m unit -q`

- [ ] **Step 3: 独立提交**

```bash
git add backend/tests
git commit -m "test: decouple pure unit tests from database"
```

### Task 10: CI、xdist 和 SQLite 删除门禁

**Files:**
- Create: `.github/workflows/backend-tests.yml`
- Modify: `pytest.ini`
- Create: `backend/tests/test_no_sqlite_fixtures.py`
- Modify: `README.md`
- Modify: `DOCKER.md`

**Interfaces:**
- CI jobs: `unit`、`db`、`db_multiconnection`、`db_ddl`。
- repository-wide SQLite fixture scan gate。

- [ ] **Step 1: 添加测试目录扫描门禁**

```python
FORBIDDEN = ("sqlite://", "StaticPool", "PRAGMA ", "TEST_PGVECTOR_DATABASE_URL")

def test_test_suite_has_no_sqlite_fixture():
    offenders = scan_python_files(Path("backend/tests"), FORBIDDEN)
    assert offenders == []
```

- [ ] **Step 2: 配置 CI pgvector service**

`db` 可使用 `-n auto`；`db_multiconnection` 和 `db_ddl` 使用 `-n 0`。每个 job 显式设置 `TEST_DATABASE_URL`。

- [ ] **Step 3: 两 worker 并行验证**

Run: `TEST_DATABASE_URL=... .venv/bin/python -m pytest -m db -n 2 -q`

验证 `test_gw0`、`test_gw1` 独立且 teardown 后删除。

- [ ] **Step 4: 完整验收**

```bash
docker compose --profile test up -d postgres-test
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
  .venv/bin/python -m pytest backend/tests -q
rg -n "sqlite://|StaticPool|PRAGMA|TEST_PGVECTOR_DATABASE_URL" backend/tests
.venv/bin/python -m compileall -q backend
git diff --check
```

Expected: pytest 0 failed/0 errors；`rg` 无命中；worker schema 无残留。

- [ ] **Step 5: 提交门禁和文档**

```bash
git add .github pytest.ini backend/tests README.md DOCKER.md
git commit -m "ci: enforce postgresql-only test suite"
```
