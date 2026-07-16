# Briefing 领域拆分硬切换设计

**版本**：1.0
**日期**：2026-07-16
**状态**：已确认

## 1. 背景与目标

当前 Briefing 领域的主要实现集中在两个大型模块：

- `backend/services/briefing/briefing_service.py` 同时负责数据采集、内容生成、同步工作流、
  持久化适配、后台任务和运行状态；
- `backend/services/briefing/module_briefing.py` 同时负责简报类型配置、确定性模块构建和
  V2 内容编排。

虽然 `briefing/` 下已经存在 `types.py`、`collectors.py`、`modules.py`、`composer.py`、
`persistence.py` 和 `jobs.py`，其中多个文件仍只是旧模块的 re-export 或占位入口。这使
真实职责边界仍停留在两个大型文件中，也让 API、Scheduler、Tools 和测试继续依赖宽
service facade。

本次按能力拆分 Briefing 领域，并一次性硬切换所有生产和测试消费者。迁移完成后删除
`briefing_service.py` 与 `module_briefing.py`，不保留 re-export、弃用模块、旧导入兼容层
或双实现。

本阶段是纯结构迁移：保持 Prompt、简报内容、异常聚合、事务边界、持久化格式、接口
响应和业务单飞语义不变。

## 2. 范围

### 2.1 本次包含

- 将数据采集、确定性模块、内容生成、持久化、同步编排和后台任务移动到明确模块；
- 将 `BriefTypeProfile` 与 `ModuleSection` 移到稳定类型模块，消除当前仅为规避循环依赖
  使用的 `TYPE_CHECKING` 反向引用；
- 使用私有状态模块隔离进程内运行状态与锁，避免 `jobs → workflow → jobs` 循环依赖；
- 将 API、Scheduler、market tools、service 导入契约和全部测试切换到新入口；
- 删除旧模块及其 service compatibility 映射；
- 新增硬切换、依赖方向、显式模型注入和事务所有权契约测试。

### 2.2 本次不包含

- 不改变 Prompt 文本、模型选择、模型参数或输出解析语义；
- 不改变简报 JSON、Markdown、sections、warnings、missing data 等返回字段；
- 不改变数据库表、repository API 或序列化格式；
- 不改变 API 路径、请求体、响应体或 Scheduler 调度配置；
- 不清理现有宽异常或重新定义业务降级规则；
- 不引入 Celery、Redis、数据库任务表或新的线程池框架；
- 不实现跨进程或跨副本单飞；
- 不引入 PostgreSQL advisory lock；
- 不调整市场证据 adapter、数据源策略或外部请求重试；
- 不在结构迁移中进行性能优化或算法重写。

Scheduler 解耦和多进程互斥属于后续独立工作，不能扩大本次迁移边界。

## 3. 方案决策

采用“能力模块 + 同步工作流编排”的硬切换方案：

```text
backend/services/briefing/
├── __init__.py
├── types.py
├── collectors.py
├── modules.py
├── composer.py
├── persistence.py
├── workflow.py
├── jobs.py
├── _state.py
└── prompts.py
```

选择该方案是为了让数据采集、确定性计算、模型生成、数据库访问和运行机制分别具有可
测试边界，同时保留一个明确的同步用例编排入口。私有 `_state.py` 只隔离共享状态，
不成为新的全局 service locator。

不采用以下方案：

1. **按两个旧文件机械拆分**：改动较小，但仍会把多类职责聚合在新文件中，无法形成
   稳定的能力边界。
2. **建立新的宽 service facade**：消费者改动较少，但会继续隐藏实际依赖，并把旧模块
   的 patch 习惯迁移到新 facade。
3. **保留旧入口作为兼容层**：会产生两个公开入口和无期限删除成本，不符合当前硬切换
   决策。

## 4. 模块职责与公开入口

### 4.1 `types.py`

作为 Briefing 领域的稳定叶子模块，包含：

- `ChatModel`、`StreamableChatModel` 等 Protocol；
- `WatchlistSnapshot`、`MarketSnapshot`、`EvidenceRecord`、`BriefingInput`、
  `ModuleEnvelope`、`BriefingResult` 等现有 DTO；
- 从旧 `module_briefing.py` 移入的 `BriefTypeProfile` 与 `ModuleSection`。

该模块不得导入其他 Briefing 业务模块，也不得通过 `TYPE_CHECKING` 引用已删除的旧
模块。

### 4.2 `collectors.py`

负责确定性数据采集和数据质量计算：

- `compute_data_quality`；
- `collect_watchlist_snapshot`；
- 市场快照、市场宽度、行业快照和基金名称查询 helper；
- 现有安全取值与缺失数据收集逻辑。

该模块可以依赖基金、自选、市场数据 service 和市场证据入口，但不得依赖 composer、
workflow、jobs 或 API 层。

### 4.3 `modules.py`

负责简报类型配置和确定性模块构建：

- brief type profiles 与 `get_brief_type_profile`；
- 各类 module builder；
- `run_module_builders`；
- quick summary 和 data statement runner。

模块 builder 的执行顺序、输入输出和降级行为保持不变。

### 4.4 `composer.py`

负责内容生成边界：

- `compose_briefing`；
- `compose_briefing_v2`；
- Prompt 组装；
- 显式注入模型的调用；
- JSON、Markdown 包裹 JSON 和普通文本的现有解析与降级。

`composer.py` 通过模块引用调用 `modules`，便于测试替换明确边界；不得导入 workflow、
jobs、API 或 graph model 的具体实现。

### 4.5 `persistence.py`

负责 Briefing 持久化用例适配：

- 读取最近或指定日期简报并完成现有字段反序列化；
- 提供窄写入 helper，调用 Briefing repository 完成 upsert；
- 保持外部 Session 只 `flush()`、事务由调用方拥有的约定。

repository 继续只负责数据访问，不得在本次迁移中增加 `commit()` 或 `close()`。

### 4.6 `workflow.py`

作为同步应用用例入口，公开 `run_daily_briefing`。它只负责：

- 按现有顺序编排证据准备、数据采集、内容生成和持久化；
- 根据是否传入外部 Session 选择现有事务路径；
- 聚合阶段结果、warnings 和 errors；
- 更新最近运行状态。

它不重新实现 collector、composer 或 repository 逻辑，也不导入 `jobs.py`。

### 4.7 `jobs.py`

作为进程内后台任务入口，公开：

- `start_run_async`；
- `get_last_run`；
- `reset_for_tests`。

它负责线程池提交、活动任务标记和同进程业务单飞，只包装
`workflow.run_daily_briefing`，不复制同步工作流。

### 4.8 `_state.py`

作为私有运行状态模块，封装：

- 最近一次运行状态；
- 当前活动任务标记；
- 对应的普通进程锁和线程安全读写操作。

`_state.py` 不导入任何 Briefing 业务模块。`workflow.py` 与 `jobs.py` 可以共同依赖它，
从而避免循环导入。该状态仅具有单进程语义。

### 4.9 `prompts.py` 与 `__init__.py`

`prompts.py` 保持现有实现。`briefing/__init__.py` 不再 eager import 或重新导出旧 service，
也不建立新的宽 facade；消费者必须从具体能力模块导入。

## 5. 依赖方向与消费者硬切换

依赖方向固定为：

```text
API ───────────────→ jobs ───────→ workflow
Scheduler ───────────────────────→ workflow
Market tools ────────────────────→ persistence

jobs ──────────────→ _state ←──── workflow
workflow ──────────→ collectors / composer / persistence
composer ──────────→ modules ────→ types
collectors ──────────────────────→ types
persistence ─────────────────────→ repository
```

生产消费者一次性切换：

- Briefing API route 导入 `briefing.jobs.start_run_async`；
- Scheduler 导入 `briefing.workflow.run_daily_briefing`；
- market tools 导入 `briefing.persistence.read_briefing`；
- `backend/services/__init__.py` 删除两个旧模块的 compatibility 映射；
- `briefing/__init__.py` 不提供旧符号别名。

新模块内部优先导入模块而不是把被测试替换的函数绑定成本地别名。例如 workflow 通过
`collectors.collect_watchlist_snapshot(...)` 调用采集器，使 monkeypatch 目标与真实
依赖边界一致。

## 6. 数据流与事务边界

同步工作流保持以下阶段：

```text
Scheduler / API background job
              │
              ▼
workflow.run_daily_briefing
              │
              ├─ 1. 证据准备
              │     PostgreSQL 短事务
              │
              ├─ 2. 数据采集
              │     collectors.collect_watchlist_snapshot
              │     不持有长期数据库事务
              │
              ├─ 3. 内容生成
              │     composer.compose_briefing
              │       └─ modules.run_module_builders
              │     LLM 调用期间不持有数据库事务
              │
              ├─ 4. 简报持久化
              │     persistence write helper
              │     PostgreSQL 短事务
              │
              └─ 5. 更新运行状态
                    _state
```

事务规则：

- 未传入外部 Session 时，每个数据库阶段继续使用独立的 `session_scope()`；
- 传入外部 Session 时继续只执行 `flush()`，由调用方决定 commit 或 rollback；
- 网络请求、行情采集和 LLM 调用期间不得持有数据库事务；
- 不把整个 `run_daily_briefing` 包裹进单一事务；
- 不为结构迁移新增数据库锁、retry 或任务记录。

现有 DTO、字段形状和序列化格式在模块间原样传递，不新建第二套中间协议。

## 7. 异常处理与任务状态

### 7.1 异常处理不变量

- 单个采集源失败继续记录到 `missing_data` 或 `warnings`，不直接终止整份简报；
- 单个模块构建失败时保留其他成功模块，并继续聚合失败信息；
- LLM 返回非法 JSON、Markdown 包裹 JSON 或普通文本时沿用现有解析与降级逻辑；
- 持久化失败时当前事务回滚，并在最终运行结果中记录失败；
- `run_daily_briefing` 顶层继续返回结构化结果，不向 Scheduler 或后台线程抛出普通业务
  异常；
- 不新增静默吞掉编程错误或不可恢复系统错误的逻辑。

日志按实际阶段归属：collector 记录数据源问题，composer 记录模型与解析问题，
persistence 记录数据库读写问题，workflow 记录总体执行结果，jobs 记录后台提交与重复
运行。日志文案只在移动所必需时调整，不改变可观察的失败分类。

### 7.2 进程内状态与单飞

`_state.py` 继续维护等价的最近运行与活动任务状态。具体内部表示可沿用现有字典与字段，
但对外字段不得变化。

- 同步 workflow 更新最近运行状态；
- jobs 管理活动 job ID 和线程池生命周期；
- 后台任务无论成功或失败都必须在 `finally` 中释放活动任务标记；
- `reset_for_tests()` 同时清理最近运行与活动任务状态；
- 同一进程同时只允许一个 Briefing 后台任务运行；
- 使用普通进程锁保护进程内状态，不保留或引入 SQLite 数据库锁语义。

本次不承诺跨进程单飞。未来多 Scheduler worker 场景应独立选择 PostgreSQL advisory
lock、任务表原子抢占或唯一约束。

## 8. 行为不变量

除 import 路径和代码所在文件外，迁移必须保持：

- API 路径、状态码、请求体和响应字段；
- Scheduler 调用参数和同步运行结果；
- brief type profile、模块顺序和模块输出；
- Prompt 内容、模型注入方式和模型调用参数；
- JSON、Markdown 和纯文本解析策略；
- warnings、errors、missing data 和 data quality 的生成规则；
- 市场证据 ingest/search 的顺序与失败隔离；
- 简报 upsert、读取和字段反序列化；
- 外部 Session 与内部短事务的所有权；
- 最近运行状态字段和同进程单飞语义；
- 测试 reset 能力。

纯结构迁移中发现的潜在业务缺陷只记录，不顺带修复；需要行为变化时另立规格。

## 9. 测试迁移策略

### 9.1 按能力拆分测试

现有 `test_briefing_service.py` 与相关测试按职责迁移或重组：

- `test_briefing_collectors.py`：数据质量、自选快照、市场宽度、行业和行情采集，以及单一
  数据源失败降级；
- `test_briefing_modules.py`：brief type 配置、确定性 module builders、quick summary 和
  data statement；
- `test_briefing_composer.py`：显式模型注入、Prompt、输出解析，以及模块或模型失败降级；
- `test_briefing_persistence.py`：读取反序列化、写入 flush 和外部 Session 事务所有权；
- `test_briefing_workflow.py`：同步编排顺序、事务阶段、失败聚合和最近运行状态；
- `test_briefing_jobs.py`：后台提交、同进程单飞、成功或失败后的释放，以及状态 reset。

测试名称是否物理拆成全部六个文件可在实施计划中按现有测试规模安排，但测试关注点和
patch 目标必须属于对应能力模块。

### 9.2 Patch 目标

测试直接 patch 新的真实依赖边界，例如：

```python
monkeypatch.setattr(
    workflow.collectors,
    "collect_watchlist_snapshot",
    fake_collector,
)
```

禁止继续 patch `backend.services.briefing.briefing_service` 或
`backend.services.briefing.module_briefing`。route、Scheduler 和 tool 测试同步改为 patch
各自导入的新入口。

### 9.3 结构与依赖契约

先增加会失败的硬切换契约，实施完成后要求：

- `briefing_service.py` 和 `module_briefing.py` 不存在；
- Python 生产代码和测试中不存在两个旧模块的导入或 monkeypatch 路径；
- `types.py` 不导入其他 Briefing 业务模块；
- `collectors.py` 不导入 composer、workflow、jobs 或 API；
- `composer.py` 不导入 workflow、jobs、API 或 graph model 具体实现；
- `workflow.py` 不导入 `jobs.py`；
- repository 继续不调用 `commit()` 或 `close()`；
- composer 与 workflow 继续满足显式模型注入契约；
- package `__init__.py` 不建立新的宽兼容 facade。

### 9.4 验证层级

按以下顺序验证：

1. types、collectors、modules、composer、persistence、workflow、jobs 定向测试；
2. Briefing route、Scheduler、market tools 和 market evidence 相关测试；
3. service import compatibility、AST 边界与事务所有权契约；
4. PostgreSQL worker schema 下完整 backend 测试；
5. `compileall`、`git diff --check` 和旧路径全文门禁。

## 10. 验收标准

迁移完成必须同时满足：

1. 删除 `briefing_service.py` 和 `module_briefing.py`；
2. 生产代码和测试中不存在旧模块导入、符号别名或 patch 路径；
3. API、Scheduler 和 market tools 分别使用 jobs、workflow 和 persistence 新入口；
4. `BriefTypeProfile` 与 `ModuleSection` 位于 `types.py`，不存在旧模块类型反向引用；
5. Prompt、返回字段、持久化格式和 API 响应保持一致；
6. 网络和 LLM 调用期间不持有数据库事务；
7. repository 仍只 flush，事务仍由调用方拥有；
8. 同进程 Briefing 业务单飞与运行状态语义保持不变；
9. 定向测试、导入契约和 PostgreSQL 完整测试套件通过；
10. 不新增 SQLite fixture、SQLite 锁、SQLite retry 或 SQLite 兼容分支。

## 11. 提交边界与回滚

设计文档与实施计划分别独立提交。实现阶段按测试驱动拆成可审查步骤，最终硬切换提交
必须原子包含：

1. 新模块职责实现；
2. 所有生产消费者导入切换；
3. 所有测试与 patch 目标迁移；
4. 硬切换、依赖方向和事务所有权契约；
5. 删除两个旧模块及 compatibility 映射。

由于不保留兼容层，实现提交不可只移动一半消费者。回滚以整体 revert 硬切换实现提交
完成，不通过恢复双入口或临时 re-export 回滚。
