# Scheduler 解耦硬切换设计

**版本**：1.0

**日期**：2026-07-16

**状态**：已确认

## 1. 背景与目标

当前 `backend/scheduler/scheduler.py` 同时承担 APScheduler 生命周期、Settings 解析、
trigger 构造、九类任务定义、业务 callable 组合和单飞包装。任务注册契约散落在一段
较长的命令式流程中，导致调度元数据难以整体审查，运行时模块也直接依赖多个领域
service。

仓库已有 `backend/scheduler/jobs.py` 中的 `JobSpec` 雏形，但生产调度仍直接调用
`scheduler.add_job(...)`，因此该抽象尚未成为实际边界。

本次采用声明式任务注册表完成硬切换：任务规范、业务 callable、注册表和 APScheduler
生命周期分别归属独立模块。迁移完成后删除旧 `scheduler.py` 和 `jobs.py`，不保留
re-export、弃用模块、兼容导入层或双实现。

本阶段只做结构迁移，保持任务集合、配置、触发参数、业务单飞、错误语义、健康检查和
应用生命周期行为不变。

## 2. 范围

### 2.1 本次包含

- 建立不可变的 Scheduler spec 类型；
- 把领域任务 callable 与 APScheduler runtime 分离；
- 由单一 registry 根据 Settings 生成完整任务定义列表；
- 让 runtime 只负责构造、注册、启动、读取和关闭 APScheduler；
- 更新 API、应用入口、测试和 monkeypatch 目标到新入口；
- 新增任务注册快照、执行函数、runtime 和硬切换结构契约；
- 删除 `backend/scheduler/scheduler.py` 与 `backend/scheduler/jobs.py`。

### 2.2 本次不包含

- 不修改 job ID、执行顺序、启用默认值、cron/interval 或 timezone；
- 不修改 `max_instances`、`coalesce`、`misfire_grace_time`、jitter 或 start delay；
- 不调整任务频率、补跑策略、日志级别或异常传播语义；
- 不引入 Celery、Redis、持久化 job store 或新的调度框架；
- 不实现多 backend worker 选主；
- 不新增 PostgreSQL advisory lock；
- 不修改领域 service、任务表状态机或业务算法；
- 不修复 executor `.submit()` 自身抛错时可能残留 active claim 的可靠性问题；该问题
  作为后续独立行为修复处理。

## 3. 方案决策

采用“声明式 JobSpec registry + 独立 runtime”的方案：

```text
backend/scheduler/
├── __init__.py       # 唯一公开入口：start/get/shutdown
├── specs.py          # JobSpec、CronSpec、IntervalSpec
├── task_functions.py # 领域任务 callable 与单飞包装
├── registry.py       # Settings → tuple[JobSpec, ...]
└── runtime.py        # APScheduler 注册与生命周期
```

不采用以下方案：

1. **按领域拆多个注册模块**：单个文件更小，但 job ID、顺序和调度参数分散，难以形成
   可审查的完整注册契约。
2. **仅拆 runtime 与 registration**：改动较少，但业务 callable、Settings 解析和任务
   元数据仍混合，无法解除 runtime 对领域 service 的直接依赖。

## 4. 依赖方向与公开入口

依赖关系固定为：

```text
API startup / health
  → backend.scheduler
  → runtime
  → registry
  → specs
  → task_functions
  → domain services
```

`runtime.py` 不得导入 `backend.services` 或 `backend.graph`。`specs.py` 不得导入
APScheduler、Settings 或领域模块。领域依赖只允许出现在 `task_functions.py`。

`backend/scheduler/__init__.py` 只公开：

```python
start_scheduler
get_scheduler
shutdown_scheduler
```

`JobSpec` 和内部构造函数不是包级公开 API。生产代码和测试不得继续导入
`backend.scheduler.scheduler` 或 `backend.scheduler.jobs`。

## 5. Scheduler Spec

`specs.py` 使用不可变 dataclass 表达任务定义。cron 与 interval 的触发参数使用不同
类型，避免依靠宽泛的字符串 trigger 和无约束字典表达所有情况。

```python
@dataclass(frozen=True, slots=True)
class CronSpec:
    hour: int
    minute: int
    timezone: str


@dataclass(frozen=True, slots=True)
class IntervalSpec:
    timezone: str
    minutes: int | None = None
    seconds: int | None = None
    jitter: int = 0
    start_delay_seconds: int = 0


@dataclass(frozen=True, slots=True)
class JobSpec:
    id: str
    callable: Callable[[], object]
    trigger: CronSpec | IntervalSpec
    max_instances: int = 1
    coalesce: bool = True
    misfire_grace_time: int | None = None
```

`IntervalSpec` 必须恰好设置 `minutes` 或 `seconds` 之一。registry 只在配置 interval
大于零时创建 interval job，因此 spec 不承担“零表示关闭”的隐式语义。

jitter 与 start delay 属于 interval trigger 自身，继续传给 `IntervalTrigger`；不得错误
传为 `add_job(..., jitter=...)`。`misfire_grace_time` 属于 job 注册参数。

## 6. Task Functions

`task_functions.py` 提供稳定的零参数 callable，registry 只引用这些具名函数，不使用匿名
lambda。主要函数包括：

- `run_daily_refresh()`；
- `run_daily_briefing()`；
- `run_morning_market_intel()`；
- `run_post_market_intel()`；
- `run_pre_market_evidence()`；
- `run_post_market_evidence()`；
- `run_post_market_evidence_hourly()`；
- `run_cls_telegraph_sync()`；
- `run_knowledge_ingest_index()`。

行为保持如下：

- daily refresh 继续使用 `trigger="scheduled"`；
- daily briefing 在执行时构造模型；缺少模型配置导致 `RuntimeError` 时记录 warning 并
  跳过本轮，其他业务异常继续向 APScheduler 传播；
- morning/post-market intel 继续传入 `None` Session 和原有 brief type；
- evidence 任务继续调用现有 async service，并保留 `scheduled` 与
  `scheduled_hourly` trigger；
- CLS 同步继续通过 `process_singleflight("scheduler.cls_telegraph_sync")` fast-fail；
- knowledge pipeline 继续在短进程锁内创建 `trigger="scheduled"` 的 job 记录，再把
  job ID 交给后台 runner；创建失败仍记录并返回，后台启动失败仍调用 `mark_failed`。

本阶段不把领域依赖改成新的 DI container。具名函数本身就是可测试、可 monkeypatch 的
组合边界。

## 7. Registry 与任务契约

`registry.build_job_specs(...)` 接收 Settings，并保留 `start_scheduler` 现有的测试覆盖
能力：timezone、daily refresh hour 和 minute 可以由调用方提供覆盖值。

完整启用时任务顺序固定为：

1. `daily_refresh`；
2. `daily_briefing`；
3. `morning_market_intel`；
4. `post_market_market_intel`；
5. `pre_market_evidence`；
6. `post_market_evidence`；
7. `post_market_evidence_hourly`；
8. `cls_telegraph_sync`；
9. `knowledge_ingest_index`。

现有条件注册保持不变：

- `daily_briefing` 由 `scheduler_briefing_enabled` 控制；
- 两个 evidence cron 由 `scheduler_evidence_enabled` 共同控制；
- hourly evidence 由 `scheduler_evidence_hourly_enabled` 控制，且 minutes 必须大于零；
- CLS 由 `cls_telegraph_sync_enabled` 控制，且 seconds 必须大于零；
- knowledge pipeline 由 `scheduler_knowledge_enabled` 控制，且 minutes 必须大于零。

各 job 的固定触发值、grace time 和 jitter 以迁移前的注册快照为权威。迁移不得借机把
`getattr(settings, ..., default)` 改成新的配置策略。

## 8. Runtime 生命周期

`runtime.start_scheduler(*, enabled=None, hour=None, minute=None, timezone=None)` 保留现有
签名和返回语义：

- 已存在 scheduler 时直接返回同一实例，不重复读取配置或注册任务；
- disabled 时返回 `None`，且不构造 BackgroundScheduler；
- 未提供覆盖参数时从 `get_settings()` 读取；
- 创建 `BackgroundScheduler(timezone="Asia/Shanghai")` 的现有默认行为保持不变；
- 逐个把 JobSpec 转换为 `CronTrigger` 或 `IntervalTrigger` 并调用 `add_job`；
- 全部注册完成后启动 scheduler，再写入进程内 `_scheduler`；
- `shutdown_scheduler()` 继续使用 `shutdown(wait=False)`，随后清空状态；
- `get_scheduler()` 继续读取实时状态，避免包级 re-export 缓存旧值。

runtime 的 trigger 转换函数属于私有实现。interval start date 继续按当前时间加
`max(0, start_delay_seconds)` 计算，seconds/minutes 与 jitter 继续做现有的最小值保护。

## 9. 错误与并发语义

- APScheduler `max_instances=1` 与 `coalesce=True` 继续防止同一 scheduler 实例内任务
  叠加；
- 写入型任务保留现有领域级单飞或任务表抢占，不重新引入数据库全局锁；
- `SingleflightBusy` 继续只记录 warning 并跳过本轮；
- 除 briefing 模型不可用、knowledge 创建/启动失败和 singleflight busy 这些已有显式
  分支外，业务异常继续向 APScheduler 传播；
- runtime 注册或启动失败继续向应用启动调用方传播，不吞掉异常，也不留下已赋值的
  `_scheduler`；
- 当前部署约束仍为单 backend worker。多 worker 调度选主与 advisory lock 另立规格。

## 10. 测试策略

### 10.1 RED 注册契约

先建立会因新模块尚不存在或旧模块尚存在而失败的契约：

- `scheduler.py` 与 `jobs.py` 不存在；
- Python 源码无旧模块导入；
- `runtime.py` 不导入 service 或 graph；
- scheduler 包只公开三个生命周期函数；
- 完整启用时九个 job 的 ID、顺序、callable、trigger 参数和 job 参数与当前行为一致。

### 10.2 Spec 与 Registry 单元测试

- CronSpec/IntervalSpec/JobSpec 不可变；
- IntervalSpec 拒绝同时缺少或同时提供 seconds/minutes；
- 每个启用开关只移除对应任务；
- 非正 interval 不注册相应任务；
- daily refresh 覆盖参数只影响该任务；
- timezone 按现有行为应用到所有 trigger；
- hourly evidence、CLS 和 knowledge 的 jitter/start delay 保持不变。

### 10.3 Task Function 测试

- 每个薄 callable 调用正确领域 service 和固定参数；
- briefing 模型配置缺失时跳过，成功时注入 model；
- CLS 空闲时执行、单飞忙时跳过；
- knowledge scheduled job 的创建、后台启动和启动失败标记保持不变。

### 10.4 Runtime 测试

使用 fake scheduler 验证：

- disabled 不构造、不注册；
- start 幂等；
- CronSpec 与 IntervalSpec 转换正确；
- callable 身份不被 lambda 包装改变；
- 注册发生在 start 前；
- shutdown 使用 `wait=False` 并清空状态；
- health API 读取实时 scheduler 状态。

### 10.5 全量验证

- 运行 Scheduler、API app、Briefing jobs、knowledge background job 定向测试；
- 运行 AST/路径硬切换契约；
- 运行 `compileall`、`git diff --check` 和旧路径全文门禁；
- 使用 PostgreSQL worker schema fixture 运行完整 backend 测试。

## 11. 提交边界与回滚

交付分为三个提交：

1. Scheduler 设计规格；
2. Scheduler 实施计划；
3. 一个原子实现提交，包含测试、新模块、消费者切换和旧模块删除。

实现阶段的 RED/GREEN 检查点不单独提交。只有定向测试、硬切换契约、完整 PostgreSQL
回归和最终 review 全部通过后才创建实现提交。

若任务快照或领域行为无法保持，则不提交部分迁移。回滚整个实现提交即可恢复旧结构；
本次没有数据库 migration、数据迁移或外部配置变更。

## 12. 完成标准

- Scheduler 唯一实现位于 `specs.py`、`task_functions.py`、`registry.py` 和 `runtime.py`；
- `scheduler.py`、`jobs.py` 已删除，仓库内无旧导入和兼容层；
- package 只公开 start/get/shutdown；
- runtime 不依赖任何领域 service 或 graph；
- 九个 job 的 ID、顺序、启用条件、触发参数和 callable 行为保持不变；
- 单飞、错误传播、health、启动和关闭语义保持不变；
- 定向测试、结构契约、静态门禁和 PostgreSQL backend 全量测试全部通过；
- 工作区不存在重复实现、临时兼容文件或未跟踪迁移产物。
