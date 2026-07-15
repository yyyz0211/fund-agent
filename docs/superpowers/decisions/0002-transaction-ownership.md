# ADR-002: 统一事务所有权

**Status**: 已实施
**日期**: 2026-07-14
**对应规格**: docs/superpowers/specs/2026-07-14-fund-agent-refactoring-design.md §4.2
**对应计划**: docs/superpowers/plans/2026-07-14-phase-1-2-transaction-ownership.md

## 背景

原后端的事务所有权分散在 14 个 service / repository / api 层共 31 处 `commit` 和 39 处 `close`,违反规格书 §4.2 "顶层入口拥有事务"原则。9 个 service 在事务内跑网络 / LLM 调用,持有数据库写锁 30s+。

## 决策

### Repository
- 写函数仅 `session.flush()`,不再内嵌 commit
- 事务边界(commit / rollback / close)由 caller 决定
- 移除 `commit=` keyword 参数(大爆炸重构,无中间兼容层)

### Service
- 函数体内**禁止**调用 `s.commit() / s.rollback() / s.close()`
- 仅允许 `s.flush()`
- 长事务 service 必须把网络 / LLM / embedding 调用挪出事务,先 fetch 再 write
- 标准模式:
  ```python
  if session is None:
      with session_scope() as s:
          return _impl(s, ...)
      # 自动 commit;异常时自动 rollback + raise
  return _impl(session, ...)
  ```

### API 路由
- 写路由通过 `Depends(get_db_session)` 获取 session
- 路由层不 commit(交给 service / Depends)
- 修复手工 `get_session()` + `close()` 的 2 个反模式

### Scheduler / CLI
- 顶层入口用 `with session_scope() as s:` 显式声明事务
- Scheduler job 函数不直接管理 session(通过 service 间接管理)

### Service 事务边界

- 不保留整文件或函数级 commit 白名单。
- `set_initial_holding`、`confirm_pending_buy` 等多表操作仍保持原子性，但提交由最外层
  `session_scope()` 或调用方事务负责。
- `knowledge_reindex_jobs` 的状态更新使用 `session_scope()` 短事务，不在 service 内直接
  commit/rollback/close。

## 不变量测试

`backend/tests/test_transaction_ownership_contract.py` 用 AST 静态扫描防止回归:
- `test_service_does_not_commit_or_close_session[每个 service]` —— 扫描 service 函数体
- `test_repository_does_not_commit_session` —— 扫描 `db/repository.py`

契约测试扫描所有 service 文件，不再跳过 watchlist、transaction 或 reindex job 文件。

## 改动范围

| 范围 | 改动 |
|---|---|
| `backend/db/repository.py` | 17 处 `session.commit()` → `session.flush()`;5 个 `commit=` keyword 删除;docstring 更新 |
| `backend/services/watchlist/watchlist_service.py` | 写函数使用 session_scope 模式;多表操作由最外层事务提交 |
| `backend/services/fund/fund_service.py` | `refresh_fund` 拆 fetch + write 并行;9 个只读函数简化 |
| `backend/services/fund/fund_profile_service.py` | `refresh_profile` 拆 fetch + write;`get_profile` 简化 |
| `backend/services/fund/pnl_service.py` | `calculate_pnl` 简化(无 close / commit) |
| `backend/services/fund/portfolio_history.py` | `calculate_pnl_series` 简化 |
| `backend/services/market/market_service.py` | `refresh_market` 用 session_scope |
| `backend/services/market/market_intel_service.py` | `collect_market_intel` 拆 fetch + write |
| `backend/services/market/market_evidence_ingestion.py` | `ingest_market_evidence` 拆 fetch + write |
| `backend/services/market/market_evidence_service.py` | 简化 + 委托 |
| `backend/services/market/data_collector.py` | `fetch_announcements` 用 session_scope |
| `backend/services/knowledge/knowledge_search_service.py` | 拆 fetch + write;`_run_knowledge_pipeline_once_inner` 拆为多段 |
| `backend/services/knowledge/cls_telegraph_sync_service.py` | 分页提交;每页独立 short-tx |
| `backend/services/knowledge/knowledge_ingestion_service.py` | `ingest_recent_knowledge` 拆 fetch + write |
| `backend/services/knowledge/knowledge_match_service.py` | 简化 |
| `backend/services/knowledge/knowledge_fund_profile_service.py` | 简化 |
| `backend/services/briefing/briefing_service.py` | `run_daily_briefing` 拆 fetch + compose + persist |
| `backend/services/shared/diagnosis_service.py` | `get_peers` / `diagnose_fund` 简化 |
| `backend/services/watchlist/watchlist_preload_jobs.py` | `_set_watchlist_preload` 用 session_scope |
| `backend/api/routes/knowledge.py` | 移除 2 处路由层 commit |
| `backend/api/routes/briefing.py` | 移除 1 处路由层 commit |
| `backend/api/routes/watchlist.py` | 改用 `Depends(get_db_session)` |
| `backend/api/routes/portfolio.py` | 改用 `Depends(get_db_session)` |
| `backend/api/routes/market.py` | 删除多余 session 参数 |
| `backend/db/session_scope.py` | 强化 docstring;调整为 monkeypatch 友好的 import |

## 已知 follow-up(不在本 ADR 范围)

- `refresh_fund` / `refresh_profile` 已恢复 `session=None` 注入契约；网络抓取在事务外，
  注入 session 时只执行持久化。
- 部分历史 service 测试仍直接创建 SQLite engine，需按 PostgreSQL worker schema fixture
  迁移计划处理；本 ADR 不恢复 SQLite 兼容分支。

## 后续约束

- 任何新 service 函数禁止 `s.commit() / s.rollback() / s.close()`(契约测试守护)
- 任何新 repository 函数禁止 `s.commit() / s.rollback() / s.close()`(契约测试守护)
- 任何长事务 service 必须先 fetch 再 write,fetch 阶段无 DB session
