# Task 2.1 Review

## Spec Compliance

✅ **满足**:
- 顶部 import 已加 `from backend.db.session_scope import session_scope` (L14)
- 17 个公开函数(不含 2 个白名单 `set_initial_holding` / `confirm_pending_buy`)统一采用 `if session is None: with session_scope() as s: return _xxx_impl(s, ...) else: return _xxx_impl(session, ...)` 模式
- 17 个对应私有 `_xxx_impl` helper 均只调用 `repo.*` / `s.scalar` / `s.add` / `s.flush`,无 `s.commit()` / `s.close()` / `s.rollback()`
- 白名单 2 函数 `set_initial_holding` (L258) 和 `confirm_pending_buy` (L471) 内的 `s.commit()` 均保留
- `recalc_holding` 在 `transaction_service.py`,独立白名单覆盖,本任务不动
- `s.commit()` / `s.close()` / `s.rollback()` 在整个 watchlist_service.py 中只出现 3 次:2 次白名单 commit + 0 次 close/rollback
- 顶部 docstring 明确说明 session 管理约定
- `get_session` 旧 import 已被移除

❌ **不满足**:None

## Code Quality

- **通用模式**: 17 函数完全一致 —— 顶部 `if session is None:` 分支,`with session_scope() as s:` 块体委托给 `_xxx_impl(s, ...)`,`else` 分支直接 `return _xxx_impl(session, ...)`;无参数 / 多参数 / dict 参数函数都按统一形状实现,无遗漏
- **私有 helper 实现**: 17 个 `_xxx_impl` 全部只调用 repo 或内部 helper,无 commit/rollback/close;`_validate_transaction_nav` / `_with_pending_buy_stage` 也仅使用 repo 查询,无事务边界违规
- **删 commit= caller**: `grep -n "commit=" backend/services/watchlist/watchlist_service.py` 唯一命中为 L290 `_recalc` 内 `commit=commit` 转发给白名单 `transaction_service.recalc_holding`;**未发现任何 `repo.xxx(..., commit=...)` 调用**,符合规范

## Test Run

- **契约测试 watchlist**: `1 skipped, 56 deselected` —— 命中白名单正确 skip ✓
- **整体契约测试**: `17 failed, 37 passed, 3 skipped` —— watchlist_service 跳过,其余未改的 service(pnl / portfolio_history / cls_telegraph_sync / knowledge_* / market_* / shared/diagnosis / watchlist_preload_jobs)继续 FAIL,符合"未破坏非白名单"预期 ✓

## Issues

### Critical
None

### Important
None

### Minor
None

## Verdict

✅ **Approved**

Task 2.1 完整落实 Phase 1.2 Task 2.1 的 spec:17 函数统一收敛到 `session_scope` 模式,2 个白名单多步原子函数保持 `s.commit()`,私有 helper 仅 flush,无残留 `commit=` 调用透传给 repo。契约测试对 watchlist_service 正确 skip,其它 service 仍按预期 FAIL 等待后续 task 处理。
