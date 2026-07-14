# Task 6 Report

## Status
DONE

## What I Did
- **`backend/services/briefing/briefing_service.py`**:
  - 顶部 docstring 增加 Phase 1.2 事务约定说明
  - `run_daily_briefing` 拆三段(原 L490-700 改造):
    - **阶段 1 (lines 539-576)**: evidence 采集
      - `session is None`: `market_evidence_service.collect_and_run_for_brief_type` + `search_evidence` 各走独立 `session_scope()` short-tx
      - caller 注 session: 复用同一 session 仅 flush
    - **阶段 2a (lines 578-585)**: `collect_watchlist_snapshot` (网络,无事务)
    - **阶段 2b (lines 605-650)**: `compose_briefing` LLM 调用(无事务,无 session)— **绝不在事务内**
    - **阶段 3 (lines 651-672)**: `upsert_briefing` 持久化
      - `session is None`: 走 `with session_scope() as s: upsert_briefing(s, ...)`
      - caller 注 session: 仅 `upsert_briefing(session, ...)`,caller 决定 commit
  - 删除 `_with_session` helper / `owns = ...` 模式 / `evidence_owns` 标志 / `s.commit()` / `s.close()` 残留 (`grep` 0 命中)
  - 替换 `from backend.db.session import get_session` → `from backend.db.session_scope import session_scope`
  - **`read_briefing` (lines 705-766)**: 改用 `with session_scope() as s:` 顶层事务模板,移除 `s = get_session() ... finally: s.close()`
  - `compose_briefing` 本身**未改动**(Phase 1.1 已接 model 参数,签名稳定)
  - `module_briefing` / `module_briefing.compose_briefing_v2` **未改动**
  - `start_run_async` 的 model 注入逻辑 **未改动**
  - API 路由 / scheduler **未改动**(不在本任务范围)

## Tests Run
1. `pytest backend/tests/test_briefing_service.py backend/tests/test_briefing_types.py backend/tests/test_briefing_prompts.py`: 10 failed, 18 passed — **0 regression** (与 baseline 完全一致: 10 failed 是 Phase 1.1 移除 `build_model` lazy import 后必须显式注入 model 的已知债;`test_compose_*` 5 个 + `test_run_*` 5 个)
2. `pytest backend/tests/test_transaction_ownership_contract.py::test_service_does_not_commit_or_close_session[backend/services/briefing/briefing_service.py]`: **PASS** (基线 FAIL,本次修好)
3. 完整 contract sweep `pytest backend/tests/test_transaction_ownership_contract.py`: 5 failed, 49 passed, 3 skipped — briefing 域内 10 个 file 全 PASS(`briefing_service` + 其它 9 个文件:`collectors` / `composer` / `jobs` / `module_briefing` / `modules` / `persistence` / `prompts` / `types` 等)。其它 5 failed 是其他子域尚未优化的基线残留(`pnl_service` / `portfolio_history` / `data_collector` / `diagnosis_service` / `watchlist_preload_jobs`),不在本任务范围。

## Self-Review
- ✅ **三段拆分正确**:`fetch` (阶段 1) / `compose` (阶段 2b) / `persist` (阶段 3) 各走独立事务边界,LLM 调用**绝不在事务内**
- ✅ **没有改 `compose_briefing` 本身**:仅调整 `run_daily_briefing` 内部对它的事务边界
- ✅ **没有改 `module_briefing`**:`brief_type` 解析 + `compose_briefing_v2` 路径完全保留
- ✅ **没有改 API 路由 / scheduler**:`briefing_api` 路由 + scheduler jobs 调用 `run_daily_briefing` 的语义不变(owning mode 下内部仍自动 commit)
- ✅ **caller 注 session 兼容**:测试 fixture 用 `in_memory_session` 时仍只 flush,符合契约
- ✅ **`_with_session` / `owns` 模式删除干净**:`grep -n "s\.commit\|s\.close\|s\.rollback\|owns " backend/services/briefing/briefing_service.py` 仅命中 docstring 字符串,函数体 0 处违规
- ✅ **AST 契约**:briefing_service.py 函数体全部 PASS `test_service_does_not_commit_or_close_session`

## Commits
- `<pending>` refactor: briefing_service.run_daily_briefing splits fetch/compose/persist

## Concerns
None。
- 10 个 baseline-failing briefing 测试(5 `compose_*` + 5 `run_*`)均来自 Phase 1.1 移除 lazy `build_model` 的既定债,不是本次回归。后续需要单独更新这些 fixture(注入 `model=...`)或迁到 postgresql test DB 才能消除。
- `start_run_async` 内部仍用 `_active_lock` + `_async_executor` 单飞,**与本次事务重构正交**,继续由 Phase 1.3-1.4 处理。
