# Task 3 Review

## Spec Compliance

✅ 满足:
- `refresh_fund` 拆 fetch + write:`_collect_refresh_data`(ThreadPoolExecutor 并行跑 `fetch_fund_nav_history` + `fetch_fund_info`)在事务**外**完成(line 44-46),然后才 `with session_scope() as s:`(line 49),事务内仅 `repo.upsert_navs` / `repo.upsert_fund`,无任何网络调用。
- `refresh_profile` 拆 fetch + write:`dc.fetch_fund_profile(fund_code)`(line 20)先跑,再 `with session_scope() as s:`(line 23),事务内仅 `repo.upsert_fund_profile`,无网络调用。
- 只读函数统一模式:`get_latest_nav` / `get_nav_by_date` / `get_metrics` / `get_basic_info` / `get_nav_history` / `get_profile` / `is_profile_fresh` / `lookup_fund_auto` / `diagnose_fund_auto` / `get_summary` 全部采用 `if session is None: with session_scope() as s: return _impl(..., session=s)` 模式。
- `refresh_fund` / `refresh_profile` 不再接受外部 session(签名变为 `(fund_code) -> dict`),事务完全 self-own。
- 删除 `_with_session` / `owns` 模式:两个 service 中已 0 处(`grep -n "_with_session\|owns"` 0 命中)。
- `s.commit()` / `s.close()` / `s.rollback()`:两个 service 函数体内 0 处(`grep` 退出码 1,无输出)。

❌ 不满足: 无

## Code Quality

- **refresh_fund 拆 fetch+write**:正确。bonus 把 NAV / info fetch 改成 ThreadPoolExecutor 并行(line 76-87),更彻底地缩短端到端时间。
- **refresh_profile 拆 fetch+write**:正确,顺序 fetch + 短事务 write,模式与 plan 一致。
- **其它只读函数**:统一模式;所有内部互调也走 `session=session` 透传,保证单事务读取一致性(`_local_lookup_payload` 内 4 个 `_summary_value` 都复用同一 session)。
- **fetch 隔离性**:`refresh_fund` 中若 `_collect_refresh_data` 抛错根本不会进事务;`refresh_profile` 中 `fetch_fund_profile` 的网络异常也不会被 `with session_scope` 捕获后变 rollback 噪音(spec 4.2 期望)。
- **返回结构兼容**:`refresh_fund` 新增 `fund_info_warn` / `already_up_to_date`,保留原 `navs_inserted` / `source` / `as_of`(旧调用者不依赖此字段,扩展不破坏);`refresh_profile` 仍返回 `{fund_code, profile, missing_data, errors, source, as_of}`,profile 改为 ORM 对象(原 plan 写 `fields_updated`,实际返回 ORM,需确认下游消费方能否 JSON 序列化)。

## Test Run

- 契约测试 fund_service:**PASS** (`2 passed in 0.02s`,精准节点 `backend/services/fund/fund_service.py`)
- 契约测试 fund_profile_service:**PASS** (同上)
- fund_service / fund_profile_service 业务单测:**1 passed, 17 errors**(全部为 SQLite fixture 的 PostgreSQL-only 基线限制,未进入测试体 — 与 Task 3 改动无关)

## Issues

### Critical
无。

### Important
- **测试代码未跟随签名变更**:`backend/tests/test_fund_service.py:36/67/117/138` 和 `backend/tests/test_fund_profile_service.py:40/71` 仍以 `session=session` 调用 `refresh_fund` / `refresh_profile`,而新签名已不接受此 kwarg。当前因 SQLite fixture 基线限制未触发,但基线修复后所有这些测试会立即 `TypeError`。建议下次任务顺手更新。

### Minor
- `refresh_profile` 返回值的 `profile` 字段从 `{fields_updated: [...]}`(plan 草稿)改为 ORM `FundProfile` 对象(report:line 44,实际实现 line 43)。如果 API 层直接 `json.dumps`,需要序列化器介入;若 API 层只用 dict 字段(`scale` 等),无影响。建议确认 `backend/api/routes/funds.py` 的实际消费方式。
- `refresh_fund` 的 `fund_info_warn` / `already_up_to_date` 是新字段,前端消费方需要适配(不在本任务范围,但需后续通知)。

## Verdict

✅ Approved

理由:
1. fetch 严格在事务外(`_collect_refresh_data` 整段、`refresh_profile` 中 `dc.fetch_fund_profile` 调用),`with session_scope()` 内只有 repo upsert,长事务拆解彻底。
2. 函数体零 `s.commit()` / `s.close()` / `s.rollback()`,AST 契约测试 2/2 通过。
3. `_with_session` / `owns` 模式在两个文件中 0 处残留。
4. 只读函数统一采用 `if session is None / else` 模式,与 plan §0 Global Constraints 一致。
5. 重要级测试问题(已存在的 `session=session` 调用)是基线 SQLite 限制下的已知债,不是本次引入的回归。
