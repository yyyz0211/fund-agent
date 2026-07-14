# Refactoring Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复领域模块移动造成的 Scheduler、旧 import、Briefing 类型、JobSpec 和 Integration Registry 回归。

**Architecture:** 保持领域目录为唯一实现位置，在包入口提供薄兼容代理；稳定领域类型保留在 `briefing.types`；新基础设施 API 只读取已存在的 Settings 契约。所有修复均以纯单元回归测试保护，不触碰数据库 schema。

**Tech Stack:** Python 3.11、pytest、APScheduler、Pydantic Settings、SQLAlchemy。

## Global Constraints

- PostgreSQL 是唯一运行时数据库，不新增 SQLite 兼容代码。
- API、Scheduler job ID/触发语义和旧模块 import 在迁移窗口内保持兼容。
- 不修改业务算法或数据库 schema。
- 不覆盖或撤销工作区中已有的用户修改。

---

### Task 1: Scheduler 锁和动态状态

**Files:**
- Modify: `backend/tests/test_scheduler.py`
- Modify: `backend/tests/test_api_app.py`
- Modify: `backend/scheduler/scheduler.py`
- Modify: `backend/scheduler/__init__.py`
- Modify: `backend/api/app.py`

**Interfaces:**
- Produces: `get_scheduler() -> BackgroundScheduler | None`、兼容的 `set_scheduler_for_testing()`，以及可调用的 `_safe_job()`。

- [ ] 添加 `_safe_job` 能调用真实锁函数、包入口能观察实现模块状态、health 使用动态状态的失败测试。
- [ ] 运行目标测试并确认分别因模块不可调用或状态停留在 `None` 而失败。
- [ ] 直接从 `shared.scheduler_lock` 导入函数，并让包入口代理实现模块状态和遗留私有 helper。
- [ ] 更新 health 通过 `get_scheduler()` 读取状态，运行目标测试确认通过。

### Task 2: 旧 Service 模块兼容入口

**Files:**
- Create: `backend/tests/test_service_import_compatibility.py`
- Modify: `backend/services/__init__.py`

**Interfaces:**
- Produces: `backend.services.<legacy_name>` 与对应 `backend.services.<domain>.<module>` 指向同一个模块对象。

- [ ] 添加旧 import、新 import 模块身份相同和旧 patch 路径可修改实际实现的失败测试。
- [ ] 运行测试，确认因旧模块不存在而失败。
- [ ] 在 services 包初始化时注册受控的旧路径到新模块别名映射。
- [ ] 运行兼容性测试及依赖旧 patch 路径的 market route 测试。

### Task 3: Briefing 稳定类型恢复

**Files:**
- Create: `backend/tests/test_briefing_types.py`
- Modify: `backend/services/briefing/types.py`

**Interfaces:**
- Produces: `ChatModel`、`StreamableChatModel`、`WatchlistSnapshot`、`MarketSnapshot`、`EvidenceRecord`、`BriefingInput`、`ModuleEnvelope`、`BriefingResult`，并保留 profile re-export。

- [ ] 添加公共类型可导入、dataclass 可构造和 Protocol 可用于依赖注入的失败测试。
- [ ] 运行测试，确认因符号缺失而失败。
- [ ] 恢复原稳定类型并扩展 `__all__`，保留 profile 类型导出。
- [ ] 运行 Briefing 类型及现有 Briefing service 测试。

### Task 4: JobSpec 参数转换

**Files:**
- Create: `backend/tests/test_scheduler_jobs.py`
- Modify: `backend/scheduler/jobs.py`

**Interfaces:**
- Produces: `JobSpec.to_apscheduler_kwargs() -> dict[str, object]`，包含 trigger kwargs，但不包含 callable。

- [ ] 添加 cron、interval 参数保留及可选参数省略测试。
- [ ] 运行测试，确认 hour/minute 或 seconds 丢失。
- [ ] 合并 `trigger_kwargs` 并将 dataclass 可选字段改为 `int | None`。
- [ ] 运行 JobSpec 测试确认通过。

### Task 5: Integration Registry 配置构造

**Files:**
- Create: `backend/tests/test_integration_registry.py`
- Modify: `backend/integrations/registry.py`

**Interfaces:**
- Produces: `get_adapter_config("ClsTelegraphAdapter") -> ClsConfig`；尚未配置的 adapter 和未知名称返回 `None`。

- [ ] 添加 CLS 字段映射和未支持 adapter 安全返回测试。
- [ ] 运行测试，确认当前实现访问不存在的 Settings 属性。
- [ ] 从现有 `cls_*` Settings 字段构造 `ClsConfig`，未支持配置不做猜测。
- [ ] 运行 Integration Registry 测试确认通过。

### Task 6: 扩大验证

**Files:**
- Verify all modified files.

- [ ] 运行新增纯单元测试和此前失败的目标测试。
- [ ] 运行 `python -m compileall -q backend` 和 `git diff --check`。
- [ ] 使用 PostgreSQL 测试环境变量完成全量 pytest collection。
- [ ] 检查最终 diff，确认未覆盖用户无关改动，并记录仍由 PostgreSQL fixture 迁移阻塞的测试。
