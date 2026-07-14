# Task 6 Review

## Spec Compliance
- ✅ 满足:`run_daily_briefing` 拆三段(阶段 1 evidence / 阶段 2 collect + LLM compose / 阶段 3 upsert)
- ✅ 满足:阶段 1 在 `session is None` 时用两个独立 `session_scope()` short-tx (ingest + search);caller 注 session 时只 flush
- ✅ 满足:阶段 2a `collect_watchlist_snapshot` 和阶段 2b `compose_briefing` 都不在任何事务内
- ✅ 满足:阶段 3 upsert 走 `with session_scope() as s:` 短事务;caller 注 session 时仅 flush
- ✅ 满足:`compose_briefing` 本身**未改动**(签名 `snapshot, evidence=None, *, model, profile` 稳定)
- ✅ 满足:`module_briefing` / `start_run_async` / API 路由 / scheduler 全部未动(改动仅 `briefing_service.py`)
- ✅ 满足:`read_briefing` 改用 `with session_scope() as s:` 顶层事务模板,移除 `s.close()` 残留
- ✅ 满足:`_with_session` helper / `owns` / `evidence_owns` / `s.commit() / s.close()` 函数体内全部删除干净
- ❌ 不满足:无

## Code Quality
- **run_daily_briefing 三段拆分**(lines 539-676):结构清晰,每段有显式注释 `阶段 1/2a/2b/3`;`session is None` 与 caller 注 session 两条分支都正确处理(注 session 时只 flush,不动 commit);LLM `compose_briefing` 调用点(line 614-620)位于 `阶段 2b`,**完全不在任何 `with session_scope()` 块内**,符合 spec §4.2。
- **阶段 1 拆为 1a (ingest) + 1b (search) 两个 short-tx**:1b 可读到 1a 写入的 evidence,因为 session_scope 出 `with` 即 commit。这是正确的设计选择。
- **compose_briefing / module_briefing 未动**:`git diff` 显示无任何签名或函数体改动,Phase 1.1 注入的 `model` 参数链路保留完整。
- **其它函数简化**:`read_briefing` (lines 705-766) 用 `with session_scope() as s:` 替代 `s = get_session() ... finally: s.close()`,减 3 行,语义等价且自动 commit/rollback。
- **导入替换**:`get_session` → `session_scope`(line 31),符合新事务所有权模式。
- **顶部 docstring 新增 Phase 1.2 事务约定说明**(lines 10-17),可读性加分。

## Test Run
- 契约测试 briefing_service: `1 passed in 0.02s` ✅
- `grep "s\.commit\|s\.close\|s\.rollback" backend/services/briefing/briefing_service.py`:仅命中 docstring 字符串(line 13),函数体 **0 行** ✅
- `git diff --stat backend/services/briefing/`:仅 `briefing_service.py` 单文件改动 (+77/-45),其它 0 ✅

## Issues
### Critical
无
### Important
无
### Minor
- `compose_result` 失败降级路径(line 624-631)与"自选池为空"降级路径(line 633-640)会覆盖原 `warnings` 字段,但这是 Phase 1.1 已有的行为,不属于本任务范围。
- 阶段 1b 在 `session is None` 分支内 `evidence_rows: list[dict] = []` 在 if/else 两侧重复声明,可在 if 之前统一初始化以减少冗余(纯风格)。

## Verdict
✅ Approved