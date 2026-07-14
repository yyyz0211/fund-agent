# Task 5 Review

## Spec Compliance
✅ 满足:
- **5.1** `search_knowledge` 拆 fetch / write:write 阶段在 `owns_session` 路径下使用独立 `with session_scope() as tx:` 短事务(`knowledge_search_service.py:241-250`),空命中走 `_log_retrieval` 同样 short-tx(284-287 行)。
- **5.1** `_run_knowledge_pipeline_once_inner` 在 owning 路径下拆为 ingest / index / profiles / matches 四个独立 `session_scope()`(515-549 行);caller 注 session 时保留单事务流但只 flush(550-556 行)。
- **5.2** `sync_cls_telegraph_once` 拆分页提交:`_sync_pages_with_own_session` 用 `for _page in range(max_pages)` 循环,每页 fetch 在事务外(202-211 行),`_persist_page` 走独立 `session_scope()` short-tx(378-392 行),`_record_success` / `_record_failure` 各为独立 short-tx(396-422 行)。
- **5.3** `ingest_recent_knowledge` 拆 fetch + LLM + write:`_fetch_recent_candidates` 独立 short-tx 拉候选(309-318 行),LLM classify 在两段事务之间执行(无 DB session 持有),write 阶段 owning 走 `session_scope()`(349-350 行)。
- **5.4** `knowledge_match_service.refresh_knowledge_fund_matches` / `knowledge_fund_profile_service.refresh_fund_watchlist_profiles` 改为 caller-session 透传 / owning 走 `session_scope()` 二选一(各自 96-103 / 93-96 行);函数体内只 flush,无 commit/rollback/close。
- **5.5** `knowledge_reindex_jobs.py` 未动(`git diff 3d36778..f25373e -- backend/services/knowledge/knowledge_reindex_jobs.py` 无输出),仍在 `ALLOWED_INTERNAL_COMMIT_SERVICES` 白名单内。
- 改动范围严格限定 5 个 knowledge service 文件,无附带副作用。

❌ 不满足:
- (轻微) **5.1 字面解读**:`search_knowledge` 阶段 1(embedding + vector search + structured SQL fetch)仍位于 `with ctx as s:` 长持有 session 内(177 行),并非真正"无事务"。但 embedding 不触发 SQL,长 session 仅承载只读查询,实际不会持有写锁;write 阶段正确分流到独立 `session_scope()`。**判定:可接受**——spirit 满足(长操作不持写锁 + 写短事务化),仅字面与 plan 模板有偏差。

## Code Quality
- **search_knowledge 拆 fetch+write**:fetch / write 拆分清晰,空命中也走 `_log_retrieval` 独立 short-tx;caller 注入 session 时 `_write_retrieval_log` 仅 `session.flush()`。`_write_retrieval_log` 内 `session.flush()`(152 行)保证写出 PK 不冲突。
- **cls_telegraph 拆分页提交**:`_sync_pages_with_own_session` 与 `_sync_pages_with_external_session` 双路径对称;失败时 `_record_failure` 回退到 `previous_state` 也走 short-tx(406-422 行),状态写失败有 try/except 兜底(417-421 行),不会二次抛错。`_load_last_time_for_page` 独立 short-tx 读 last_time(354-362 行)。
- **knowledge_ingestion 拆 fetch+write**:`_fetch_recent_candidates` 独立 short-tx,LLM classify 在两段事务之间;`ingest_candidates` 仍要求 caller 传 session(208-213 行),与 plan 一致。
- **match / fund_profile 简化**:两个 service 改造形态一致——caller-session 透传到 `_compute_*` / `_recompute_*`,owning 走 `session_scope()`;内部只 `session.flush()`(135 / 142 行),无 commit/rollback/close。
- **knowledge_reindex_jobs 未动**:git diff 0 输出,白名单仍生效,契约测试对此文件 `pytest.skip`。

## Test Run
- **5 契约测试**: PASS(`5 passed in 0.03s`)
  - knowledge_search_service / cls_telegraph_sync_service / knowledge_ingestion_service / knowledge_match_service / knowledge_fund_profile_service 全过。
- 业务测试:6 passed,9 pre-existing failed(sqlite vs postgresql baseline 一致,非本次回归)。

## Issues
### Critical
None。

### Important
None。

### Minor
1. `search_knowledge` 在 owning 路径仍持有长 session 跑 fetch + embedding,与 plan 字面"embedding 无事务"略有偏差。embedding 本身不触发 SQL,不影响写锁,但若想严格字面满足,可改为 `_fetch_search_results` 接收已构造的 provider/store,主函数不持 session。**建议:接受现状**(在 self-review 已说明),不阻塞。
2. `cls_telegraph_sync_service._sync_pages_with_external_session` 在 caller 注 session 失败时,使用 try/except 嵌套 + `session.flush()` 处理 state 更新(319-332 行),模式与 owning 路径不完全对称但语义合理——caller 拥有 commit/rollback,service 仅 flush + 记录 last_error。**可接受**。

## Verdict
✅ Approved
