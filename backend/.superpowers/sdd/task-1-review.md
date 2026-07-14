# Task 1 Review

## Spec Compliance
✅ 满足:
- Task 1.1 三个 watchlist 写函数(`add_to_watchlist` / `add_to_watchlist_full` / `remove_from_watchlist`)改为 `session.flush()`,无 commit。
- Task 1.2 四个 watchlist 写函数(`update_watchlist_note` / `update_watchlist` / `update_watchlist_preload` / `backfill_watchlist_fund_names`)改为 `session.flush()`,无 commit;`update_watchlist_preload` 的 `commit=True/False` keyword 已彻底删除,改为单一 `status` keyword。
- Task 1.3 三个 fund upsert 写函数(`upsert_fund` / `upsert_fund_profile` / `upsert_navs`)改为 `session.flush()`,无 commit。
- Task 1.4 七个 transaction/plan/pending 写函数(`add_transaction` / `delete_transaction` / `add_investment_plan` / `update_investment_plan` / `delete_investment_plan` / `add_pending_buy` / `update_pending_buy`)改为 `session.flush()`,无 commit;5 个 `commit=` keyword 全部删除。
- 顶部 docstring(第 1-5 行)明确写出"按 spec §4.2 重构后,所有写函数仅 `session.flush()`;事务边界(commit/rollback/close)由 caller 决定"。
- AST 契约测试 `test_repository_does_not_commit_session` 通过(1 passed in 0.02s)。

❌ 不满足:None

## Code Quality

- **17 处 commit 改造质量**:每处都是机械替换(commit → flush),无副作用代码保留。`remove_from_watchlist` 的级联删除顺序保持不变,`backfill_watchlist_fund_names` 的"只在有 rows 时才 flush"微优化保留;`update_pending_buy` / `update_investment_plan` 用白名单 `for key in (...)` 过滤未改,仍安全。
- **commit= keyword 删除**:5 个 keyword 全部清除,signature 已是 flat kwargs;`update_watchlist_preload` 改为 `(*, status)` 单一 keyword。grep `commit:|commit=True|commit=False` 在 `backend/db/repository.py` 返回 0 命中(只 docstring 第 4 行有"commit"作为名词出现,符合预期)。
- **docstring 更新**:原文是"写路径默认在内部自己 commit / 少数 service 传 commit=False"这种"双模式"说明,改为契约式单模式说明,清楚、无歧义。
- **`session.refresh()` 新增**:在 `add_transaction` / `add_investment_plan` / `add_pending_buy` / `update_pending_buy` 4 个函数中,统一在 `flush()` 后加了 `session.refresh(obj)`。这是行为变化,见 Concerns #3 评估。

## Concerns 评估

- **#1 (测试环境)**:同意。`test_knowledge_ingestion_service.py` / `test_knowledge_match_service.py` 两个文件名在仓库里就不存在(grep 0 命中);`make_engine` 拒绝 `sqlite://` URL 抛 `ValueError` 是 Phase 0 fixture 迁移遗留,不在 Task 1 范围。Task 2-6 跑回归套件时需要先确认本地/CI 有 PostgreSQL,否则 setup error 会掩盖真实失败。建议在 Task 9.1 的全量验证前先用一个 `scripts/check_test_db.sh` 之类的小脚本确认 `TEST_DATABASE_URL` 可用。

- **#2 (commit=False caller 升级)**:清晰。grep 出 `backend/services/watchlist/watchlist_service.py` 仍有 5 处 `commit=False` keyword caller(`add_transaction` ×1, `_recalc` ×2, `update_pending_buy` ×1 — 加上原本 Task 1 报告里说的)。删除 keyword 后这些调用方会立即 `TypeError: unexpected keyword argument 'commit'`,必须由 Task 2.1 第一个 PR 在 service 层显式接管 commit 后才能恢复。报告里"Task 2-6 第一个 PR 必须包含 watchlist_service / transaction_service 的 commit 接管"这一警告是准确的、可执行的。

- **#3 (统一 refresh)**:本任务范围内**合理**。具体分析:
  - 原 `commit=True` 路径不 refresh,caller 在 `s.commit()` 后读到的是 stale ORM 对象:`id` / `created_at` 等 `server_default` 列在 commit 后才会被 expire,下次 lazy load 会触发额外 SELECT(且 `created_at` 这种 server-side 默认值在 commit 后才真正可见);原 `commit=False` 路径 refresh 后才让 caller 拿到完整 PK / 时间戳快照。
  - 新实现每次都 `flush()` + `refresh()`:代价是每个 insert/update 多一次 SELECT(round-trip 增加);收益是 caller 总是拿到一个"立刻可序列化"的稳定快照。
  - **潜在风险**:之前有 caller 依赖 `commit=True` 路径的"延迟可见"特性 — 但看 `watchlist_service.add_transaction` 的实现,`tx` 直接被序列化成 dict 返回(用 `_tx_to_dict(tx)`),后续没有 lazy-load 操作。新实现与 caller 实际用法兼容,**不构成回归风险**。
  - **结论**:这是 spec §4.2 的合理副产品 — caller 拿到稳定快照比"等到第一次 lazy load 才看见 id"更安全;额外一次 SELECT 的成本可接受。无需在 Task 1 内进一步处理。

- **#4 (update_watchlist_preload)**:仅 1 个 caller(`backend/services/watchlist/watchlist_preload_jobs.py:_set_watchlist_preload`),且该 caller 调用时**不**传 `commit=` keyword,新 signature `(*, status)` 兼容。`backend/db/repositories/watchlist.py` 第 32 行的导出白名单是字符串列表(仅用于测试),与 signature 无关。**安全,无 caller 依赖问题**。

## Issues

### Critical
None

### Important
None

### Minor
- `update_watchlist_preload` 的 docstring 仍是"后台预热任务专用更新入口。"一句,未提"事务边界由 caller 决定"或 "flush only";建议下次有人改这个函数时把契约 docstring 补齐(跟 `add_to_watchlist` 那种"事务边界由 caller 决定"对齐)。**非阻塞**。
- `update_pending_buy` 的 patch 字段过滤写成 `for key in ("status", "nav_date", "nav", "share", "transaction_id"): if key in patch: setattr(...)`,字段集合是函数内硬编码 inline,不像 `update_investment_plan` 那样提到模块顶层 `_INVESTMENT_PLAN_PATCH_FIELDS` 常量。这是 pre-existing 风格不一致,本任务不应顺手改(超出"只改 commit/close"原则),留作后续重构。

## Verdict
✅ Approved

Task 1.1-1.4 严格按 spec §4.2 实施,17 处 `session.commit()` → `session.flush()` 改造完整、无残留,5 个 `commit=` keyword 全部清除,顶部 docstring 与契约一致,AST 契约测试通过。Service 层 regression 失败属 plan 预期的"service 仍依赖 repository commit"过渡期现象,Task 2-6 接管 commit 后会恢复。报告里 4 个 concerns 都是诚实标记,无隐藏风险。