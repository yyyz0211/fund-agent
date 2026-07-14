# Fund Agent 模块化重构 Review 修复设计

**日期**：2026-07-14

**状态**：已批准实施

## 目标

修复当前 Phase 2 模块移动引入的运行时和兼容性回归，不改变 API、业务算法、数据库 schema 或 PostgreSQL fixture 方案。

## 设计

1. Scheduler 只从具体模块导入 `scheduler_lock` 函数；包入口通过代理函数访问实现模块的动态状态，并继续暴露迁移窗口内测试和调用方依赖的旧符号。
2. `backend.services` 为所有被移动的旧模块名注册到新模块对象的兼容别名，使旧 import 和 `unittest.mock.patch` 修改的是实际实现模块；内部代码继续使用领域新路径。
3. `briefing.types` 恢复已定义的稳定输入、输出和模型 Protocol，同时 re-export 现有 briefing profile 类型。
4. `JobSpec.to_apscheduler_kwargs()` 合并触发器参数；callable 仍作为 `add_job()` 的第一个位置参数传入。
5. Integration Registry 从现有扁平 Settings 字段构造已支持的 CLS 配置；尚无 Settings 契约的适配器返回 `None`，而不是访问不存在的属性。

## 测试边界

- Scheduler 锁、包状态和兼容导出使用不连接数据库的单元测试。
- 旧 service import 使用模块身份等价测试，覆盖普通 import 和 mock patch 的语义。
- Briefing 类型、JobSpec 和 Integration Registry 使用纯单元测试。
- PostgreSQL fixture 完整迁移保持为规格书 Phase 0 的独立工作包，本修复不重新引入 SQLite 支持。

## 验收

- 新增回归测试先在当前实现上按预期失败，修复后通过。
- 原 review 中可运行的目标测试通过；需要旧 SQLite fixture 的遗留测试问题单独报告。
- `compileall`、`git diff --check` 和全量 pytest collection 通过。
