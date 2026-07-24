# Fund Agent 可维护性优先纵向切片设计

**版本**：1.0

**日期**：2026-07-24

**状态**：已完成口头确认，待书面审阅

**适用周期**：未来六个月持续开发当前项目

**首个实施范围**：可信基线、最低质量门禁、原子新增自选及前端即时一致性

## 1. 摘要

未来六个月继续开发 Fund Agent 时，优化重点不是提前抽取跨项目通用包，而是降低本项目
每次修改的理解成本、影响范围和回归风险。采用“可维护性优先的渐进式纵向切片”：

1. 先恢复可信测试基线；
2. 补齐最低限度的前后端质量门禁；
3. 每次选择一条完整用户路径，从 API、应用用例、事务、Repository、后台任务一直迁移到
   前端 Feature、缓存策略和行为测试；
4. 每个切片保持公开契约兼容、可以独立验证和整体回滚；
5. 只有当同一稳定边界在项目内被至少两个真实场景复用后，才考虑抽成更通用的内部组件
   或独立包。

首个纵向切片确定为：

> 原子化 `POST /api/watchlist` 新增自选，并在数据库提交成功后启动可选的数据预热；前端在
> POST 成功后立即显示自选记录，不等待预热完成。

该切片非破坏性、公开面较小，却能同时建立应用用例、Unit of Work、并发幂等、后台任务
交接、类型化错误、Feature 边界和组件行为测试的参考实现。

## 2. 与现有设计的关系

本设计是 `2026-07-14-fund-agent-refactoring-design.md` 的执行收敛，不重写已完成的
PostgreSQL、领域目录、Scheduler、WatchlistDrawer 和 React Query 治理成果。

以下已确认设计继续提供背景和已交付契约：

- `docs/superpowers/specs/2026-07-14-fund-agent-refactoring-design.md`
- `docs/superpowers/decisions/0002-transaction-ownership.md`
- `docs/superpowers/specs/2026-07-16-scheduler-hard-cut-design.md`
- `docs/superpowers/specs/2026-07-16-watchlist-drawer-hard-cut-design.md`
- `docs/superpowers/specs/2026-07-17-react-query-governance-design.md`

本设计修正两处“文档状态已经完成、生产接线仍有偏差”的现状：

1. ADR-002 声明 API 写路由使用请求事务，但 `POST /api/watchlist` 当前先后调用
   `get_one()` 和 `add_full()`，两次调用分别由 Service 打开事务；`get_db_session()`
   本身也不会在正常请求结束时提交。
2. Scheduler 硬切换设计要求 `start_scheduler()`、`shutdown_scheduler()` 保留同步签名和
   返回行为；当前工作区暂存修改将它们改成 coroutine，而同步调用方和测试没有原子迁移。

因此，现有 ADR 和硬切换文档仍是目标约束，但不能把声明过的“已实施”直接当作当前生产
行为的证据。实施时必须以代码、契约测试和可复现验证结果三者一致为完成标准。

对于事务所有权，本设计明确修订 ADR-002：

- ADR-002 中 Repository 只 flush、Service 不 commit、后台线程使用独立 Session、网络
  调用不占用长事务等规则继续有效；
- “API 写路由使用 `Depends(get_db_session)`，事务由 Service/Dependency 间接完成”的
  规则只描述尚未迁移的旧路径；
- 已迁移的写路径以本设计为准：Route 只做 HTTP 映射，Application Use Case 通过 Unit of
  Work 显式决定 commit/rollback；
- 首个业务切片必须同步更新 ADR-002 的状态和适用范围，不能让两个事务规则长期都标为
  全局有效。

## 3. 当前基线与问题

### 3.1 验证基线

截至本设计整理时：

- 后端收集到 1,707 个测试，其中 996 个标记为 `unit`；
- 当前 unit 分区结果为 990 通过、6 失败、711 deselected；
- 6 个失败均来自 Scheduler 生命周期同步契约与 coroutine 实现不一致，并伴随未
  `await` 警告；
- 前端 105 个测试通过；
- TypeScript strict 检查 `npx tsc --noEmit` 通过；
- 后端 `compileall` 通过；
- 本地未重新运行完整 PostgreSQL 分区，完整数据库验证由修复后的 CI 执行；
- 当前 CI 只安装 Python、运行后端 pytest 分区和 `compileall`，没有前端 test、
  typecheck 或 production build。

这意味着项目测试数量充足，但当前没有全绿、跨前后端的可信基线，不能直接开始结构重构。

### 3.2 主要维护性问题

| 问题 | 当前表现 | 开发影响 |
|---|---|---|
| 事务所有权不一致 | API request Session、Service `session_scope()` 和后台任务短事务并存 | 同一用例可能部分成功，回滚边界难推断 |
| 依赖方向未完全单向 | `fund_service` 与 `diagnosis_service` 存在双向依赖 | 修改或测试任一侧都需要理解另一侧 |
| Route/Service/Repository 职责渗漏 | Route 查 ORM，Service 直接写 SQLAlchemy 或启动任务 | 无法独立替换和测试编排 |
| 外部数据与持久化混合 | `data_collector.py` 同时处理采集、重试、线程和数据库 | 文件过大，失败模式互相耦合 |
| 前端缓存副作用重复 | 详情页、表格、批量刷新、Drawer 和 polling 各自列缓存 key | 新增一个缓存消费者时容易漏失效 |
| 页面和类型过宽 | Briefing 页面承担请求、轮询、渲染和反馈，DTO 大量可选 | 局部改动缺少明确边界 |
| 测试实现耦合 | 部分前端测试读取源码并匹配字符串或正则 | 安全重构会触发无业务意义的失败 |
| 质量门禁不完整 | 前端测试、类型和构建不在 CI | 本地通过不能保证提交后仍可集成 |
| 兼容层持续累积 | `backend/services/__init__.py` 安装 33 个旧模块别名 | 真实依赖路径被隐藏，清理没有单调目标 |

### 3.3 已有优势

本设计不否定现有治理成果，而是建立在以下能力上：

- PostgreSQL 测试安全检查和分区 fixture；
- Service/Repository 禁止 `commit()`、`rollback()`、`close()` 的 AST 契约；
- Scheduler 注册表快照；
- `queryKeys` 与 `queryPolicy` 集中定义；
- WatchlistDrawer 和 QA 已按领域目录拆分；
- TypeScript strict；
- 外部 Provider Protocol 和 Briefing 稳定类型已经有部分基础。

## 4. 目标与非目标

### 4.1 目标

未来六个月的目标是：

1. 一项业务变更主要发生在一个 Feature 或 Use Case 内，而不是同时散落在多个页面和
   Service；
2. 一次业务操作只有一个明确的事务所有者；
3. Route 不写 SQL，Repository 不编排业务，Provider 不访问数据库；
4. 内部实现重构时，只要外部行为不变，大多数测试不需要修改；
5. 前端 mutation 的缓存影响由 Feature 统一声明；
6. 依赖方向可由自动化规则验证；
7. 每个迁移切片都有基线、验收、停止条件和整体回滚方式；
8. 复用来自稳定职责和窄接口，不来自提前建设抽象框架。

### 4.2 非目标

本设计不包含：

- 全仓库一次性重写或大规模目录重排；
- 抽取可发布的跨项目 Python/TypeScript 包；
- 引入 Celery、Redis、持久化 job store、Outbox 或新的 ORM；
- 修改数据库 schema 或迁移已有数据；
- 修改公开 API 路径、成功状态码或已有成功响应字段；
- 在首个切片中迁移 initial-holding、PATCH、DELETE、交易、定投或申购中流程；
- 在首个切片中改变 preload interval、最多轮询次数或终态语义；
- 在首个切片中解决多 backend worker 调度或任务选主；
- 首先拆分 `data_collector.py` 或 Briefing 大页面；
- 一次性消灭所有兼容别名、未分类测试或历史 source-contract 测试。

## 5. 方案选择

比较三种重构方式：

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 大爆炸式分层重写 | 最终目录看起来统一 | 反馈周期长，冲突和行为漂移风险最高 | 不采用 |
| 按技术层横向清理 | 可集中处理 Repository、Service 或 hooks | 很久不能形成完整参考路径，容易留下双实现 | 只用于机械性配套工作 |
| 按用户路径纵向切片 | 每次交付完整、可验证，能逐步复制稳定模式 | 同一时期新旧模式会短暂并存 | 采用 |

选择纵向切片并不意味着允许永久混用。每个新边界都必须包含：

- 明确的生产调用者；
- 明确的旧路径退出条件；
- 依赖方向契约；
- 行为测试；
- 可整体回滚的交付单元。

## 6. 目标架构与职责

### 6.1 后端依赖方向

```text
FastAPI / Graph / Scheduler / CLI
              ↓ 组合与依赖注入
Application Use Case
              ↓
Domain Types + Ports
              ↓
Repository / Provider / Job Adapter
              ↓
PostgreSQL / 外部数据源 / 进程内执行器
```

各层职责固定如下：

| 单元 | 负责 | 不负责 |
|---|---|---|
| Route | 输入验证、DTO 映射、HTTP 映射 | SQL、commit、跨 Service 编排 |
| Application Use Case | 业务步骤、事务时机、错误转换、后置副作用 | HTTP 细节、ORM 查询语句 |
| Domain Types/Ports | 稳定数据语义和依赖协议 | 框架、数据库和网络实现 |
| Repository Adapter | SQL、ORM 映射、原子持久化操作 | commit、后台任务、HTTP |
| Provider Adapter | 外部请求、规范化、限流和重试 | Session、业务事务 |
| Unit of Work | Session 生命周期、commit、rollback | 业务判断 |
| Job Adapter | 创建、查询和执行后台任务 | 复用请求 Session |

依赖必须单向。函数内 lazy import 只允许作为短期兼容手段，不能作为消除循环依赖的完成
标准。

### 6.2 前端依赖方向

```text
App Page
   ↓
Feature Public API
   ├── mutation/query hooks
   ├── cache policy
   ├── response normalization
   └── feature behavior
          ↓
Shared API Transport + queryKeys/queryPolicy
          ↓
Backend API
```

页面负责组合和布局，展示组件负责渲染；只有 Feature action 可以决定一项 mutation 成功后
应更新或失效哪些缓存。页面、表格和 Drawer 不再各自复制相同 key 列表。

### 6.3 五条架构不变量

以下规则立即适用于所有新增代码和已经迁移的切片；尚未迁移的旧路径通过后续切片逐步
收敛，不能因为全仓库暂时不满足就为新代码增加例外：

1. Page 不枚举跨资源缓存失效列表；
2. Route 不执行 ORM 查询或提交事务；
3. 一个 Use Case 只有一个事务所有者；
4. Provider 不持有或创建数据库 Session；
5. 生产依赖图不新增双向边。

## 7. 错误与事务设计

### 7.1 错误流

目标错误流沿调用方向收敛：

1. Provider 表达超时、限流、外部源不可用和数据无效；
2. Repository 表达不可恢复的持久化失败；
3. Use Case 将可预期失败转成 `FundAgentError` 子类；
4. API 统一映射为 `{error: {code, message, details}}`；
5. 前端 Shared Transport 解析为带 `status`、`code` 和 `details` 的 `ApiError`；
6. Feature 决定 toast、重试、保留旧数据或停止 polling。

日志必须携带当前上下文中可用的 `fund_code`、`job_id`、`source` 和 `stage`。首个切片
至少要求 `fund_code` 与 `stage`；统一生成请求关联 ID，以及是否把它作为可选字段加入
HTTP 错误响应，属于后续可观察性切片。首个切片不改变现有错误响应 schema。

首个切片的精确错误契约是：

- Pydantic/FastAPI 422 响应保持；
- 已注册的业务异常处理器继续兼容 `{error: ...}`，历史 `HTTPException` 继续兼容
  `{detail: ...}`；
- Shared Transport 的 `ApiError` 必须同时解析这两种现有响应；
- 本切片不要求把所有 Route 一次性迁移到统一错误 envelope；
- commit 前失败按现有错误映射返回失败，commit 后 preload handoff 失败按第 10.4 节返回
  新增成功。

禁止：

- Route 重复拼装相同业务错误；
- `except Exception: pass`；
- 把可选后台预热失败伪装成数据库新增失败；
- 向用户或日志暴露凭证、数据库 URL 或未经脱敏的完整外部响应。

### 7.2 事务流

采用“一次业务操作，一个事务所有者”：

- Use Case 通过注入的 Unit of Work 控制 commit 或 rollback；
- Route、Domain Service 和 Repository 不 commit；
- API composition root 只构造 Use Case 和 Unit of Work factory；
- 外部网络请求在事务外执行；
- 后台任务拥有独立 Unit of Work，不复用请求 Session；
- 跨事务副作用只在提交完成后触发。

首个切片不全局改变 `get_db_session()` 的语义，避免同时迁移所有路由。只为新增自选建立
显式、切片级 Unit of Work；后续写路径逐条迁移后，再决定是否收敛全局 request
transaction。

## 8. 分阶段迁移

### 8.1 Stage 0：恢复可信基线

开始任何结构切片前必须完成：

1. 解决 Scheduler 同步公开契约与 coroutine 实现不一致；
2. 推荐保留 `runtime.start_scheduler()` 和 `shutdown_scheduler()` 的同步签名；
3. 如果 FastAPI lifespan 需要避免阻塞，只在 composition root 使用
   `asyncio.to_thread()`，不改变 Scheduler 包的公开契约；
4. 运行完整 unit 分区，确认没有未 await coroutine 或资源泄漏警告；
5. 运行 PostgreSQL 各测试分区、前端 105 个现有测试、TypeScript strict 和 production
   build；
6. 记录基线提交、测试数量、耗时、warning、skip 和 33 个兼容别名数量。

Stage 0 必须独立于首个业务切片提交。当前工作区已有的暂存修改属于实施前现状，本设计
文档提交不得包含这些代码。

### 8.2 Stage 1：最低质量门禁

在首个结构切片前增加：

- 前端脚本：
  - `test:contract` 运行现有 Node tests；
  - `test:component` 运行 Vitest；
  - `test` 顺序运行两类测试；
  - `typecheck` 运行 `tsc --noEmit`；
- 前端 CI：`npm ci`、test、typecheck、production build；
- 后端 CI：unit、普通 DB、多连接、DDL/pgvector 独立 job；
- 完整 OpenAPI snapshot，而不是只检查 `/api/health`；
- 保留 Scheduler registry、API、import、事务所有权和数据库安全契约；
- Ruff 和 Python 类型检查先以报告模式建立零基线，再对本切片触及的包设为阻断；
- 增加 differential coverage 报告，但首个切片不以尚未稳定的覆盖阈值阻断；
- 禁止新增读取生产源码并匹配字符串的行为测试。

现有 471 个未分类后端测试和历史前端 source-contract 测试不要求一次性清零，但本切片
新增或修改的测试必须正确分类；被行为测试完整替代的 source-contract 断言应在同一切片
删除。

### 8.3 Stage 2：首个纵向切片

实施本设计第 9 至第 13 节描述的“新增普通自选 + 可选预热”。

### 8.4 Stage 3：复制模式

首个切片稳定后，按以下顺序推进，每一项单独设计、计划和验收：

1. 单基金刷新与统一缓存策略；
2. 明确“移出自选”和“清理基金缓存/交易数据”是否应为不同业务动作；
3. 切断 `fund_service ↔ diagnosis_service` 循环；
4. 拆分 `data_collector.py` 的 Provider、规范化、重试和持久化职责；
5. 拆分 Briefing 页面请求状态、领域展示、证据和反馈。

## 9. 首个切片：范围与行为契约

### 9.1 包含

- 普通 `POST /api/watchlist`；
- 原子 get-or-create；
- 一次明确的数据库事务；
- commit 后 preload handoff；
- HTTP 成功响应兼容；
- 前端普通新增分支；
- 新增成功后的即时 watchlist cache 更新；
- 可选 preload polling 和终态 cache invalidation；
- 后端并发/事务测试与前端组件行为测试。

### 9.2 不包含

- `/initial-holding`；
- PATCH、DELETE 和交易相关端点；
- preload 执行步骤、线程池大小、状态枚举或轮询策略重写；
- 持久化任务队列；
- Watchlist 数据模型或唯一约束 migration；
- 删除现有 Service 兼容门面；
- 拆分 monolithic API client 的全部端点；
- 修改 Query Key tuple 形状。

### 9.3 保持的公开行为

- 路径仍为 `POST /api/watchlist`；
- 成功状态码仍为 200；
- 请求字段和验证规则不变；
- 首次新增返回新行，可选包含 `preload_job`；
- 重复 POST 返回原始行，不覆盖 note、持仓或关注字段；
- 已存在行不启动新的 preload；
- LangChain note-only `add_fund_to_watchlist` 契约和是否预热的现有行为不变；
- preload 的 `pending/running/done/partial/failed/missing` 语义不变；
- 前端成功、info 和失败 toast 的用户语义不变。

唯一有意澄清的失败语义是：membership 已经 commit 后，如果可选 preload handoff
同步失败，HTTP 仍返回新增成功并记录异常，而不是把已提交的数据伪报为新增失败。该语义
必须由独立契约测试固定。

## 10. 首个切片：后端设计

### 10.1 当前问题

当前 Route 先调用 `ws.get_one()`，再调用 `ws.add_full()`，最后调用
`start_preload_job()`。前两步各自打开短事务，Repository 又以 `SELECT` 后 `INSERT`
实现幂等。

并发请求可能同时判断记录不存在，然后其中一个请求收到唯一约束异常。即使没有并发，
“记录已经提交”和“任务已经成功交接”也没有统一编排语义。

### 10.2 应用契约

首个切片建立以下窄接口，具体文件名可在实施计划中微调，但职责不可合并回 Route：

- `AddWatchlistCommand`：规范化后的基金代码和允许写入的字段；
- `WatchlistCreateOutcome`：`row` 与 `created`；
- `WatchlistMembershipRepository`：原子 get-or-create；
- `WatchlistUnitOfWork`：提供 Repository 并控制 commit/rollback；
- `PreloadDispatcher`：为已提交的新记录启动或复用 preload；
- `AddWatchlistUseCase`：编排事务和 post-commit handoff。

推荐落点：

```text
backend/application/watchlist/add_entry.py
backend/application/watchlist/ports.py
backend/db/unit_of_work.py
backend/db/repositories/watchlist.py
backend/services/watchlist/watchlist_preload_jobs.py
backend/api/deps.py
backend/api/routes/watchlist.py
```

Protocol 与应用 DTO 不导入 FastAPI、SQLAlchemy ORM model 或进程级 job globals。

### 10.3 原子 get-or-create

Repository 使用 PostgreSQL 原子写入：

```text
INSERT INTO watchlist (...)
ON CONFLICT (fund_code) DO NOTHING
RETURNING ...
```

若 `RETURNING` 有结果，则 `created=true`；若冲突，则在同一事务中读取已有行并返回
`created=false`。`created` 只能来自写入结果，不能由事务外预查询推断。

现有 `uq_watchlist_fund` 唯一约束已经满足该设计，不新增 migration。Repository 只执行
SQL、映射结果和必要的 `flush()`，不 commit。

### 10.4 事务与 preload handoff

目标时序：

```text
Route 验证
  → Use Case 进入 Unit of Work
    → Repository 原子 get-or-create
    → Use Case commit
  → Unit of Work 结束
  → created=true 时调用 PreloadDispatcher
  → Route 映射现有成功响应
```

约束：

- commit 失败时不允许调用 Dispatcher；
- Dispatcher 不接收请求 Session；
- worker 新 Session 必须能看见已提交的 membership；
- `created=false` 时不调用 Dispatcher；
- Dispatcher 返回 job 时，响应继续合并 `preload_job` 和 `preload_status`；
- Dispatcher 返回 `None` 时，新增仍成功，响应不包含 `preload_job`；
- Dispatcher 在 commit 后抛出异常时，记录带 `fund_code` 和
  `stage=preload_dispatch` 的异常日志，返回已提交的新增结果，不伪报数据库失败；
- 进程在 commit 后、enqueue 前崩溃时可能留下未预热记录，这是首个切片接受的残余风险，
  用户可以手动刷新，后续根据真实故障频率再决定是否设计持久化任务。

### 10.5 兼容路径

现有 `watchlist_service.py` 继续作为 LangChain tools 和尚未迁移调用者的兼容门面。
兼容门面可以复用新的原子 Repository primitive，但首个切片不强制所有旧调用者改用新
Use Case，也不改变其是否启动 preload。

只允许一份原子 get-or-create SQL 实现。兼容门面不得保留另一份 `SELECT` 后 `INSERT`
实现。

## 11. 首个切片：前端设计

### 11.1 Feature 边界

新增窄 Feature：

```text
frontend/src/features/watchlist-add/
├── api.ts
├── cache.ts
├── use-add-watchlist-fund.ts
├── use-watchlist-preload-job.ts
└── index.ts
```

公开入口只导出普通新增所需 hook 和稳定类型。首个切片完成后，普通新增生产路径只有该
Feature 可以直接调用 `api.watchlistAdd()`、`api.watchlistPreloadJob()` 及其缓存策略。

`useWatchlistSave` 继续负责 edit 和 initial-holding；普通
`mode === "add" && !needsInitialHolding` 分支迁移到 Feature。不得把 initial-holding 和
普通关注基金合并为一个含大量布尔分支的新 hook。

### 11.2 响应规范化

Feature API 把当前交叉类型 `WatchlistRow & { preload_job? }` 规范化为：

```text
{
  row: WatchlistRow,
  preloadJob: WatchlistPreloadJob | null
}
```

组件不直接判断后端 snake_case 的可选附加字段。Shared Transport 继续负责 URL、JSON 和
错误解析；首个切片不拆完 `frontend/src/lib/api.ts` 的其他领域端点。

Shared Transport 将当前普通 `Error` 收敛为 `ApiError`，至少保留 `status`、`code`、
`details` 和兼容的 message。Watchlist Feature 不再从字符串反解析错误；尚未接入 Shared
Transport 的 Market 请求留给后续切片。

### 11.3 两阶段缓存策略

第一阶段，POST 已提交：

1. 如果 `queryKeys.watchlist.all` 已有缓存，按 `fund_code` 幂等 upsert；
2. 新行追加；已有行保持原位置，并以 `{...cachedRow, ...responseRow}` 合并，避免 POST
   响应缺少 `transaction_count`、NAV 和 PnL 展示字段时清空 GET 已经补充的值；
3. 缓存未初始化时不凭空构造不完整列表；
4. 始终 invalidate `queryKeys.watchlist.all`，让带 NAV、收益和交易数量的完整列表重新
   校准；
5. invalidate `queryKeys.fund.summaryForFund(code)`，因为 summary 包含自选状态；
6. 不等待 preload 才显示新增结果。

第二阶段，可选 preload 到达终态或 polling 查询失败：

- invalidate watchlist；
- invalidate fund summary、detail、NAV、NAV history、metrics 和 diagnosis；
- invalidate单基金 PnL 与全组合 PnL；
- 保留当前 toast、1.5 秒 interval、120 次上限、`retry=false` 和终态语义。

缓存列表只能由 `cache.ts` 中的命令级 helper 管理。页面、Drawer 和 polling hook 不再
复制这两组 key。

### 11.4 生命周期

- 响应不含 `preload_job`：新增成功，不启动 polling；
- 响应含 job：只启动一次 polling；
- Drawer 关闭后 polling 继续；
- Watchlist 路由卸载后 observer 停止，不跨页面继续 toast；
- POST 失败时表单保持打开，不改缓存、不启动 polling；
- 重复提交获得已有行时按 `fund_code` upsert，不产生重复 UI 行。

为保证 Drawer 关闭后仍轮询，polling owner 必须位于不会随 `open=false` 卸载的 Feature
或页面边界，而不是 BasicTab 的条件渲染子树。

## 12. 测试设计

### 12.1 测试原则

- 业务行为测试优先于源码形状测试；
- 架构测试只守护依赖方向、禁止调用和唯一入口等稳定规则；
- 不用正则锁定函数名、调用顺序或 JSX 文案来代替用户行为；
- 新测试先失败，再实现；
- 删除旧断言前必须有等价或更强的行为覆盖；
- 测试不得连接开发或生产数据库。

### 12.2 后端测试

Use Case 单元测试使用 Fake UoW、Repository 和 Dispatcher：

1. 首次新增 commit 后恰好 dispatch 一次；
2. 已存在行不覆盖字段、不 dispatch；
3. Repository 或 commit 失败时 rollback 且不 dispatch；
4. Dispatcher 返回 `None` 时仍返回成功；
5. Dispatcher 抛错时记录异常并返回已提交结果；
6. worker 不获得请求 Session。

PostgreSQL 集成测试：

1. 两个独立连接并发新增同一 `fund_code`，只有一行；
2. 两个并发 HTTP 请求最终只产生一次 preload handoff；
3. Dispatcher 启动的新 Session 能看见 membership；
4. 原子操作保留原始字段，不发生 last-write-wins 覆盖；
5. API 路径、200 状态和 JSON 字段保持；
6. Pydantic 422 行为保持；
7. 事务失败后数据库无半成品。

并发测试使用 `db_multiconnection`，不得用同一 Session 模拟。

### 12.3 前端测试

引入 Vitest、React Testing Library 和 jsdom，覆盖：

1. 普通新增只发送一次请求，提交期间禁止重复提交；
2. POST 成功后页面立即出现新行并关闭 Drawer；
3. 无 `preload_job` 时不请求 job status；
4. 有 job 时只启动一次 polling；
5. `done`、`partial`、`failed` 保持现有缓存和 toast 行为；
6. POST 失败时 Drawer 保持打开，缓存不变；
7. 重复返回已有行时不产生重复列表项；
8. 重复返回已有行时保留缓存中的 NAV、PnL 和 transaction count 等富化字段；
9. 关闭 Drawer 后 polling 继续，路由卸载后停止；
10. initial-holding 仍调用原端点，不经过普通新增 Feature。

现有 source-contract 测试可以继续守护 Query Key 必须来自 factory、禁止手写 timer 等架构
规则；普通新增的缓存和交互不再通过读取 `useWatchlistSave.ts` 源码验证。

### 12.4 每个切片的验证命令

最低门禁：

```bash
python -m pytest -q backend/tests -m unit
python -m pytest -q backend/tests -m "not unit and not db_multiconnection and not db_ddl and not db_pgvector"
python -m pytest -q backend/tests -n 0 -m db_multiconnection
python -m pytest -q backend/tests -n 0 -m "db_ddl or db_pgvector"
python -m compileall -q backend

cd frontend
npm test
npm run typecheck
npm run build
```

另需运行：

- 首个切片的 focused backend/frontend tests；
- 改动测试连续三次，确认无偶发失败；
- `git diff --check`；
- OpenAPI、Scheduler registry、事务和 import 契约；
- 使用 SQLAlchemy query instrumentation 固定新增路径的查询数；
- 延迟只记录同机、同数据库、同数据规模下的观察值，不在没有稳定 benchmark protocol
  前作为合并门禁。

## 13. CI 与质量门禁

每个切片必须满足：

- 所有 required checks 通过；
- 无未 await coroutine、线程或数据库连接泄漏 warning；
- OpenAPI、Scheduler registry、tool schema 和持久化契约没有未批准变化；
- 无新增事务所有权或依赖方向违规；
- 测试数量减少时，同一提交必须说明被哪个行为测试替代；
- 修改过的决策分支有覆盖；
- 首个切片必须报告 touched code 覆盖且不得出现无测试的新决策分支；coverage 配置稳定后，
  再将 touched code 行覆盖至少 80% 设为阻断目标；
- 新增路径的 SQL query count 由集成测试固定，不允许出现随数据量增长的额外查询；
- 兼容别名从 33 起只能减少，不能新增；
- 不新增 source-string 行为测试；
- 单个提交目标小于 400 行非生成 diff；超过时拆分为可审查提交，但整个切片作为一个
  merge/revert 单元。

Ruff、Python typing 和 differential coverage 只有在配置、依赖和基线提交后才能被称为
门禁；在此之前只报告结果。

## 14. 发布、提交与回滚

### 14.1 提交边界

按顺序交付三个独立 merge 单元：

1. **基线单元**：Stage 0 Scheduler 契约修复和基线记录；
2. **门禁单元**：Stage 1 前端 test/typecheck/build CI，以及报告模式静态检查；
3. **业务切片单元**：
   - 后端 characterization tests 与原子 Repository；
   - Use Case、Unit of Work、Route 切换和后端集成测试；
   - 前端 Feature、组件行为测试和旧 source assertion 替换；
   - ADR、README 或开发命令同步。

三个单元不得合并为一个“大重构”提交。业务切片单元内部可以拆成多个可审查提交，但后端
和前端迁移全部通过后才合并。任何单元都不得带入当前工作区无关的暂存或未暂存修改。

### 14.2 发布条件

- 不需要 schema migration 或数据回填；
- 后端与前端必须在同一发布单元保持现有 API 兼容；
- 旧 Service facade 在发布后继续工作；
- 新 Feature 不依赖后端新增字段；
- 所有 required checks 和完整 PostgreSQL CI 通过后才能合并。

### 14.3 停止与回滚

出现以下任一情况立即停止并回滚整个切片：

- 公开 API 或 preload 状态语义意外变化；
- 并发新增出现两行、重复 dispatch 或未处理唯一冲突；
- commit 失败后仍启动任务；
- worker 读取不到已提交 membership；
- 测试连接到非测试数据库；
- 线程、coroutine 或 Session 泄漏；
- 前端新增成功后出现重复行、幽灵行或等待 preload 才显示；
- 新增路径出现未批准的额外 SQL 或随 watchlist 数量增长的查询；
- 完整门禁转红。

回滚方式是 revert 整个 merge 单元。由于没有 schema 和数据迁移，不需要数据库 downgrade。
已经成功创建的自选记录属于用户业务数据，代码回滚不得删除。

## 15. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| commit 后、enqueue 前进程退出 | 新记录暂未预热 | 明确日志和手动刷新；首切片不引入 Outbox |
| 原子 upsert 与旧 facade 双实现 | 并发语义再次漂移 | 原子 SQL 只有一份，旧 facade 调用同一 primitive |
| 普通新增误并入 initial-holding | 持仓与交易语义改变 | 独立 Feature 和测试，initial-holding 明确排除 |
| 即时缓存行字段不完整 | 列表短暂显示缺省值 | 只在已有 cache 中 upsert，并立即 invalidate 校准 |
| polling owner 随 Drawer 卸载 | 后台完成后页面不刷新 | owner 放在稳定 Feature/页面边界，行为测试覆盖 |
| 全局 UoW 重写扩大范围 | 大量路由同时变化 | 首切片使用局部 UoW，后续逐条迁移 |
| 并发测试偶发失败 | 门禁不可信 | 使用真实独立连接、确定性 barrier 和三次重复运行 |
| 新测试框架增加维护成本 | 前端依赖和配置变多 | 只引入 Vitest/RTL/jsdom，不同时引入 E2E 框架 |

## 16. 衡量方式

首个切片不以“新建了多少目录”为成功标准，记录以下指标：

| 指标 | 当前基线 | 首切片目标 |
|---|---:|---:|
| Backend unit | 990 pass / 6 fail | 全绿，无未 await warning |
| Frontend tests | 105 pass | 全绿，并增加普通新增行为测试 |
| 前端 CI | 无 | test/typecheck/build 全部 required |
| 自选新增事务 | 查询与新增分属两个隐式事务 | 一个显式 UoW |
| 并发幂等 | SELECT 后 INSERT | 数据库原子 get-or-create |
| 新增缓存策略位置 | Save hook + polling hook/消费者 | 一个 Feature cache policy |
| 生产 service 循环 | 1 个已知 SCC | 不新增；后续切片降为 0 |
| Service 兼容别名 | 33 | 不新增，只减不增 |
| 新 source-string 行为测试 | 不适用 | 0 |

六个月内持续观察：

- 一个需求平均需要修改的生产文件数量；
- 同一缓存失效列表的重复位置数量；
- source-contract 测试与行为测试的比例；
- 未分类 pytest 数量；
- 兼容别名数量；
- CI 偶发失败率；
- 变更引入回归与回滚次数。

这些指标用于选择下一切片，不设置为了达标而大规模搬文件的虚假目标。

## 17. 首个切片完成标准

- [ ] Scheduler 基线恢复全绿且公开生命周期契约明确；
- [ ] 前端 test、typecheck 和 build 已进入 CI；
- [ ] `POST /api/watchlist` 使用一个显式 Unit of Work；
- [ ] Repository 原子返回 `row + created`；
- [ ] 并发请求只有一条 membership 和一次 preload handoff；
- [ ] commit/rollback 与 post-commit dispatch 时序有测试；
- [ ] Route 不查询 ORM、不 commit；
- [ ] worker 不复用请求 Session；
- [ ] API 请求、200 状态和成功响应字段兼容；
- [ ] 普通新增成功后前端立即显示记录；
- [ ] 无 job 时不 polling，有 job 时只 polling 一次；
- [ ] 普通新增缓存策略只存在于 Feature；
- [ ] initial-holding、PATCH、DELETE 和其他 Watchlist 行为不变；
- [ ] 新增交互由组件行为测试覆盖，不新增源码正则测试；
- [ ] 全部前后端、PostgreSQL、类型、构建和架构门禁通过；
- [ ] 文档与 ADR 的“已实施”状态和生产接线一致；
- [ ] 整个切片可以通过一个 merge revert 回滚。

## 18. 后续设计门禁

本文件提供六个月的方向和首个切片的完整设计，但不是所有后续切片的单一实施计划。

首个切片完成后，每个 Stage 3 项目必须重新执行：

1. 检查当时生产代码与测试基线；
2. 明确该切片的行为不变量和非目标；
3. 比较至少两个迁移方案；
4. 书面确认事务、错误、缓存和测试边界；
5. 编写独立设计与实施计划；
6. 验证、审查并以独立 merge 单元交付。

这样可以让半年路线保持方向一致，同时避免今天为几个月后的未知代码写出失效的详细计划。
