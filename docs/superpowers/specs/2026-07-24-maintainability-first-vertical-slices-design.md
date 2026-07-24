# Fund Agent 代码可维护性、复用与性能优化设计

**版本**：1.2

**日期**：2026-07-24

**状态**：已由用户于 2026-07-24 书面确认

**适用周期**：未来六个月持续开发当前项目

## 1. 决策摘要

本项目未来六个月的优化顺序固定为：

1. **先优化生产代码的可维护性**：降低理解一项业务所需跨越的文件数，收拢事务、缓存、
   刷新、错误处理等散落规则，消除循环依赖和超大职责单元；
2. **再提高项目内复用性**：只抽取已经有至少两个真实生产调用方、且语义和生命周期一致
   的内部能力，不以“看起来相似”为理由建设通用框架；
3. **然后做有证据的性能优化**：优先消除重复请求和重复查询，其次批处理和缓存，最后才是
   有界并发或协程；
4. **测试和 CI 只作为护栏**：它们用于证明行为没有回退，不作为本轮优化的主要交付物。

采用的整体方案是：

> 在现有单体应用内按业务纵向切片逐步形成模块化单体，并让共享层通过真实复用“自然长
> 出来”。保持同步 SQLAlchemy；AkShare 调用保持串行；只在原生异步、彼此独立的网络 I/O
> 路径上使用有界协程并发。

第一阶段不是重写目录，而是先完成一个限时安全/基线修复，再完成两个可独立合并的业务
切片：

1. 恢复 Scheduler 同步契约，并修正 AkShare 内部并发绕开全局锁的问题；
2. 首个纵向切片：原子新增自选后端，加上前端 add/preload 的最小 Feature 行为；
3. 独立复用切片：抽出 preload、定时刷新和手动刷新共同使用的稳定基金刷新操作。

两个业务切片分别解决写入/前端边界和后端复用问题。不会为了一个 POST 接口预先引入
通用 Command Bus、DI 容器、泛型 Repository 或全局 Unit of Work 框架。

### 1.1 与现有设计的关系

本设计是现有重构工作的优先级调整和执行收敛，不推翻已经建立的 PostgreSQL、领域目录、
Scheduler 注册表、WatchlistDrawer 和 React Query 治理。以下文档继续提供背景约束：

- `docs/superpowers/specs/2026-07-14-fund-agent-refactoring-design.md`；
- `docs/superpowers/decisions/0002-transaction-ownership.md`；
- `docs/superpowers/specs/2026-07-16-scheduler-hard-cut-design.md`；
- `docs/superpowers/specs/2026-07-16-watchlist-drawer-hard-cut-design.md`；
- `docs/superpowers/specs/2026-07-17-react-query-governance-design.md`。

ADR-002 中以下规则继续有效：

- Repository 只 flush，不 commit/rollback/close；
- 网络、LLM 和 embedding 不占用长事务；
- 后台线程使用独立短 Session；
- 调用方传入 Session 时，被调用函数不自行结束事务。

对于已迁移的写路径，本设计补充并局部取代 ADR-002 的 API Route 规则：Delivery 不拥有
Session，顶层 Application 函数使用具体 `session_scope()` 拥有事务。尚未迁移的旧路径
继续维持当前契约。实施首个写切片时必须同步更新 ADR-002 的状态和适用范围，避免两套规则
同时被描述为全局标准。

Scheduler 硬切换设计中的同步签名和返回语义仍是权威契约。当前代码、暂存修改或历史文档
中的“已实施”字样都不能单独证明完成；必须以生产接线、行为验证和文档三者一致为准。

## 2. 当前证据与问题排序

### 2.1 生产代码维护热点

| 优先级 | 现状 | 对持续开发的影响 | 目标 |
|---|---|---|---|
| P0 | `fund_service` 与 `diagnosis_service` 双向依赖并靠 lazy import 缓解 | 修改任一侧都要理解另一侧，隔离测试困难 | 通过窄读取端口消除依赖环 |
| P0 | Watchlist Route、Service、Repository 和后台任务共同编排一个业务操作 | 事务边界和提交后副作用难推断 | 一个应用函数拥有一次业务操作 |
| P0 | 前端页面、表格、Drawer、交易和 polling 分别维护缓存失效列表 | 新增缓存消费者时容易漏改 | 按业务动作集中缓存策略 |
| P0 安全 | 外层 AkShare 锁内又启动子线程，实际调用可能并发；线程超时不能终止底层调用 | 可能违反已有串行保护并留下孤儿工作 | 首轮恢复真实串行和诚实的超时语义 |
| P1 | `data_collector.py` 约 1,170 行，混合网络、重试、解析、线程和数据库 | 数据源变化会波及无关功能 | 按 Provider 能力拆分，Provider 不访问 DB |
| P1 | `watchlist_service.py` 重复 `session=None → session_scope → _impl` | 样板代码掩盖业务步骤 | 新路径直接使用明确的应用边界 |
| P1 | Briefing 页面约 1,264 行，混合请求、轮询、版本识别和渲染 | 修改一个模块容易影响整页 | 页面只组合，Feature 管理数据和模块 |
| P1 | 多个模块各自维护 executor、锁、jobs 和 active-key | 生命周期、去重和清理逻辑重复 | 两个流程迁移后抽 keyed job runner |
| P2 | `backend/services/__init__.py` 安装大量旧模块别名 | 真实依赖路径被隐藏 | 给兼容层设置最终调用者和删除条件 |

### 2.2 已观察问题与待验证假设

当前最明显的问题不是“协程用得少”，而是重复工作：

- **已观察**：Briefing 对每只基金分别调用三次 `get_metrics()`，每次都重新加载整段 NAV 历史；
  30 只基金时约产生 90 次历史查询；
- **待量化**：批量刷新每只基金的 profile 时，会反复获取可跨基金复用的全局规模、排名、
  经理和 fallback category 数据；
- **已观察**：知识分类状态被重复查询，匹配和向量写入存在逐行
  `SELECT + flush/upsert`，匹配本身还可能全量执行 documents × funds；
- **已观察**：NAV upsert 先加载全部已有日期，再逐个加入 ORM；
- **已观察**：前端部分 polling 在任务已结束或没有任务时仍按固定间隔请求；
- **已观察**：同日刷新时，过粗的 snapshot 指纹可能无法识别新结果，导致无效轮询；
- **待量化**：17:00 Briefing 可能重复抓取 15:35 market intelligence 和 16:00 evidence
  已经产生的新鲜数据。

因此性能优化遵循：

```text
删除重复工作 → 批量读写 → 有边界的缓存 → 有界并发 → 原生异步化
```

后一步只有在前一步仍不足、且基准数据证明收益时才进入。

### 2.3 当前验证基线

整理本设计时的可复现结果：

- 后端收集到 1,707 个测试，其中 996 个标记为 `unit`；
- 后端 unit 分区为 990 通过、6 失败；6 个失败都来自 Scheduler 同步公开契约被改为
  coroutine，而调用方和测试仍按同步方式使用；
- 前端 105 个测试通过；
- TypeScript strict 检查通过；
- 后端 `compileall` 通过；
- 当前 CI 只覆盖后端，没有运行前端 test、typecheck 和 production build；
- 多个前端测试直接读取源码并匹配字符串或正则，容易把重构误判为行为变化。

恢复 Scheduler 契约是开始结构改造前的有限前置条件。补齐全部测试体系不是生产代码优化
的前置项目；每次只为被修改的行为补足必要护栏。

## 3. 目标、衡量方式与非目标

### 3.1 维护性目标

未来六个月希望达到：

1. 一项业务变更主要落在一个 Feature 或应用用例中；
2. 一次写操作只有一个明确的事务所有者；
3. Route 不查 ORM、不提交事务；Repository 不编排业务；Provider 不访问数据库；
4. 页面和组件不各自维护跨资源缓存规则；
5. 循环依赖数量单调下降，不再通过新增 lazy import 隐藏；
6. 每个兼容 facade 都有最终调用者、迁移条件和删除条件；
7. 内部重构不改变外部行为时，大多数行为测试无需修改。

主要观察指标：

- 完成一个代表性业务变更需要修改的生产文件数；
- 同一规则在生产代码中的重复实现点数量；
- Python 模块依赖强连通分量数量；
- 超大文件的职责数和行数变化；
- 兼容别名数量；
- 仅因实现重排而需要修改的测试比例。

这些指标用于看趋势，不鼓励为了数字机械拆文件。

### 3.2 复用目标

一个共享抽象必须同时满足：

1. 至少两个真实生产调用方；
2. 调用方复用的是相同语义，而不只是相同代码形状；
3. 生命周期一致，例如事务所有权、缓存时效或任务状态一致；
4. 接口比实现窄，调用方不需要知道底层 SQL、线程或 Provider；
5. 抽取后能删除重复生产实现，而不是再增加一层包装。

计划形成的项目内共享能力：

| 共享能力 | 首批真实调用方 | 保留在业务模块中的内容 |
|---|---|---|
| 基金刷新操作 | 新增自选预热、定时刷新、手动刷新 | 各触发方自己的步骤组合、状态和展示 |
| 语义化缓存策略 | 新增/删除自选、交易、待确认申购、基金刷新 | 组件自己的 UI 状态 |
| 类型化 HTTP transport | 现有全局 API、Watchlist Feature，之后按触达迁移 | Feature DTO 和响应规范化 |
| Keyed in-process job runner | Watchlist preload、Diagnosis refresh | 各任务的状态字段和持久化 |
| AkShare gateway 策略 | Fund Provider、现有 market collector（随后迁移到 Market Provider） | 各数据集解析与规范化 |

### 3.3 性能目标

性能改造必须提供前后对比，至少记录：

- p50/p95 总耗时；
- SQL 次数和读取行数；
- 外部请求次数；
- AkShare 锁等待时间；
- DB 连接池等待时间；
- 超时、限流和错误数；
- 输出等价性。

约 20% 的 p95 改善只是启发式判断，不是为了达标而优化的硬门槛。实施前要固定 1/10/30
只基金、冷/热缓存、正常/超时等 workload 和最低样本量。默认保留条件是满足以下之一，
同时没有提高错误率、队列积压或孤儿任务数：

- 代表性路径 p95 至少改善约 20%；
- SQL 或外部请求数量出现数量级明显的下降；
- 用户请求不再被长网络 I/O 阻塞，且后台任务完成时间和队列上限仍满足约束；
- 移除了已确认的资源泄漏、无界排队或竞态风险。

首批测量协议：

- 在实施计划中把 30 个 fund code、每只 NAV 行数和 PostgreSQL seed manifest 固定进
  benchmark fixture，1/10 场景取同一列表前缀；
- cold 表示清空本切片拥有的进程缓存后执行，warm 表示先完成一次成功加载；不得清除无关
  用户数据；
- 纯 DB/本地路径同一环境先 warm-up 3 次，再至少重复 30 次；记录 p50/p95 和 query count；
- 真实外网路径至少重复 10 次，只作观测，不用单次延迟作硬门禁；
- 确定性的 SQL/外部调用数、返回行数和输出等价性可以设门禁；
- 在 SQLAlchemy engine event、Provider wrapper、AkShare lock wrapper 和 job runner
  边界记录计数/阶段耗时，不把 instrumentation 散到业务函数。

### 3.4 非目标

本设计暂不包含：

- 全仓库一次性重写或统一目录搬迁；
- 抽取跨项目发布的 Python/npm 包；
- 通用 Command Bus、事件总线、CQRS、DI 容器或泛型 Repository；
- Celery、Redis、Outbox、持久化 Job Store 或多 worker 选主；
- 替换 ORM、整体迁移 async SQLAlchemy；
- 为了使用协程而重写同步路径；
- 一次性生成全量 OpenAPI Client 或转换所有 DTO；
- 一次性替换全部前端源码形状断言；
- 未经 profiling 的广泛并行、缓存或线程池扩容。

## 4. 目标结构：模块化单体与“挣来的共享层”

### 4.1 后端依赖方向

```text
FastAPI Route / Graph Tool / Scheduler / CLI
                       ↓
              Feature Application API
                       ↓
           Feature-owned Types and Ports
                       ↓
       Repository / Provider / Job Adapters
                       ↓
       PostgreSQL / HTTP / In-process Executor
```

职责约束：

| 单元 | 负责 | 不负责 |
|---|---|---|
| Delivery | 输入验证、协议映射、依赖装配 | SQL、commit、跨 Service 编排 |
| Application | 业务步骤、事务时机、调用 Provider/Job | HTTP 状态码、ORM 查询细节 |
| Feature Types/Ports | 稳定语义和窄依赖接口 | 框架或基础设施实现 |
| Repository | SQL、ORM 映射、原子持久化原语 | commit、网络和后台任务 |
| Provider | 外部请求、解析、规范化、限流与重试 | Session 和业务事务 |
| Job Adapter | 去重、排队、执行和状态快照 | 复用请求 Session |

不立即建设全局 `domain/ports/application/infrastructure` 四层目录。先在被迁移的 Feature 内
形成边界；两个 Feature 确认共享后，再移动到小型 shared/runtime 层。

首个写切片允许 Application 直接依赖具体 `session_scope()`，但不得 import ORM Model 或
编写 SQL。这是避免单消费者 UoW Protocol 的有意选择，不是依赖方向例外：事务上下文属于
现有基础设施入口。第二个写用例迁移后再用真实差异判断是否需要事务端口。

### 4.2 前端依赖方向

```text
Next Page / Component
          ↓
Feature Public API
  ├── api and contracts
  ├── query/mutation hooks
  ├── response normalization
  └── semantic cache effects
          ↓
Shared HTTP Transport + queryKeys/queryPolicy
          ↓
Backend API
```

目录以业务域为单位，例如 `frontend/src/features/watchlist/`，而不是建立
`watchlist-add/`、`watchlist-delete/` 等微型包。新增、删除、交易、待确认申购和预热属于
同一个 Watchlist Feature，但可以拥有独立 action。

### 4.3 抽象升级门禁

每次准备抽共享组件时回答：

1. 哪两个生产调用方现在就在重复同一规则？
2. 抽取后会删除哪些重复代码？
3. 两个调用方的事务、错误、缓存或生命周期是否真的一致？
4. 未来其中一个变化时，是否会迫使接口不断增加布尔参数？
5. 如果暂不抽取，复制一次的成本是否反而更低？

无法明确回答前两项时不抽取。出现多个 mode flag 时优先退回 Feature 内部。

### 4.4 错误与事务兼容

错误沿依赖方向收敛：

1. Provider 表达超时、限流、外部源不可用和数据无效；
2. Repository 让不可恢复的持久化异常向上返回；
3. Application 把可预期业务失败转成稳定的领域错误；
4. Delivery 统一映射 HTTP；
5. 前端 transport 解析为带 `status`、`code`、`details`、`message` 的 `ApiError`；
6. Feature 决定提示、重试、保留旧数据或停止 polling。

本轮不一次性统一所有错误响应。Shared transport 必须兼容现有 `{error: ...}` 和
`{detail: ...}` 两种形状；迁移中的 Endpoint 保持公开状态码和字段。日志使用当前可得的
`fund_code`、`job_id`、`source` 和 `stage`，不得记录凭证、数据库 URL 或未经脱敏的完整
外部响应。

事务规则是：

- 一次业务写入只有一个顶层 Application 所有者；
- Repository、Provider 和 Delivery 不 commit；
- 网络阶段在事务外，持久化阶段使用短事务；
- 后台任务不复用请求 Session；
- 跨事务副作用只在 commit 完成后触发；
- Application 在 Session 关闭前把 ORM 结果投影成稳定 DTO/dict，不向外返回绑定 Session
  的 ORM 实例。

## 5. 第一轮实施设计

第一轮包含一个前置单元和两个业务切片。前置单元独立提交；第 5.2 与 5.3 节共同构成首个
端到端业务切片；第 5.4 节是其后的独立复用切片。三者可分别验证和回滚。

### 5.1 前置单元：恢复 Scheduler 契约和 AkShare 串行安全

当前 `BackgroundScheduler` 本身已经在后台线程运行，`start_scheduler()` 和
`shutdown_scheduler()` 改为 coroutine 不会让任务体变成异步，只会额外增加一次线程切换，
并破坏现有调用方。

本轮决定：

- 保持 `start_scheduler()`、`shutdown_scheduler()` 的同步签名；
- `shutdown(wait=False)` 保持非阻塞语义；
- `backend/api/app.py` 的 startup/shutdown 调用方同步迁移为直接调用，不再 `await`；
- 包级导出、生命周期测试和生产调用方在同一合并单元恢复一致；
- 不在同步方法外包 `asyncio.to_thread()`；
- 只有未来整体迁移到 `AsyncIOScheduler` 且任务体也变为原生 async 时，才单独设计公开
  契约迁移。

同时修正当前 AkShare 安全问题：

- `_collect_profile_frames()` 不再在外层锁内启动五个 AkShare 子线程，scale、rank、
  holdings、industry、manager 五个调用先恢复串行；
- `_collect_refresh_data()` 不再用两个线程包装最终仍受同一全局锁串行的基金调用；
- 不把 `future.cancel()`、`shutdown(wait=False)` 或 `wait_for(to_thread(...))` 描述为硬
  取消；
- HTTP transport timeout 只限制对应 I/O 阶段；同步调用整段的硬截止只能由可终止进程
  隔离提供；
- signal-based timeout 不在 FastAPI、APScheduler 或后台 worker 线程中使用；
- 记录 AkShare lock wait、调用耗时，以及进程活跃线程数的调用前后值与差值；
  线程指标只用于发现疑似遗留 worker 的趋势，不把无法归因的线程变化伪装成精确计数。
  先用结构门禁证明本模块不再拥有 executor，再讨论吞吐。

这个单元只恢复可信基线和既有串行保护，不扩展 Scheduler 或数据采集功能。

### 5.2 首个业务切片（后端）：原子新增自选

#### 当前问题

`POST /api/watchlist` 当前先 `get_one()`，再 `add_full()`，两个调用各自可能打开 Session。
这会造成：

- 检查与写入不是一个原子操作；
- 并发请求存在 `SELECT → INSERT` 竞争；
- Route 同时承担幂等判断和后台任务编排；
- 很难准确证明预热一定发生在提交成功之后。

#### 目标调用流

```text
POST /api/watchlist
  → add_watchlist_entry(payload)
      → session_scope()
          → repository.create_if_absent(...)
      → commit 已完成
      → preload.dispatch(fund_code)（仅新建时）
  → 保持现有响应形状
```

实现边界：

- `backend/application/watchlist/add_entry.py`
  - 定义窄输入和 `WatchlistCreateOutcome(row, created)`；
  - 使用现有具体 `session_scope()`，暂不创建通用 UoW Protocol；
  - 数据库上下文退出成功后才 dispatch；
- `backend/db/repositories/watchlist.py`
  - 提供单条原子 `create_if_absent()`；
  - 使用现有 `uq_watchlist_fund` 执行
    `INSERT ... ON CONFLICT (fund_code) DO NOTHING RETURNING ...`；
  - `RETURNING` 有行才是 `created=true`；冲突时在同一事务读取原行，`created` 不得来自
    事务外预查询；
  - 返回最终行和是否新建，不 commit；
- `backend/api/routes/watchlist.py`
  - 只做 Pydantic 输入与 HTTP 响应映射；
- 现有 LangChain/Graph 工具继续通过兼容 facade 使用原接口，直到后续迁移。

行为契约：

- 首次添加创建一行，并在提交后启动一次预热；
- 重复添加返回已有行，不用新 payload 覆盖；
- 并发添加同一 `fund_code` 最终只有一行；
- 事务失败不启动预热；
- 预热启动失败不回滚已提交的自选记录；记录
  `fund_code`、`stage=preload_dispatch` 和异常，HTTP 仍以 200 返回已提交记录，但不附加
  不存在的 job 字段，返回行的 `preload_status` 与清理后的 `failed` 状态一致；
- Dispatcher 的 submit 失败必须清除 `_active_by_code` claim，把已创建 snapshot 和
  `watchlist.preload_status` 标为 `failed`（或在写入 pending 前失败时完全删除 snapshot），
  不能留下永久 `pending`；清理本身失败时记录第二条结构化错误；
- API 路径、成功状态码和已有成功字段保持不变。

这个单元只引入一项原子 Repository 原语和一个应用函数，不借机建设全局事务框架。等
initial-holding 或交易写入成为第二个已迁移用例后，再判断是否真的需要共享 UoW。

### 5.3 首个业务切片（前端）：Watchlist add/preload Feature

建立同一业务目录：

```text
frontend/src/features/watchlist/
  api.ts
  contracts.ts
  use-add-entry.ts
  use-preload-job.ts
  index.ts
```

首批只迁移普通 add 和 preload。initial-holding、edit、transaction、pending buy 继续走原
路径，避免把一个正确性切片扩成整个 Watchlist 重写。

Feature API 把后端交叉响应规范化成：

```ts
type AddWatchlistOutcome = {
  row: WatchlistRow;
  preloadJob: WatchlistPreloadJob | null;
};
```

组件不再读取 `row.preload_job` 这种传输层交叉字段。

POST 成功后的固定顺序：

1. 按 `fund_code` 更新已有 watchlist cache；已有行使用
   `{...cachedRow, ...responseRow}` 合并，首次行只追加一次；
2. 如果 watchlist cache 尚未初始化，不凭 POST 的不完整行构造整个列表，只 invalidate
   `queryKeys.watchlist.all`；
3. 已有 cache 在即时合并后也后台 invalidate 一次，以补齐 enriched GET 字段；
4. 显示 success toast，并调用可选 `onSaved(row)`；
5. 有 job 时显示 info toast、启动 polling；没有 job 时跳过；
6. 最后关闭 Drawer。Drawer 关闭不终止已经启动的 polling。

规则：

- 重复 POST 不追加重复行；
- preload 的 1.5 秒间隔、最多 120 次、`retry=false`、现有终态和 toast 在首切片保持；
- Drawer 关闭与浏览器 tab hidden 不等价：首切片保持既有 background polling；route 卸载
  随组件销毁停止。后续若改 hidden 策略，需要单独修改用户体验契约；
- preload 到终态后停止 polling，并一次性失效 watchlist、fund summary/detail/NAV/
  metrics/diagnosis 和相关 portfolio 数据；
- 只有 Feature 可以决定跨资源 cache effect，组件只处理自身展示状态。

Feature 内先使用具体动作 `applyAddSucceeded()` 和 `applyPreloadTerminal()`，不提前创建过宽
的 `settleMembershipChange()`。当手动刷新与 preload、或删除与交易等第二个现有动作迁移
后，再提升为 `settleFundRefresh()`、`membershipChanged()` 等语义 helper，并在同一提交
删除至少两处重复 key 列表。

本设计局部修订 React Query 治理中的“不得新增 optimistic patch”：这里不是请求前的
乐观写入，而是收到服务端成功响应后的 confirmed write-through。失败时不修改 cache。

同时从现有 `frontend/src/lib/api.ts` 机械抽出 `frontend/src/lib/http.ts`：

- `request<T>()` 统一请求、JSON 和取消处理；
- `ApiError extends Error`，保留 `status`、`code`、`details`、`message`，并保持现有 toast
  使用 `String(error)` 时的可读内容；
- 现有全局 `api.ts` 的全部 endpoint 立即委托该 transport，Watchlist Feature 是第二个
  生产调用者；旧 `get/send/parseError` 在同一提交删除，不保留两套 transport；
- Endpoint DTO 留在各 Feature，不继续扩大全局 `types/api.ts`；
- 只迁移 Watchlist endpoint 的归属，不搬动其他 endpoint 或 DTO。

### 5.4 独立复用切片：共享稳定基金刷新操作

当前至少有三类调用方需要刷新基金，但它们的失败语义不同。因此不建立带 `scopes`、
`trigger` mode 的万能协调器，只在 `backend/application/fund/refresh.py` 共享两个稳定
操作：

```python
@dataclass(frozen=True)
class BasicNavRefreshResult:
    fund_code: str
    navs_inserted: int
    already_up_to_date: bool
    fund_info_warn: str | None
    source: str
    as_of: str


@dataclass(frozen=True)
class ProfileRefreshResult:
    fund_code: str
    profile: FundProfileSnapshot
    missing_data: tuple[str, ...]
    errors: tuple[str, ...]
    source: str
    as_of: str | None
```

- `refresh_basic_and_nav(fund_code, *, session=None) -> BasicNavRefreshResult`；
- `refresh_profile(fund_code, *, session=None) -> ProfileRefreshResult`。

二者都先同步获取/规范化网络数据，再持久化：`session=None` 时自行使用一个短
`session_scope()`；调用方注入 Session 时只在该 Session 中 flush，不 commit/rollback/
close，事务仍由调用方拥有。这一参数用于保留现有 API、测试和组合调用契约，不是通用
UoW。mandatory NAV 获取失败抛稳定的 `DataSourceError`；基础信息失败仍进入
`fund_info_warn`；profile 可用但有缺失时返回 `missing_data/errors`，只有无法形成结果的
失败才抛领域错误。可选 `trigger` 只能进入日志上下文，不能改变步骤、错误或持久化策略。

新组合用例若需要把刷新结果和其他写入放进同一事务，应显式先调用无 Session 的 collect
阶段，再在短事务中调用 persist 阶段；禁止在已经执行过 SQL 的长事务里调用兼容的一体化
刷新函数。这样保留旧 `session=` 契约，同时不把它复制成新代码模式。

现有调用方组合规则保持：

| 调用方 | 执行步骤 | 失败映射 |
|---|---|---|
| 手动 refresh API / Graph tool | 只调用 basic+NAV | 维持现有成功字段；NAV 主步骤失败按现有 API 映射失败 |
| Scheduler | basic+NAV 成功后才调用 profile | 主步骤失败则该基金失败并跳过 profile；profile 失败是该基金的软失败 |
| Watchlist preload | basic+NAV 与 profile 分别尝试 | 两步都失败为 failed；只成功一步或有缺失为 partial；全部成功为 done |

旧 `fund_service.refresh_fund()` 和 `fund_profile_service.refresh_profile()` 只作兼容 facade，
把 dataclass 映射回当前 dict，确保 `navs_inserted`、`already_up_to_date`、
`fund_info_warn`、`profile`、`missing_data`、`errors`、`source`、`as_of` 和已有错误行为
不丢失；facade 把领域错误重新映射成旧 error dict，使现有 Route 继续返回原来的 502/detail
形状，Graph tool 也不被迫改契约。`FundProfileSnapshot` 是可序列化内部 DTO，不把 ORM
实例带出 Session。三个调用方迁移完成后删除重复 fetch/persist 编排。

AkShare 始终串行：前置单元已经移除 `_collect_refresh_data()` 和
`_collect_profile_frames()` 中无收益或绕锁的线程 fan-out；本切片不再增加线程。共享刷新
操作的价值是让 fetch/persist 和结果语义只有一份实现，各触发方仍保留自己的流程组合和
任务状态。

## 6. 后续维护性改造路线

### 6.1 Watchlist 写操作簇

当新增自选稳定后，按变化频率迁移：

1. initial holding；
2. transaction add/remove；
3. pending buy confirm/cancel；
4. membership patch/remove；
5. enriched list query。

目标是把 `watchlist_service.py` 从“所有规则和 Session 包装的中心”降为兼容 facade。第二个
写用例迁移完成后，再评估抽取 slice-local UoW；若两个用例只共享 `session_scope()`，就
继续使用具体实现，不制造 Protocol。

### 6.2 消除 Fund/Diagnosis 循环依赖

建立窄读取端口：

```text
Diagnosis Use Case → FundSummaryReader → Fund Query Adapter
```

`FundSummaryReader` 是 Diagnosis-owned port，用于反转依赖，不作为“共享层”抽象，因此不
要求两个 port 消费者；它的 Fund Query Adapter 复用现有 Summary query，后者继续同时服务
Fund API 与 Diagnosis。`FundSummary` 只包含诊断确实需要的数据，不返回整个 ORM 模型或
通用 dict。迁移完成标准是：

- 两个 service 不再互相 import；
- 不再新增 lazy import；
- 依赖图中对应强连通分量消失；
- Fund 刷新和 Diagnosis 规则可以分别测试。

### 6.3 拆分外部数据 Provider

把 `data_collector.py` 逐步拆为内部模块：

```text
backend/integrations/akshare/
  gateway.py       # 全局串行、重试、限流、调用包装
  funds.py         # 基金获取及同域 DataFrame 规范化
  markets.py       # 市场获取及同域 DataFrame 规范化
```

迁移约束：

- `gateway.py` 只有在新 Fund Provider 与仍处兼容期的 market collector 同时改用它时才
  抽取；否则全局锁/重试暂留现有 facade，不能创建单消费者 shared gateway；
- Provider 不 import Session、Repository 或 ORM Model；
- 基金和市场的 normalizer 先留在各自同域模块；只有两边已经重复使用的标量转换才抽到
  私有 `_normalization.py`，避免产生新的大杂烩；
- 数据库读取如 announcement 查询移到 application/query；
- 原文件先作为 forwarding facade，调用方归零后删除；
- 每个 facade 都记录剩余最终调用者，避免永久双实现。

### 6.4 Briefing Feature

后端先解决数据收集的重复查询，前端再拆页面：

```text
frontend/src/features/briefing/
  contracts.ts
  normalize.ts
  use-briefing-workbench.ts
  BriefingScreen.tsx
  FeedbackPanel.tsx
  modules/
```

`app/briefing/page.tsx` 最终只负责页面组合。版本识别、query/mutation、evidence 状态和模块
规范化属于 Feature；单个 renderer 不感知整个响应对象。

### 6.5 Keyed in-process job runner

Watchlist preload 与 Diagnosis refresh 都迁移后，再建立
`backend/runtime/in_process_jobs.py`：

- `submit(key, job_id, task) -> SubmitResult`，结果明确区分
  `accepted`、`deduplicated(existing_job_id)` 和 `rejected(reason)`；
- 只统一 key 去重、锁、executor 提交、完成清理；
- Feature 保留自己的状态 schema、持久化和结果语义；
- 设置有界队列或明确拒绝策略，不允许无界堆积；
- queue 满、executor submit 抛错和 shutdown 都必须释放 active claim，并通知 Feature 把
  已暴露状态收敛到终态；
- 应用 shutdown 时有明确停止行为。

仓库已有的 `backend/services/shared/process_singleflight.py` 继续负责同步临界区的 keyed
互斥；新 runner 负责“提交后异步完成”的任务生命周期。一个业务流只能选择其中一个作为
去重事实源，不能先用 lock 再维护第二套 active map。若实现中共享底层 key registry，应是
私有实现；两个公开契约仍保持上述职责差异。

它不是通用任务平台，也不解决多进程选主。Briefing/Market 只有在生命周期一致时才接入。

### 6.6 Facade 退出条件

| Facade | 最终已知调用者 | 删除条件 |
|---|---|---|
| `fund_service.refresh_fund` | Funds Route、fund Graph tool、auto lookup、Scheduler、Watchlist preload | 全部改用两个具体刷新操作，并各自通过旧响应契约 |
| `watchlist_service.py` | Watchlist Routes 与 note-only Graph tools | HTTP 用例全部迁移；Graph 只保留窄 adapter，不再依赖 517 行总 facade |
| `data_collector.py` | Fund/Profile/Market services 与 announcement 路径 | 调用者分别改用 AkShare providers 或 application query，`rg` 结果归零 |
| `frontend/src/lib/api.ts` 的 Watchlist 段 | Watchlist 页面、Drawer 及 hooks | 全部改用 Feature public API；全局 API 仍可承载未迁移领域 |

实施计划必须用当时的静态调用清单补全表格；删除标准是生产调用归零和兼容测试迁移，不是
仅凭文件变薄。

## 7. 性能优化设计

### 7.1 第一优先：批量化与删除重复工作

#### Briefing 指标

新增批量查询/计算入口：

```text
get_period_returns_for_funds(fund_codes, periods={"1d", "1w", "1m"})
  → 一条分区查询为每只基金读取最近 22 个 NAV 点
  → 按 fund_code 分组
  → 每组内一次计算三个周期
```

验收：

- 30 只基金不再产生约 90 次 NAV 历史查询；
- 不把“多次全历史”替换成“一次超大全历史”；1m 最大窗口为 21 个交易日，只读取计算所需
  的 22 个累计净值点；
- 数据不足的基金继续对对应周期返回 `None`，不改变现有语义；
- 与逐基金逐周期结果等价；
- 记录 SQL 次数、读取行数、p50/p95。

Briefing 还应优先读取 freshness TTL 内已存在的 `MarketSnapshot` 和 evidence，只有字段
缺失或过期才补抓。记录 reused/refetched source 数，避免 15:35、16:00、17:00 三个任务
重复获取相同市场数据。

#### Profile 全局数据

规模、排名、经理和 SINA fallback category 等 DataFrame 第一版按一次 refresh batch 获取
一次，每个基金只在内存中筛选自己的行。只有 batch-scoped reuse 的收益和 freshness 语义
验证后，才考虑跨 batch TTL cache。

#### 批量数据库写入

- NAV 使用可配置且有上限的多行
  `INSERT ... ON CONFLICT (fund_code, nav_date) DO NOTHING RETURNING ...`，不先把全部已有
  日期加载到 Python；inserted count 来自 `RETURNING`，已有同日 NAV/source 不被覆盖；
- Market 数据在 SQL 中限定范围或直接处理冲突，不扫描全部历史；
- Knowledge 预取分类状态和已有 match key；
- 向量和匹配结果使用 executemany/批量 upsert，一批只 flush 一次。

Knowledge 还要避免每轮全量 documents × funds：ingestion/profile 返回 changed document
IDs/fund codes，只重算受影响范围；全量 rebuild 保留为显式维护任务。批量 API 的 batch
size 从 Settings 读取并有保守默认值，避免一次 SQL 或参数集合无限增长。

### 7.2 第二优先：有边界的缓存

每个缓存必须在实现前写清：

| 项目 | 必须回答 |
|---|---|
| Key | 哪些参数决定结果 |
| Value | 缓存原始数据、规范化数据还是领域结果 |
| TTL | 多久后过期，依据是什么 |
| Source | 来源和 `as_of` 如何保留 |
| Invalidation | 哪个写操作或刷新事件使其失效 |
| Single-flight | 同一个 key 过期时是否只允许一个加载者 |
| Capacity | 最大 key/字节数和淘汰策略 |
| Failure | 加载失败时返回旧值、空值还是错误 |

优先缓存跨基金复用的原始/规范化全局数据，不缓存用户可修改的派生结果。缓存命中与未命中
必须产生等价业务输出，并可通过配置快速关闭。

### 7.3 第三优先：有界协程并发

#### 保持同步的路径

- **AkShare**：现有全局锁是为规避底层运行时崩溃；并发线程不会提高吞吐，反而可能绕开
  锁。保持单并发；
- **SQLAlchemy + psycopg2**：继续使用同步 Session；本轮没有证据支持整体 async engine
  迁移；
- **APScheduler 生命周期**：保持同步；
- CPU 计算很轻的 metrics：通过批量化减少重复，不用协程包装。

特别需要修正的风险是：外层持有 AkShare 锁时，内部再创建多个 worker 调用 AkShare，子线程
并不继承锁所有权，可能违反串行约束。该路径应改成串行调用。`future.cancel()`、
`wait_for(to_thread(...))` 或 `shutdown(wait=False)` 都不能硬取消已经运行的阻塞 C 调用；
HTTP timeout 只约束对应 I/O；同步调用整段的硬截止必须由可终止子进程提供，不能伪装成
协程取消。

#### 可以使用协程的路径

只有同时满足以下条件才使用 `asyncio.TaskGroup`/`gather`：

1. 调用彼此独立；
2. 底层客户端原生支持 async；
3. 没有共享 SQLAlchemy Session；
4. 有全局和 per-host 并发上限；
5. 有连接、读取和总超时；
6. 明确部分失败、取消和重试语义。

首批候选：

- 非 AkShare 的独立 HTTP evidence 来源；
- 可原生 async 的政策/FRED 等数据源；
- 无法批量提交时的 LLM 分类请求。

Evidence 当前还不能直接作为性能基线：现有 adapter client ownership/injection 不一致，
部分 Policy/FRED 调用会收到 `client=None` 并返回空结果。试点前必须先统一同步 client
注入，并为每个候选来源建立至少一个成功取数 smoke test；然后才设计真正的 async adapter
和共享 `AsyncClient`，不能把现有同步 `fetch()` 直接塞进 `TaskGroup`。

以下只是首次试验的安全上限，不是半年内必须达到的并发目标：

| 资源 | 初始上限 |
|---|---:|
| AkShare | 1 |
| 独立 HTTP 全局 | 4 |
| 单 host HTTP | 1–2 |
| LLM | 2–4，并服从 rate limit |
| 后台 DB worker | 共享进程级 limiter；稳态总量小于 `pool_size=5`，为请求留余量 |

示意结构：

```python
async with asyncio.TaskGroup() as group:
    for source in sources:
        group.create_task(fetch_with_limits(source))
```

limiter 和 `AsyncClient` 是进程/服务生命周期对象，并配置连接池上限，不能每个请求临时
创建。`TaskGroup` 外设置整体 batch deadline；`fetch_with_limits()` 在全局和 per-host
semaphore 内执行，并使用 connect/read/write/pool timeout。重试只用于幂等的瞬态失败，
遵守 `Retry-After`、使用 jitter，并计入同一个总 deadline。若一个任务失败：

- 必需来源失败：取消同组任务并返回整体失败；
- 可选来源失败：捕获为结构化 warning，其他结果继续；
- 调用方取消：向下传播，不吞 `CancelledError`。

`asyncio.to_thread()` 只允许在已经是 async 的边界内临时接入少量、线程安全的阻塞调用；
它不用于把整个同步业务栈“染成 async”，也不为每个请求创建新的线程池。提交前先获取
worker 容量；协程被取消后，底层线程真正结束前不能释放安全锁、容量或把 job 标成完成。

#### 数据库与并发边界

- 网络获取阶段不持有事务；
- 并发任务不得共享 Session；
- 默认先完成网络收集，再按明确的原子一致性单元使用一个 Session 批量持久化；
- 只有业务允许独立、幂等和部分成功的单元才可并发落库；同步 Session 在受限 worker 中
  运行，每个 worker 独占 Session，并共享进程级 DB limiter；
- `max_overflow=10` 只作突发缓冲，不计入日常容量；记录 pool wait、checkout duration 和
  overflow 使用量；
- 不把 ORM 实例跨线程/协程传递。

### 7.4 前端任务轮询

优先使用已有 job id/status，而不是引入 SSE/WebSocket：

- 每个 Feature 明确自己的 active/terminal 集，不假定全局只有 `pending/running`；
  Watchlist 使用 `pending/running`，Diagnosis 还包含 `started`；
- 终态只做一次语义化 cache effect；
- Market Snapshot 和 Briefing 先提供按返回 `job_id` 查询的状态，再改为 job polling；
- 完成响应暴露 `finished_at` 或单调 `refresh_generation`；不能用 `trade_date`、`as_of` 或
  不会在 upsert 时更新的 `created_at` 冒充版本；
- 页面不可见是否暂停由各 Feature 的用户体验契约决定，不作为全局规则；Watchlist 首切片
  维持现状；
- Briefing latest 不无限固定轮询，改为 stale policy 或显式刷新。

## 8. 六个月路线图

每个月只设一个必达主题；同月列出的“候选”必须在必达项完成且有基线证据后才进入。

### 第 0–2 周：安全与可信基线

- 恢复 Scheduler 同步契约；
- 移除两处 AkShare 线程 fan-out，修正文档和实现中的超时/取消语义；
- 为首批路径记录生产代码重复点、SQL/外部请求次数和基准耗时；
- 只为触达 Feature 建立可验证的行为测试入口；
- CI 加入前端 test、typecheck、build，作为后续提交护栏。

### 第 1 月：首个端到端参考切片

- 原子新增自选；
- Watchlist add/preload 的最小 Feature、响应规范化和 confirmed cache update；
- 从现有 API client 抽出唯一 transport，并让旧 API 与新 Feature 共用；
- 记录首切片前后的生产文件触达数和重复规则删除点。

### 第 2 月：消除最高优先级依赖环

- 建立 Diagnosis-owned `FundSummaryReader`；
- 让现有 Fund Summary query 同时服务 API 与该 adapter；
- 消除 `fund_service ↔ diagnosis_service` 双向 import 和相关 lazy import；
- 候选：批量读取 peer NAV/profile，前提是先记录当前 query count。

### 第 3 月：收拢 Fund/Watchlist 应用边界

- 建立两个具体刷新操作并迁移 preload、手动刷新和 Scheduler；
- 迁移一个高频 Watchlist 写用例，决定 UoW 是否有第二个真实消费者；
- 手动刷新与 preload 共用 `fundDataChanged` cache effect；
- 候选：再迁移 transaction/pending buy，使 membership/portfolio cache effect 获得两个
  真实调用方。

### 第 4 月：AkShare Fund Provider

- 拆出 fund 获取/同域规范化；只有现有 market collector 同时接入并删除旧锁/重试实现时
  才把 gateway 提升为共享模块；
- 本月迁移的 fund Provider 不访问数据库；announcement DB 查询随后续 market 切片迁移；
- NAV 改为有界批量 `DO NOTHING RETURNING`；
- Profile 全局帧先做 batch-scoped reuse；
- market provider、Market/Knowledge 批量写作为后续候选，不列为本月必达。

### 第 5 月：Briefing 纵向切片

- 后端按每只基金最近 22 个 NAV 点批量计算三个周期；
- 优先复用 freshness TTL 内的 market snapshot/evidence；
- 前端 Feature shell、typed normalizer 和独立 renderer；
- 只把被修改部分的源码形状断言替换为行为测试。

### 第 6 月：证据驱动的收敛

- 在以下两个主题中选择当时收益更高的一项作为必达：
  - Watchlist/Diagnosis 生命周期一致时抽 keyed in-process job runner；
  - 删除无调用方 facade 和兼容别名；
- 另一项作为 stretch；
- 只有 evidence client 注入已修复、成功 smoke test 已建立且 profiling 显示网络等待占主导
  时，才做非 AkShare HTTP async 试点；
- 复查大文件职责、依赖环、重复规则和已引入性能复杂度，删除没有达到收益门槛的方案。

## 9. 测试与 CI 护栏

测试的任务是允许生产代码安全变化，而不是规定代码必须写成某种字符串形状。

### 9.1 每个切片的最低护栏

- 应用用例：成功、重复、业务失败、后置副作用失败；
- Repository：唯一约束、并发 get-or-create、rollback；
- Route：协议映射和公开响应兼容；
- 前端：用户动作、即时缓存结果、终态轮询和错误展示；
- 架构：新增及已迁移切片不出现逆向 import、Route ORM、Provider DB 访问或内部 commit；
  未迁移旧代码不作为首切片的全仓阻断。

### 9.2 测试迁移规则

- 不一次性重写 24 个会读取源码的前端 Node 测试；其中只有使用源码形状断言的部分需要
  逐步替换，编译后运行纯函数的行为测试可以保留；
- 修改一个 Feature 时，为它增加 Vitest/RTL 行为测试，再删除该范围内等价的源码正则；
- 不把私有函数名、目录文本或 import 字符串作为主要验收；
- 架构约束可以继续使用 AST/静态检查，因为其目标本来就是代码结构；
- 性能测试使用固定数据规模和可比较的冷/热缓存场景，不要求单次绝对时间稳定。

### 9.3 CI 最低顺序

1. 后端快速 unit/architecture；
2. 前端现有 Node test、独立 Vitest/RTL component script 与 `tsc --noEmit`；
3. 前端 production build；
4. PostgreSQL integration；
5. 代表性性能基准只做趋势记录，已确认的 query/request count 回归才设硬门禁。

## 10. 发布、回滚与停止条件

### 10.1 提交边界

每个合并单元应满足：

- 生产调用方和新边界在同一单元接通；
- 不提交“未来可能使用”的空抽象；
- 旧 facade 与新实现不同时拥有业务规则；
- 有明确的兼容终点；
- 能通过回退该单元恢复旧行为。

数据库 schema 和公开 API 不在第一轮变化范围内，因此回滚主要是代码级回退。

### 10.2 停止条件

遇到以下情况停止扩张并回到较小改造：

- 新抽象只有一个生产调用方；
- 接口开始累积多个布尔 mode；
- 为迁移一个行为需要同时修改大量无关领域；
- 性能方案没有降低耗时、请求数或资源风险；
- 并发让错误率、限流或 DB pool 等待上升；
- 新旧路径都长期保留真实业务逻辑；
- 测试只证明实现字符串，没有证明行为。

### 10.3 风险与缓解

| 风险 | 缓解 |
|---|---|
| 新旧模式并存增加理解成本 | 每个 facade 记录最终调用者和删除条件，按 Feature 完整迁移 |
| 原子写改变边缘响应 | 固定公开契约测试，并发测试使用真实 PostgreSQL |
| 缓存出现陈旧数据 | 明确 TTL、invalidation、source/as_of 和关闭开关 |
| 协程放大外部限流 | semaphore、per-host limit、timeout、Retry-After 和 jitter |
| 线程取消被误解为硬超时 | 阻塞 AkShare 串行；I/O timeout 放 transport，整段硬截止用可终止进程 |
| 批量查询占用过多内存 | 设定 batch size，按 fund/date 范围读取并记录行数 |
| 拆大文件变成纯搬家 | 每次拆分必须同步收紧职责或删除重复调用 |

## 11. 完成标准

### 11.1 第一阶段 DoD

前置单元与两个业务切片完成时，必须全部满足：

1. Scheduler 公开方法和全部调用方恢复同步，无未 await warning；
2. 两处 AkShare 线程 fan-out 被移除，串行调用可验证，超时文案不再承诺线程硬取消；
3. 新增自选只有一个事务所有者，`created` 来自原子 insert，并发请求只有一行；
4. commit 失败不 dispatch；submit 失败不留下 active claim 或永久 pending；
5. 普通 add/preload 进入 Watchlist Feature；initial-holding、edit 等未迁移行为不变；
6. POST 成功后按 `fund_code` 即时合并已有 cache，未初始化 cache 不被不完整行污染；
7. 现有 API client 与 Watchlist Feature 只使用一份 transport/error parser；
8. preload、Scheduler 和手动刷新复用两个具体刷新操作，同时保持各自旧失败语义和
   `session=` 注入契约；
9. 本阶段触达的公开 API、Graph tool、polling 和 toast 契约通过行为验证。

### 11.2 六个月结果

半年路线完成时希望验证：

1. Fund/Diagnosis 不再形成依赖环；
2. Watchlist 高频写操作逐步进入应用边界，UoW 只在证明有第二个消费者时出现；
3. 跨资源 cache effect 只在至少两个现有动作共同使用时提升为语义 helper；
4. AkShare fund Provider 与数据库分离，旧 facade 有明确剩余调用者和删除条件；
5. Briefing 的三个周期收益不再逐基金重复加载全量 NAV，并优先复用新鲜市场数据；
6. 每个共享组件至少有两个真实生产调用方，并删除对应重复实现；
7. 经基线证明有收益的 batch/cache/async 项通过各自专项验收；没有收益的候选不实施或被
   删除；
8. 测试与 CI 能防止公开行为回退，但没有反过来固化内部实现。

### 11.3 观察指标

以下用于季度复盘，不作为单次切片的虚假精确门槛：

- 代表性需求触达的生产文件数；
- 同一业务规则/cache key 列表的生产实现点数；
- 依赖强连通分量和 lazy import 数量；
- facade/兼容别名及其剩余生产调用者；
- 固定 1/10/30 基金 workload 的 p50/p95、SQL 数、外部请求数和读取行数；
- executor queue depth、孤儿任务、AkShare lock wait、DB pool wait/overflow；
- 因纯实现重排而修改的测试比例。

## 12. 后续设计门禁

用户书面确认本设计后，下一步才编写实施计划。实施计划必须：

- 细化到文件、调用方、删除点和验证命令；
- 把前置单元、首个纵向切片和刷新复用切片拆为可独立提交的小任务；
- 先记录性能基线，再实现批量、缓存或并发；
- 每项共享抽象列出至少两个现有生产调用方；
- 不把“改成 async”本身当作性能成果；
- 不扩大到本设计列出的非目标。
