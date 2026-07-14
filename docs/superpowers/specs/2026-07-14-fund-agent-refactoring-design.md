# Fund Agent 重构设计规格书

**版本**: 1.3

**日期**: 2026-07-14

**状态**: 待审批

**替代版本**: 1.2

---

## 1. 背景与目标

### 1.1 项目概述

Fund Agent（公开基金信息整理助手）是一个全栈应用，结合确定性数据后端、定时数据采集、知识库 RAG、LangGraph QA 和 Next.js 前端，为用户提供基金信息管理、市场简报与问答服务。

本次重构完成后，PostgreSQL 16 + pgvector 是项目唯一数据库，覆盖生产部署、本地开发、CLI、Scheduler、LangGraph、单元测试和集成测试。SQLite 不再作为运行时、降级后端或测试替身。

现有约 23 MB 的 `backend/data/fund_agent.db` 仅包含测试数据，不迁移、不对账，也不作为回滚数据源。PostgreSQL 从空库通过 Alembic 建立 schema，测试数据通过 seed/fixture 重新生成。

### 1.2 重构动机

| 类别 | 问题 | 影响 |
|------|------|------|
| 循环依赖 | `graph.model → tools → market_tools → briefing_service → graph.model` | 启动顺序敏感，依赖方向不清 |
| Session 管理 | service 自建 Session 与 API `Depends` 注入并存 | 事务所有权不明确，容易提前提交或泄漏 |
| 大文件 | `WatchlistDrawer.tsx`、`repository.py`、`module_briefing.py` 职责过多 | 修改风险高，难以独立测试 |
| 模块组织 | services 和 repository 按技术层集中，领域边界弱 | import 关系复杂，定位成本高 |
| 类型系统 | Python/TypeScript 中仍有宽泛或隐式类型 | 重构缺少静态保护 |
| 错误处理 | 部分宽异常缺少上下文，部分降级语义未统一 | 故障定位和用户反馈不稳定 |
| 硬编码 | 启动 cwd、临时脚本绝对路径和部分魔法值 | 移植性差 |
| 性能治理 | 缺少基线、查询计划和缓存失效规范 | 难以证明优化有效且正确 |
| 数据库双轨 | 运行时和 39 个测试文件仍包含 SQLite 分支或内存库 | 方言差异掩盖 PostgreSQL 问题，维护成本高 |
| Schema 管理 | Alembic 配置存在重复项、多个初始 revision，启动失败时回退 `create_all` | migration 不是可靠的唯一事实来源 |

### 1.3 重构目标

1. **可维护性**：建立清晰、可验证的领域和依赖边界。
2. **可测试性**：通过显式依赖注入消除反向依赖，保留离线测试能力。
3. **事务可靠性**：统一事务所有权，而不是让每个 service 隐式提交。
4. **可观察性**：规范错误分类、降级结果和结构化日志上下文。
5. **行为兼容性**：保持 API、LangGraph tools、调度语义和持久化数据兼容。
6. **性能可验证性**：只实施有基线、有测量、有失效策略的优化。
7. **数据库单一化**：移除 SQLite 方言、锁、重试、迁移和测试分支，所有持久化行为以 PostgreSQL 为准。

### 1.4 非目标

本次重构不包含：

- 改变公开 API 路径、请求体或响应体。
- 改变 LangGraph tool 名称、参数 schema 或返回结构。
- 引入 Celery、Redis 任务队列或新的 ORM。
- 实现完整多用户系统，或在 `watchlist` 中新增 `user_id`。
- 将 Redis 作为必需依赖；首版缓存仅允许有界进程内缓存。
- 保留或迁移现有 SQLite 测试数据。
- 为不使用数据库的纯函数测试强制创建数据库连接。
- 在纯模块迁移阶段同时修改业务算法。
- 支持多 backend 副本的分布式调度选主；如需支持，另立设计。
- 在 PostgreSQL 切换阶段顺便把全部字符串日期、JSON 字符串和浮点金额改成新的数据库类型；类型现代化另立 migration 和行为测试。

---

## 2. 行为不变量与架构原则

### 2.1 行为不变量

重构过程中以下行为必须保持：

- API 路径、HTTP 状态码和 JSON 字段保持兼容。
- LangGraph tool schema 和 tool-calling 行为保持兼容。
- Scheduler 的 job ID、时区、触发频率、jitter、coalesce、misfire 和单飞语义保持兼容。
- 所有需要数据库的测试必须连接隔离的 PostgreSQL 测试库；仓库中不得再出现 `sqlite://` 测试连接。
- embedding 配置缺失或向量服务不可用时，知识搜索仍可在 PostgreSQL 上返回 `structured_fallback`，不得伪报语义分数。
- pgvector 的 model、version、dimension 和 content hash 校验保持不变。
- 自选、交易、待确认买入、持仓重算和简报幂等结果保持不变。
- 除数据库切换明确涉及的默认值和测试变量外，现有环境变量名称保持兼容。
- QA thread 的 localStorage key 与已保存内容保持兼容；如需变更必须提供迁移函数。
- 旧模块兼容导入在迁移窗口内继续有效。

### 2.2 允许的依赖方向

```text
API / Graph / Scheduler / CLI（组合与入口层）
                    ↓ 显式注入
Application Services（用例编排）
                    ↓
Domain Types / Ports（稳定接口与纯类型）
                    ↓
Repositories / Integrations（数据库与外部数据源适配器）
```

禁止：

- service 反向导入 `graph.model`。
- repository 导入 service、API 或 graph。
- integrations 直接调用 API route。
- 通过全局 Service Locator 隐藏核心依赖。
- 仅用函数内 lazy import 掩盖循环依赖，并把它视为最终解法。

### 2.3 依赖注入策略

不引入全局 `DIContainer`。优先使用：

1. 函数参数注入。
2. 小型构造函数注入。
3. `Protocol` 描述模型、repository、cache 和数据源能力。
4. 在 API、graph、scheduler 或 CLI 入口完成对象组合。

模型可以在组合层缓存，但必须提供显式 reset/override 接口供测试使用，并保证配置变化和并发初始化行为可预测。

### 2.4 渐进式重构原则

- 先补 characterization tests，再移动代码。
- 文件移动、业务修改、数据库迁移分开提交。
- 每个阶段可独立部署和回滚。
- 兼容层必须有删除条件和截止阶段。
- 不以目录看起来整齐作为完成标准，以依赖方向和行为测试为准。

### 2.5 PostgreSQL 单一数据库原则

- `DATABASE_URL` 必须是 PostgreSQL URL；缺失或使用其他方言时应用快速失败。
- `TEST_DATABASE_URL` 必须指向独立、可丢弃且启用 pgvector 的测试数据库。
- 测试安全检查必须拒绝数据库名不含 `_test` 的 URL，避免误清理开发或生产库。
- Alembic 是 schema 的唯一权威；应用启动不得以 `create_all` 掩盖 migration 失败。
- `structured_fallback` 表示检索能力降级，不表示数据库降级。
- PostgreSQL 特有行为可以直接使用，但必须通过测试和 migration 明确表达。

---

## 3. Phase 0：PostgreSQL 单一化与基线护栏

**时间**：3–4 周

**风险等级**：高

### 3.1 建立测试基线

先记录当前测试结果，再将需要数据库的测试统一切换到专用 PostgreSQL 测试服务。推荐在 Compose 中增加 `postgres-test` profile，镜像与生产一致使用 `pgvector/pgvector:pg16`。

目标命令：

```bash
docker compose --profile test up -d postgres-test
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:***@localhost:55432/fund_agent_test \
  .venv/bin/python -m pytest backend/tests -q
cd frontend && npm test
cd frontend && npx tsc --noEmit
cd frontend && npm run build
```

如要把 lint 或 mypy 作为验收项，必须在本阶段先添加对应配置、依赖和脚本，之后不得使用“如果存在”作为验收描述。

### 3.2 PostgreSQL 测试隔离

PostgreSQL fixture 不是连接串替换，而是独立测试基础设施工作包。当前至少 39 个测试文件包含 SQLite 假设，其中约 27 个直接创建或替换 engine/`SessionLocal`，9 个涉及 FastAPI dependency override，至少 3 个验证后台线程或新连接的事务可见性。因此本工作包需要独立估算、实施和验收。

#### 3.2.1 前置：Session factory 可注入缝

完整事务所有权重构仍在 Phase 1，但 Phase 0 必须先建立最小测试接缝：

- API、service、repository 和后台线程从可替换的 Session factory 获取 Session。
- 测试可以一次性把所有新连接指向当前 worker schema。
- 禁止测试继续逐模块 monkeypatch 进程级 `engine`、`SessionLocal` 和 `get_session`。
- 该接缝只改变依赖获取方式，不在本阶段改写业务 commit/rollback 语义。

否则 PostgreSQL fixture 会先复制一套全局 monkeypatch，Phase 1 又必须重写一次。

#### 3.2.2 测试分类与 marker

| 类型 | Marker | 数据库策略 | 并行策略 |
|------|--------|------------|----------|
| 纯单元测试 | `unit` | 不创建数据库连接 | 可并行 |
| 普通 repository/service/API 测试 | `db` | worker schema + 每测试事务/savepoint rollback | worker 内并行需谨慎，默认文件级串行 |
| 多连接/后台线程测试 | `db_multiconnection` | 允许真实 commit，测试前后 `TRUNCATE ... RESTART IDENTITY CASCADE`；必要时每测试独立 schema | 同一 worker 串行 |
| Alembic/DDL/pgvector 重建测试 | `db_ddl` | 独立 schema 或独立测试数据库 | 全局串行 |

原 `TEST_PGVECTOR_DATABASE_URL` 合并为统一的 `TEST_DATABASE_URL`；pgvector 不再是可选数据库测试，而是 PostgreSQL 测试环境的基础能力。

#### 3.2.3 Worker schema 生命周期

- session 级创建一个 PostgreSQL engine。
- 无 xdist 时使用 `test_master` schema；xdist 时使用 `test_gw0`、`test_gw1` 等唯一 schema。
- 每个连接统一设置 `search_path=<worker_schema>,public`；`public` 用于解析数据库级 `vector` extension。
- 每个 worker 只执行一次 Alembic migration，不为每个普通测试重复建 schema。
- worker 结束时只删除自己的 schema，不 drop 整个数据库。
- schema 名称只允许由受控 worker ID 生成，禁止拼接任意测试输入。

#### 3.2.4 普通事务 fixture

普通数据库测试使用：

```text
worker engine
  → connection.begin()
  → Session 绑定 connection
  → begin_nested() savepoint
  → 测试
  → rollback 外层事务
```

如果被测代码调用 `Session.commit()`，fixture 必须通过 SQLAlchemy transaction event 正确重建 savepoint；不得让 commit 逸出到 worker schema。Phase 1 移除内部 commit 后再简化该 fixture。

#### 3.2.5 多连接与后台线程 fixture

以下行为必须在真实独立连接上验证，不能复用普通回滚 fixture：

- API 提交 job 后，后台线程的新 Session 立即可见。
- job 状态在 `pending → running → completed/failed` 间跨连接更新。
- scheduler/manual trigger 的单飞或 advisory lock。
- PostgreSQL 并发 upsert、唯一冲突、deadlock/serialization retry。

此类测试使用专用 marker，允许真实 commit，并通过测试前后的确定性清理恢复 worker schema。只有涉及 schema/extension 变更的测试才创建独立 schema 或数据库。

#### 3.2.6 FastAPI 与后台线程接线

- FastAPI `get_db_session` override 与 application Session factory 使用同一 worker schema。
- TestClient lifespan 不得启动真实 scheduler 或访问开发数据库。
- fake background test 可以继续使用无副作用 Thread；事务可见性测试必须使用真实新 Session。
- 测试结束前必须 join 所有后台线程，超时视为失败，不允许线程泄漏到下一个测试。

#### 3.2.7 安全与清理

- 从 `TEST_DATABASE_URL` 构造 engine，不复用开发 `DATABASE_URL`。
- 数据库名必须以 `_test` 结尾；不满足时在 pytest collection/session start 阶段拒绝运行。
- 清理 SQL 只能作用于受控 worker schema。
- fixture 必须验证 pgvector extension 和 schema revision。
- 测试失败时也必须在 `finally` 中释放连接、停止线程并清理 schema。

#### 3.2.8 工作量估算

| 子任务 | 估算 |
|--------|------|
| `postgres-test`、环境变量和误连保护 | 0.5–1 天 |
| Alembic baseline 与 worker schema 支持 | 1.5–3 天 |
| Session factory 最小注入接缝 | 1–2 天 |
| 普通 transaction/savepoint fixture | 1–2 天 |
| FastAPI override 与 lifespan 整合 | 1–2 天 |
| 多连接、后台线程和 DDL fixture | 2–3 天 |
| 39 个 SQLite 测试文件迁移 | 2–4 天 |
| CI、xdist 和偶发失败治理 | 1–3 天 |

预计 fixture 基础设施为 5–8 个工程日；包含全部测试迁移和稳定性治理为 10–17 个工程日。因此 Phase 0 总工期按 3–4 周规划，不与后续模块化重构共享同一交付承诺。

### 3.3 修复 Alembic 基线

当前 `backend/alembic.ini` 存在重复配置项，migration 目录存在两个独立 initial revision；Phase 0 必须先修复：

- `alembic heads` 必须成功且只返回一个 head。
- 以空 PostgreSQL 数据库为目标建立一条可完整建库的 baseline migration。
- 清理重复或无效的 initial revision，不保留对 SQLite 的条件分支。
- pgvector extension、`knowledge_embeddings` 与索引的 DDL 所有权必须唯一。
- 启动时 migration 失败必须阻止应用进入 ready 状态，不得 fallback 到 `create_all`。
- `create_all` 不再用于应用启动或数据库测试建库。
- 暂不借切换机会批量改变日期、JSON 和金额字段类型；ORM 与 baseline 必须先保持一致。现有 PostgreSQL JSONB migration 若与 ORM 类型不一致，应撤回或延后到独立阶段。

### 3.4 增加契约护栏

补充以下测试：

- FastAPI OpenAPI schema snapshot。
- LangGraph tool 名称、参数和返回 schema snapshot。
- Scheduler job 注册表 snapshot。
- 关键 API response contract tests。
- 关键模块冷启动 import 测试。
- PostgreSQL 空库执行完整 Alembic migration 的测试。
- repository、事务、并发 upsert 和 pgvector 集成测试。
- 应用在数据库不可达、migration 失败和 pgvector schema 不匹配时的启动/健康检查测试。
- QA localStorage 兼容测试。

### 3.5 移除 SQLite 实现

Phase 0 内完成并验证：

- `Settings.database_url` 不再默认到 SQLite，`DATABASE_URL` 缺失时快速失败。
- `make_engine()` 只接受 PostgreSQL，删除 `StaticPool`、`NullPool`、SQLite PRAGMA、WAL 和 `busy_timeout`。
- 删除 `call_with_sqlite_retry` 及其调用；如确需重试，新增针对 PostgreSQL deadlock、serialization failure 和瞬时连接错误的有限重试策略。
- 删除 SQLite 专用补列、重建表、方言检测和测试。
- 删除 scheduler 中只为 SQLite 全局写锁存在的逻辑，但保留业务单飞语义。
- 把所有 `sqlite:///:memory:` fixture 迁移到统一 PostgreSQL fixture。
- 更新 `.env.example`、`backend/.env.example`、README、DOCKER.md、pytest markers 和开发命令。

SQLite 文件不在代码切换提交中自动删除。完成 PostgreSQL 全量验证后，单独删除 `fund_agent.db`、`-wal`、`-shm`，并在 CHANGELOG 明确旧测试数据不会保留。

### 3.6 性能基线

在固定数据集和固定运行环境下记录：

- `/api/watchlist`、知识搜索和市场页面接口 P50/P95。
- Watchlist 页面和 Drawer 打开后的请求数。
- 简报生成、知识流水线和 CLS 同步耗时。
- 关键 SQL 查询数量和查询计划。
- PostgreSQL 连接池等待、锁等待、deadlock/serialization retry 次数。

没有基线的数据不进入 Phase 4 性能优化。

### 3.7 全项目影响清单

Phase 0 至少覆盖以下位置：

| 范围 | 当前问题 | 目标状态 |
|------|----------|----------|
| `backend/config/settings.py` | 默认 SQLite URL、连接池注释按方言分支 | PostgreSQL URL 必填，连接池参数统一 |
| `backend/db/session.py` | SQLite pool/PRAGMA 与通用分支共存 | 仅 PostgreSQL engine factory |
| `backend/db/init_db.py` | SQLite 手写迁移、`create_all`、pgvector DDL 混合 | Alembic 权威，运行时只做非破坏性健康校验 |
| `backend/alembic.ini`、`db/alembic/` | 重复配置、多个 initial、SQLite URL | 单配置、单 baseline、单 head |
| `backend/api/app.py` | migration 失败 fallback `create_all`，硬编码 cwd | 部署先 migration；启动失败显式退出或 not-ready |
| `backend/services/db_retry.py` | SQLite lock retry | 删除或替换为窄范围 PostgreSQL retry |
| `backend/services/scheduler_lock.py` | SQLite/PG 方言分支 | 业务单飞 + PostgreSQL advisory lock/原子抢占 |
| knowledge services | SQLite structured fallback 与 pgvector factory 混杂 | PostgreSQL 始终为事实库；向量不可用时仅检索模式降级 |
| ORM models/repositories | 注释和部分实现为 SQLite 兼容妥协 | 清理方言注释；保持本阶段字段语义不变 |
| `backend/tests/` | 至少 39 个文件包含 SQLite fixture/假设 | 纯单元测试无 DB，其余统一 PostgreSQL fixture |
| `pytest.ini`、`conftest.py` | pgvector 可选、缺少测试库安全保护 | PostgreSQL/pgvector 为标准测试基础设施 |
| Compose/环境示例 | 开发默认仍可选择 SQLite | 开发、测试、部署均声明 PostgreSQL 服务与 URL |
| README/DOCKER/scripts | 混合启动、备份和故障说明 | 统一 PostgreSQL 初始化、备份、恢复和测试命令 |

删除 SQLite 后仍允许在文档的迁移记录和 CHANGELOG 中出现“SQLite”字样；运行时代码、配置默认值和测试连接中不得继续存在 SQLite 支持。

---

## 4. Phase 1：事务、依赖与错误边界

**时间**：2–3 周

**风险等级**：高

### 4.1 消除 graph/service 循环依赖

将模型能力定义为稳定端口，由组合层注入：

```python
from typing import Protocol, Any, TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class ChatModel(Protocol[InputT, OutputT]):
    """聊天模型的最小接口定义"""

    def invoke(self, input: InputT, **kwargs: Any) -> OutputT: ...


def compose_briefing(
    snapshot: Snapshot,
    *,
    model: ChatModel[str, str],
) -> BriefingResult:
    """briefing 组装函数，模型由调用方注入"""
    ...
```

实施步骤：

1. 为当前循环依赖增加 import 回归测试。
2. 提取 briefing 输入、输出和 profile 类型。
3. 让 `briefing_service` 与 `module_briefing` 接受模型参数或 factory。
4. 在 graph/scheduler/API 组合层构造并注入模型。
5. 删除 service 对 `backend.graph.model` 的依赖。
6. 测试中直接注入 fake model，不修改全局单例。

### 4.2 统一事务所有权

采用“顶层入口拥有事务”的规则：

- API 写路由负责 request transaction。
- Scheduler job 和后台线程各自创建并拥有 Session。
- CLI/维护脚本使用顶层 `session_scope()`。
- service 接收外部 Session 时只允许 `flush()`，不得 `commit()`、`rollback()` 或 `close()`。
- repository 不拥有事务。
- 后台线程不得复用请求 Session。
- LLM、embedding 和网络请求原则上不应在长事务内执行；需要持久化状态时拆成短事务阶段。

```python
from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """
    顶层事务上下文管理器。

    用途：
    - CLI/维护脚本的顶层入口
    - Scheduler job 的事务边界
    - 后台线程的事务边界

    注意：
    - service 接收外部 Session 时不得调用此函数
    - service 只允许 flush()，不得 commit/rollback/close
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

迁移顺序：

1. 建立事务所有权测试。
2. 标记所有 `owns/session is None` 路径。
3. 先迁移知识任务、简报任务等高风险后台流程。
4. 再迁移 API 和普通 services。
5. 删除内部隐式 commit。
6. 验证异常时整个用例可以回滚。

### 4.3 错误分类与日志

业务异常至少包含：

- `FundAgentError`
- `ResourceNotFoundError`
- `InputValidationError`
- `DataSourceError`
- `DataSourceTimeoutError`
- `DatabaseConflictError`
- `DependencyUnavailableError`

错误处理矩阵：

| 类别 | 行为 | 日志 | 重试 | API 映射 |
|------|------|------|------|----------|
| 参数错误 | 立即失败 | info | 否 | 400/422 |
| 资源不存在 | 立即失败 | info | 否 | 404 |
| 外部源超时 | 降级或失败 | warning | 有限重试 | 502/504 |
| 数据库冲突 | 回滚 | warning | 视方言 | 409/503 |
| 可选依赖失败 | 显式降级 | warning | 可选 | 200 + warning |
| 程序缺陷 | 失败 | exception | 否 | 500 |

规范：

- 禁止 `except Exception: pass`。
- 允许在进程、线程、外部数据源和降级边界捕获宽异常，但必须记录上下文或返回显式降级状态。
- 日志不得包含 API key、数据库密码、完整持仓或未经脱敏的外部响应。
- 跨模块日志统一携带 `job_id`、`fund_code`、`source`、`stage` 等可用上下文。

### 4.4 清理硬编码

- 启动路径基于项目根或配置解析，不写死 `/Users/...`。
- 临时 patch 脚本退出正式运行路径。
- timeout、batch size、TTL 等运行参数进入 Settings；纯协议常量保留代码常量。
- 新增配置必须提供默认值、环境变量说明和测试。

---

## 5. Phase 2：模块化迁移

**时间**：3–4 周

**风险等级**：中

### 5.1 Briefing 边界

不以“合并两个大文件”为目标，而是按职责拆分：

```text
backend/services/briefing/
├── types.py          # 输入、输出、profile、envelope
├── collectors.py     # 快照与证据收集
├── modules.py        # 确定性模块 builders
├── composer.py       # LLM 编排
├── persistence.py    # 简报读写用例
└── jobs.py           # 异步触发和运行状态
```

`module_briefing.py` 和 `briefing_service.py` 先变为兼容 re-export，内部消费者迁移完成后再删除。

### 5.2 Repository 拆分

```text
backend/db/repositories/
├── fund.py
├── watchlist.py
├── market.py
├── briefing.py
├── knowledge.py
└── jobs.py
```

规则：

- 不引入无实际行为的 `BaseRepository`。
- repository 接收 Session，不自行创建或提交。
- 迁移时不得改变 SQL、排序、幂等键和返回结构。
- 原 `repository.py` 暂时 re-export 新函数。
- 使用 import compatibility tests 验证新旧入口一致。

### 5.3 Services 按领域分组

```text
backend/services/
├── fund/
├── watchlist/
├── market/
├── briefing/
├── knowledge/
└── shared/
```

模块移动分两步：先建立新路径和兼容导出，再批量迁移内部 import。不得在同一提交中同时移动文件并大改业务算法。

### 5.4 外部数据源适配器

```text
backend/integrations/
├── protocols.py
├── registry.py
├── akshare/
├── cls/
├── cninfo/
├── fred/
└── policy/
```

每个适配器必须定义：

- timeout 和 retry 所有权。
- 输入、规范化输出和 source metadata。
- 可重试异常与永久异常。
- 测试 fixture，不依赖真实网络。
- 限流和降级行为。

### 5.5 Scheduler 解耦

```python
from dataclasses import dataclass, field
from typing import Callable, Literal, Mapping

from typing_extensions import NotRequired


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Job 定义规范"""

    id: str  # 唯一标识，用于单飞和日志
    callable: Callable[[], object]  # 执行逻辑
    trigger: Literal["cron", "interval"]  # 触发类型
    trigger_kwargs: Mapping[str, object]  # 触发参数
    max_instances: int = 1  # 最大并发实例数
    coalesce: bool = True  # 是否合并错过触发
    misfire_grace_time: NotRequired[int | None] = None  # 错过触发宽限期
    jitter: NotRequired[int | None] = None  # 随机延迟（秒）
```

Scheduler 只注册和触发 job，但必须保留：

- 原 job ID、时区和触发参数。
- 手动触发、定时触发和后台线程之间的业务单飞语义。
- 单进程内使用轻量锁；需要跨连接互斥的 job 使用命名 PostgreSQL advisory lock 或任务表原子抢占，不再依赖数据库方言分支。
- advisory lock 必须使用稳定 key、独立短连接并在 `finally` 中释放；连接中断时依赖 PostgreSQL 自动释放。
- advisory lock key 命名约定：`fund_agent.<category>.<resource>`，例如 `fund_agent.scheduler.daily_briefing`；key 必须为 64 位整数，通过哈希稳定名称生成。
- job 状态、失败日志和 shutdown 行为。
- 单 backend worker 的当前部署约束。

### 5.6 前端组件拆分

`WatchlistDrawer` 按“容器、领域 hooks、表单、展示组件”拆分，而不是只按视觉 Tab 拆分：

```text
frontend/src/components/watchlist-drawer/
├── WatchlistDrawer.tsx
├── hooks/
│   ├── useWatchlistDrawerData.ts
│   └── useWatchlistMutations.ts
├── tabs/
├── forms/
└── shared/
```

`qa/page.tsx` 拆分为线程持久化、LangGraph streaming、消息展示和工具卡片。拆分过程中保持 localStorage schema、流式状态机和 URL 行为兼容。

---

## 6. Phase 3：前端状态与类型治理

**时间**：1–2 周

**风险等级**：中

### 6.1 React Query 统一

React Query 已在项目中使用，本阶段不是重新引入，而是统一现有策略：

- 集中 query key factory。
- 明确 `staleTime`、`gcTime`、retry、refetchInterval。
- mutation 只失效必要 query。
- 将剩余手写 polling 迁移到 React Query。
- 服务端状态不得复制到 Zustand。

状态边界：

- 服务端状态：React Query。
- 局部 UI 状态：React state/reducer。
- 跨刷新客户端状态：localStorage 或持久化 store。

除非出现三个以上跨页面共享、非服务端状态的真实用例，否则不引入 Zustand。

### 6.2 TypeScript 类型

- API client 使用明确 DTO，禁止无依据的 `any`。
- 错误 payload 先作为 `unknown` 解析。
- 使用 discriminated union 表达 loading/success/degraded/error。
- 仅在运行时校验后使用类型收窄。
- `npx tsc --noEmit` 和 production build 纳入每阶段验收。

---

## 7. Phase 4：基于测量的性能优化

**时间**：1–2 周

**风险等级**：中

### 7.1 数据库优化

流程：

1. 从 Phase 0 基线选择慢路径。
2. PostgreSQL 使用 `EXPLAIN (ANALYZE, BUFFERS)`。
3. 检查现有唯一约束和索引是否已覆盖。
4. 添加 Alembic migration。
5. 对比读延迟、写放大和索引大小。
6. 无显著收益则撤销。

注意：当前 `fund_nav` 字段为 `nav_date`，且已有 `(fund_code, nav_date)` 唯一约束；当前 `watchlist` 没有 `user_id`。不得为不存在的查询模式预建索引。

### 7.2 批量 upsert

优先检查 select-then-insert 的竞态和 N+1，不仅追求速度：

- 使用 PostgreSQL `INSERT ... ON CONFLICT` 或 SQLAlchemy PostgreSQL dialect upsert。
- 唯一冲突必须转化为可预期结果。
- 批次失败的原子性必须有测试。
- 并发测试必须使用真实独立连接，不能只在单 Session 内模拟。

### 7.3 有界缓存

首版只实现进程内缓存，并满足：

- 最大容量和明确淘汰策略。
- 使用 `time.monotonic()`。
- 并发安全和测试 reset。
- 写操作后的主动失效。
- 明确空值、异常和降级结果是否缓存。
- 防止同 key 并发击穿。
- 缓存关闭时业务结果一致。

Embedding cache key 必须至少包含：

```text
provider + model + version + dimensions + text_hash
```

多 worker 下进程内缓存不保证一致；Redis 留待独立设计。

### 7.4 性能验收

- 目标路径 P95 至少改善 20%，否则不保留新增复杂度。
- 页面请求数不得增加。
- 不新增 N+1 查询。
- 缓存命中率和淘汰可观察。
- scheduler 运行时长和数据库锁等待不得恶化。

---

## 8. PostgreSQL Schema 与迁移策略

> **说明**：本节描述的 Schema 管理原则适用于所有 Phase，具体实施细节在 Phase 0 完成。

### 8.1 Schema 权威来源

- Alembic 是开发、测试和生产 schema 变更的唯一权威路径。
- `Base.metadata.create_all()` 不用于应用启动、测试建库或生产恢复。
- pgvector extension、向量表和索引的 DDL 所有权必须保持单一，不能同时由 Alembic 和启动补丁重复演进。
- Alembic online/offline 模式都从显式 PostgreSQL URL 获取连接，不在 ini 中保留 SQLite URL。
- 每次提交后 `alembic heads` 必须只有一个 head，并验证 `upgrade head` 可在空库执行。
- 自动生成 migration 后必须人工审查 PostgreSQL 类型、server default、约束和 downgrade。

### 8.2 必测路径

- 空 PostgreSQL 初始化。
- 现有 PostgreSQL schema 升级。
- pgvector extension 缺失、dimension mismatch 和重建路径。
- upgrade 失败后的应用启动行为。
- 多个并发应用实例尝试 migration 时的部署约束；默认由部署步骤先迁移，再启动应用，不由每个 worker 并发迁移。

### 8.3 部署与回滚

- SQLite 测试数据不迁移、不备份、不对账。
- PostgreSQL 产生真实业务数据后，后续生产 migration 前必须执行并验证 `pg_dump` 备份。
- schema 先后兼容时采用 expand/migrate/contract。
- 代码回滚不得依赖已被删除的列。
- 破坏性 migration 必须单独审批，不能夹在模块重构提交中。
- 首次切换的回滚方式是回退代码并重建测试环境，不恢复旧 SQLite 数据。

### 8.4 环境与部署拓扑

| 环境 | 数据库 | 建库方式 | 数据策略 |
|------|--------|----------|----------|
| 本地开发 | Compose `postgres` | `alembic upgrade head` | Docker volume 持久化 |
| pytest | Compose `postgres-test` | session 开始执行 Alembic | 事务或独立 schema 清理 |
| CI | CI service/container pgvector:pg16 | 每次从空库 migration | job 结束销毁 |
| 部署 | Compose `postgres` | 部署步骤先 migration，再启动应用 | `pg_dump` + volume |

配置要求：

- 开发和部署使用 `DATABASE_URL`。
- 测试只使用 `TEST_DATABASE_URL`，不得 fallback 到 `DATABASE_URL`。
- backend 与 LangGraph 连接同一 PostgreSQL 实例时使用不同连接池预算，并纳入总连接数计算。
- `docker compose down` 默认保留 PostgreSQL volume；只有明确执行带 `-v` 的破坏性命令才删除数据。
- readiness 必须依赖数据库连接与 schema revision，liveness 不执行昂贵查询。

---

## 9. 兼容迁移、发布与回滚

### 9.1 兼容导入生命周期

1. 新建模块并保持旧模块 re-export。
2. 添加新旧 import 等价测试。
3. 迁移仓库内部 import。
4. 使用 `rg` 验证无旧路径消费者。
5. 兼容层保留至下一阶段稳定完成。
6. 删除兼容层并记录 CHANGELOG。

禁止无限期保留两套实现。

### 9.2 提交与 PR 边界

> **说明**：以下顺序为 Phase 0–4 的实施顺序，也是推荐提交 PR 的顺序。每个 Phase 可根据需要拆分为多个 PR，但不应跨 Phase 混合提交。

Phase 0：PostgreSQL 单一化

1. 修复 Alembic 配置和单一 PostgreSQL baseline。
2. 建立 `postgres-test`、安全检查和统一 pytest fixture。
3. 迁移数据库测试并删除 SQLite 运行时代码。
4. 建立 characterization/contract tests。
5. Session factory 最小可注入接缝。

Phase 1：事务、依赖与错误边界

6. 稳定类型与 Protocol（业务异常类体系）。
7. 依赖方向修复（消除 graph/service 循环依赖）。
8. 事务所有权迁移（移除 service 内部 commit）。

Phase 2：模块化迁移

9. repository 纯移动（按领域拆分）。
10. services/integrations 纯移动（按领域分组）。
11. 前端纯拆分（组件拆分）。

Phase 3–4：前端治理与性能优化

12. React Query 统一与 TypeScript 类型治理。
13. 性能基线建立与优化实施。

每个 PR 必须可独立回滚，不把 schema 破坏性变更和大规模文件移动混在一起。

### 9.3 运行期开关

缓存和高风险优化必须支持通过 Settings 关闭。纯模块路径迁移不使用永久 feature flag；短期双路径只能用于验证，并有明确删除阶段。

---

## 10. 风险与缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 事务提前提交或部分成功 | 中 | 高 | 顶层事务所有权、失败回滚测试 |
| 循环依赖被延迟导入掩盖 | 中 | 高 | 依赖方向规则、import 测试、显式注入 |
| 模块移动造成兼容破坏 | 中 | 中 | re-export、契约测试、分阶段删除 |
| Scheduler 参数或锁语义丢失 | 中 | 高 | job snapshot、并发和 shutdown 测试 |
| 测试误连开发或生产 PostgreSQL | 低 | 极高 | `TEST_DATABASE_URL`、`_test` 名称硬校验、禁止复用 `DATABASE_URL` |
| Alembic 多 head 或 baseline 不完整 | 高 | 高 | Phase 0 修复配置、单 head 门禁、空库升级测试 |
| PostgreSQL 测试变慢或并行冲突 | 中 | 中 | session engine、事务回滚、worker 独立 schema |
| savepoint 隔离被 service 内部 commit 绕过 | 高 | 高 | transaction event 重建 savepoint、Session factory 接缝、Phase 1 删除内部 commit |
| 后台线程连接错误 schema 或线程泄漏 | 中 | 高 | 统一 Session factory、固定 search_path、强制 join/finally 清理 |
| 删除 SQLite 分支遗漏 | 中 | 中 | `rg sqlite` 清单、禁止方言测试、代码审查 |
| PostgreSQL advisory lock 使用错误 | 低 | 高 | 稳定 key、独立连接、并发与异常释放测试 |
| 缓存返回陈旧持仓或向量 | 中 | 高 | 主动失效、版本化 key、关闭开关 |
| 前端拆分破坏流式状态 | 中 | 高 | reducer/streaming characterization tests |
| 错误治理误删必要降级 | 中 | 中 | 错误矩阵，边界允许宽异常但必须可观察 |
| 工期因范围过大失控 | 中 | 高 | 非目标、PR 边界、阶段审批 |

---

## 11. 验收标准

### 11.1 每阶段通用门禁

- [ ] 后端纯单元测试和 PostgreSQL 数据库测试通过。
- [ ] 前端 `npm test` 通过。
- [ ] `npx tsc --noEmit` 通过。
- [ ] 前端 production build 通过。
- [ ] OpenAPI 和 tool schema 无未审批变化。
- [ ] 仓库运行时代码和测试中无 `sqlite://`、SQLite PRAGMA 或 SQLite retry 路径。
- [ ] `alembic heads` 成功且只有一个 head，空 PostgreSQL 数据库可 `upgrade head`。
- [ ] pgvector extension、schema、upsert、检索和重建测试通过。
- [ ] 无新增吞错路径。
- [ ] 文档、环境变量示例和 CHANGELOG 已更新。

### 11.2 Phase 0 数据库切换验收

> **Phase 0 交付物说明**：Phase 0 不仅完成 SQLite → PostgreSQL 的迁移，还包括 Session factory 最小可注入接缝（详见 3.2.1），该接缝是 Phase 1 事务所有权迁移的基础。

- [ ] `DATABASE_URL` 缺失或不是 PostgreSQL 时应用快速失败。
- [ ] `TEST_DATABASE_URL` 不以 `_test` 数据库结尾时 pytest 拒绝启动。
- [ ] 所有原 SQLite 数据库测试已迁移到 PostgreSQL fixture。
- [ ] `unit`、`db`、`db_multiconnection`、`db_ddl` marker 的执行边界有文档和 CI job。
- [ ] 普通测试通过事务/savepoint 隔离，service 内部 commit 不会污染后续测试。
- [ ] pytest-xdist 每个 worker 使用唯一 schema，所有连接的 `search_path` 包含 worker schema 和 `public`。
- [ ] 多连接测试使用真实独立连接并验证提交可见性，结束后确定性清理。
- [ ] DDL/pgvector 重建测试串行运行，不与普通 transaction fixture 混用。
- [ ] FastAPI dependency override 和后台线程 Session factory 指向同一测试 schema。
- [ ] 后台线程全部在测试结束前 join，无连接或线程泄漏。
- [ ] 应用启动不再 fallback 到 `create_all`。
- [ ] SQLite 文件删除前已完成后端全量、API、scheduler 和 pgvector 验证。
- [ ] 文档明确旧 SQLite 测试数据不保留。

### 11.3 Phase 1 验收

- [ ] service 不再导入 `backend.graph.model`。
- [ ] 关键 service 的核心依赖可由测试显式注入。
- [ ] 外部 Session 不被 service commit/close。
- [ ] 后台线程创建独立 Session。
- [ ] 组合用例失败可完整 rollback。
- [ ] 错误分类和降级状态有测试。

### 11.4 Phase 2 验收

- [ ] 新旧 import 在兼容窗口内等价。
- [ ] `repository.py` 和旧 service 文件只保留兼容导出，无双实现。
- [ ] Scheduler 注册快照不变。
- [ ] Watchlist、QA 和 briefing 的行为测试不变。

### 11.5 Phase 3 验收

- [ ] React Query query key、失效和 polling 策略有测试。
- [ ] QA localStorage 和 streaming 行为保持兼容。
- [ ] TypeScript 无新增 `any`，类型检查和 production build 通过。

### 11.6 Phase 4 验收

- [ ] 优化前后基线可复现。
- [ ] P95 达到目标或撤销优化。
- [ ] 新索引有 migration 和查询计划证据。
- [ ] 缓存失效、容量、并发和关闭路径有测试。

---

## 12. 交付物

每个阶段至少交付：

- 对应代码与测试。
- 架构或行为变化说明。
- 可复制执行的验证命令及结果。
- 数据库 migration 与回滚说明（如涉及）。
- 兼容层新增/删除清单。
- 性能基线与对比结果（如涉及）。

---

## 13. 后续独立议题

以下内容需要单独设计，不作为本规格书的隐含范围：

1. 多 backend worker/副本的分布式 scheduler 选主。
2. Redis 缓存与跨进程一致性。
3. 用户认证、授权和多租户数据模型。
4. APM、业务指标和告警体系。
5. PostgreSQL 原生 JSONB/全文检索的进一步利用。
6. CI/CD 与生产自动回滚。

---

## 附录 A：术语

| 术语 | 定义 |
|------|------|
| Composition Root | API、Graph、Scheduler 或 CLI 中负责构造并连接依赖的入口 |
| Transaction Owner | 决定 commit、rollback 和 close 的最外层用例 |
| Characterization Test | 固定现有行为、防止重构无意改变结果的测试 |
| Compatibility Re-export | 旧模块临时从新模块重新导出符号的迁移方式 |
| Structured Fallback | 向量能力不可用时使用结构化过滤和关键词召回的降级模式 |
| Expand/Migrate/Contract | 先扩展兼容 schema，再迁移数据，最后删除旧结构的发布策略 |
| Protocol | Python typing.Protocol，定义结构化子类型接口 |
| Advisory Lock | PostgreSQL 命名锁，用于跨连接互斥 |
| Worker Schema | pytest-xdist 并行测试中每个 worker 的独立 schema |
| slots=True | dataclass 内存优化，禁用 `__dict__` |

## 附录 B：参考资料

- SQLAlchemy 2.0 Session 与事务文档
- FastAPI Dependencies 与 OpenAPI 文档
- Alembic migration 文档
- TanStack Query 文档
- Martin Fowler《Refactoring》
