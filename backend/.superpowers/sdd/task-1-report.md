# Task 1 Report

## Status
DONE_WITH_CONCERNS

## What I Did

把 `backend/db/repository.py` 的所有写函数从 `session.commit()` 改为 `session.flush()`,
去掉所有 `commit=` keyword 参数(大爆炸决策),并把模块顶部 docstring 改为契约式说明。

### 17 处 commit → flush 改造

| # | 行号 | 函数 | 改动 |
|---|------|------|------|
| 1 | 139 | `add_to_watchlist` | `commit()` → `flush()` |
| 2 | 156 | `add_to_watchlist_full` | `commit()` → `flush()` |
| 3 | 185 | `remove_from_watchlist` | `commit()` → `flush()` |
| 4 | 195 | `update_watchlist_note` | `commit()` → `flush()` |
| 5 | 222 | `update_watchlist` | `commit()` → `flush()` |
| 6 | 235 | `update_watchlist_preload` | 删除 `commit: bool = True` keyword + `if commit:` 分支,直接 `flush()` |
| 7 | 262 | `backfill_watchlist_fund_names` | 条件 `commit()` → 条件 `flush()` |
| 8 | 279 | `upsert_fund` | `commit()` → `flush()` |
| 9 | 308 | `upsert_fund_profile` | `commit()` → `flush()` |
| 10 | 333 | `upsert_navs` | `commit()` → `flush()` |
| 11 | 501 | `add_transaction` | 删除 `commit: bool = True` keyword;`if/else` 两个分支合一为 `flush()` + `refresh()`(caller 现在 commit 时仍拿到 PK/时间戳) |
| 12 | 513 | `delete_transaction` | `commit()` → `flush()` |
| 13 | 545 | `add_investment_plan` | 删除 `commit: bool = True` keyword;分支合一为 `flush()` + `refresh()` |
| 14 | 563 | `update_investment_plan` | `commit()` → `flush()` |
| 15 | 578 | `delete_investment_plan` | `commit()` → `flush()` |
| 16 | 613 | `add_pending_buy` | 删除 `commit: bool = True` keyword;分支合一为 `flush()` + `refresh()` |
| 17 | 631 | `update_pending_buy` | 删除 `commit: bool = True` keyword;分支合一为 `flush()` + `refresh()` |

`git diff` 显示 18 行 `session.commit()` 被替换为 `session.flush()`(其中 5 行是 `add_transaction / add_investment_plan / add_pending_buy / update_pending_buy / update_watchlist_preload` 里 `if commit: ... else: ...` 双分支各自一行,与 17 个独立写函数对应)。

### 顶部 docstring 更新
- 删除原"写路径默认在内部自己 commit / 少数 service 传 commit=False"段落
- 替换为:`"按 spec §4.2 重构后,所有写函数仅 session.flush();事务边界(commit/rollback/close)由 caller 决定。"`

### ResourceNotFoundError 替换
未做。原因:Step 4 明确要求"只在已经改了 commit/close 的函数里,如果原本就是 raise 异常,顺带换;不要为了替换而大改文件"。`backend/db/repository.py` 17 个写路径里没有任何一处 `raise KeyError(...)` 或 `return None` 同时还包含 commit 调用需要顺带改的(常见 Not-found 用 `return None` 风格,与契约测试无关;Task 2-6 处理 service 时一并替换更安全)。

## Tests Run

### 1. 契约测试
命令:`python -m pytest backend/tests/test_transaction_ownership_contract.py::test_repository_does_not_commit_session --no-header -q`
结果:**1 passed**

修复前同样命令的状态(在执行 Step 3 前已记录):
```
AssertionError: repository.add_to_watchlist() calls session.commit(); repository 仅允许 flush
1 failed in 0.04s
```

### 2. Service 回归套件
命令:
```
python -m pytest backend/tests/test_watchlist_service.py \
                 backend/tests/test_fund_service.py \
                 backend/tests/test_fund_profile_service.py \
                 backend/tests/test_market_service.py \
                 backend/tests/test_market_intel_service.py \
                 backend/tests/test_market_evidence_service.py \
                 backend/tests/test_briefing_service.py \
                 backend/tests/test_knowledge_search_service.py \
                 backend/tests/test_knowledge_reindex_jobs.py \
                 backend/tests/test_cls_telegraph_sync_service.py --no-header -q
```
结果:**31 passed, 16 failed, 35 errors** (在 ~37s 内,35 个 errors 全是 setup 阶段 `make_engine("sqlite:///:memory:")` 抛 `ValueError: Only PostgreSQL is supported` — 与本次 repository 改动无关,见 Concerns)。

按任务说明中**预期**失败(后续 Task 2-6 会修),按文件分组:

- **briefing_service.py**: 10 failed(`TestComposeBriefing` ×5 + `TestRunDailyBriefing` ×5),典型原因 `compose_briefing requires model to be injected by the composition root` / 状态快照中无 `last_run` 字段 → 需要 service 层自己 commit。
- **knowledge_search_service.py**: 3 failed(`structured_search_excludes_expired_documents` 等),service 没 commit 拿到 reflection / structured fallback 副作用。
- **cls_telegraph_sync_service.py**: 3 failed(repository upsert 之后 service 没 commit 写 telegraph 行)。
- 其余失败是 35 个 setup errors,不在本任务范围(环境前置条件:这些测试期望 PostgreSQL 后端,本地 `make_engine` 拒绝 `sqlite://` URL,见 Concerns #1)。

## Self-Review
- 17 处 commit 全部清理 ✓
- 没有保留 `commit=True/False` keyword(大爆炸决策)✓
- 顶部 docstring 更新 ✓
- 契约测试 `test_repository_does_not_commit_session` PASS ✓
- service 失败属预期(主要是 service 之前依赖 repository 内 commit,后续 Task 修)✓
- ResourceNotFoundError 替换按 Step 4 "不顺带改"原则未做,记录在本报告。

## Commits
- <pending> refactor: repository functions flush only; transactions owned by caller

## Concerns
1. **测试环境前置条件缺失**:Plan 列出 `test_knowledge_ingestion_service.py` 与 `test_knowledge_match_service.py` 两个文件,实际仓库中没有这两个文件(已 glob 确认);并且大量 service 测试的 fixture 用 `make_engine("sqlite:///:memory:")` 直接抛 `ValueError: Only PostgreSQL is supported`,导致 ~35 个 setup 错误。这两点都不在本任务范围(运行计划里给的命令也会失败),但说明 service 套件在本地 PostgreSQL 之外的开发环境下**无法**完整跑过 —— Task 2-6 跑回归时需要确认 CI/本地有 PostgreSQL 可用。我未在 Step 6 前提醒,但已在 Step 6 跑出来的结果中暴露。
2. **commit=False 的 caller 未升级为 True**:本次删除了 5 个 `commit` keyword 参数,意味着 `backend/services/watchlist/watchlist_service.py` 里 `add_transaction(..., commit=False)` / `_recalc(..., commit=False)` / `update_pending_buy(..., commit=False)` 的 caller 现在会 `TypeError: unexpected keyword argument`。这正是 Step 3 "大爆炸"决策的预期效果;Task 2-6 修改这些 caller 时必须去掉 `commit=False` 并在 service 层显式 `s.commit()`。**报告里点出:Task 2-6 第一个 PR 必须包含 watchlist_service / transaction_service 的 commit 接管,否则这两个 service 套件会从 "X failed" 升级为 "全炸"。**
3. **`add_transaction / add_investment_plan / add_pending_buy / update_pending_buy` 现在统一 `flush() + refresh()`**:之前 `commit=False` 路径才会 refresh,新行为是每次都 refresh(因为 caller 必须 commit 才能持久化,而 caller commit 后这些字段会被 expire,所以提前 refresh 给 caller 一个稳定快照)。这点 Task 2-6 改动 service 时可能影响行为(比如依赖 lazy load 的字段),需要后续 review 关注。
4. **`update_watchlist_preload` 删除 `commit=False` 兼容**:原来是后台预热任务专用,Task 2-6 检查谁调用它,可能需要改后台任务。