# Transaction Ownership Review Fixes Design

**Date:** 2026-07-15  
**Status:** Approved for implementation planning

## Goal

修复 Phase 1.2 review 中发现的事务所有权回归，确保 service 在调用方注入
`Session` 时只执行数据库操作和 `flush()`，且网络、LLM、embedding 等慢调用不在
已启动的数据库事务中运行。

## Invariants

- repository 不调用 `commit()`、`rollback()` 或 `close()`。
- service 接受外部 session 时不提交、回滚或关闭该 session。
- service 在 `session=None` 时通过 `session_scope()` 拥有事务。
- 网络、LLM 和 embedding 调用执行时不得存在由当前 service 启动的活动事务。
- 需要原子性的多表业务操作仍位于同一个最外层事务内。
- PostgreSQL 是唯一运行时和测试数据库；不增加 SQLite 兼容分支。

## Design

### Watchlist transaction ownership

`transaction_service.recalc_holding()` 保留可选 `session`，删除 `commit` 参数和内部
commit/close。未传 session 时使用 `session_scope()`；传入 session 时只更新 ORM 状态并
flush。`watchlist_service` 的 add/remove/initial-holding/confirm-pending-buy 路径统一调用
这个 flush-only 接口。多表原子性由各公开函数最外层的 `session_scope()` 或调用方事务
提供，不再通过内部 commit 提供。

### Fund refresh compatibility

`refresh_fund()` 和 `refresh_profile()` 恢复 `session=None` 参数。函数先完成所有网络抓取，
再将纯数据库写入委托给内部 helper：传入 session 时在该 session 上 flush；否则使用
`session_scope()` 提交。这样保留现有调用契约，同时避免网络阶段持有事务。

### Knowledge ingestion

候选按“批量短读、事务外 classify、批量短写”处理：

1. 使用短只读事务读取 classification state，并决定是否需要分类。
2. 关闭该事务后调用 classifier/LLM。
3. 使用调用方 session 或独立短写事务重新读取 state；如果同一候选已被并发处理，则按
   最新状态跳过，否则写 document、source link 和 classification 结果。

外部 session 只覆盖写阶段，不能包住 LLM。必须先完成本批全部分类再开始写入，否则第一条
写入启动的外部事务会覆盖后续候选的 LLM 等待时间。写阶段仍逐条重新校验状态，避免并发
更新被过期分类结果覆盖。

### Knowledge search

在创建或使用数据库 session 前生成 query embedding。随后在一个短只读事务内完成 fund
match、structured query 和 pgvector search。检索结束后关闭只读事务，再通过调用方
session 或独立短写事务记录 retrieval log。embedding 失败时维持现有 structured fallback
语义。

### Market snapshot cache miss

缓存读取和网络刷新分离。`session=None` 时先用短事务读取缓存；未命中则关闭事务并调用
`collect_market_intel(session=None)`。传入外部 session 时只查询缓存；未命中后在外部事务
之外执行刷新，因此刷新结果使用自己的短写事务，不能复用已执行 SELECT 的 session。

### Contract enforcement

AST 契约不再按文件 skip。检查每个函数中的任意 attribute call，只要方法名是
`commit`、`rollback` 或 `close` 就报告违规。若仍有不可消除的例外，白名单必须精确到
`(path, function_name)`；本轮修复目标是删除 watchlist 和 transaction service 白名单。

## Error Handling

- 网络、LLM、embedding 的现有业务降级语义保持不变。
- 数据库异常不得在已失败的事务中被吞掉并继续执行；异常交给最外层事务管理器回滚。
- 外部 session 上的异常向调用方传播，由调用方决定回滚。
- 并发 ingestion 写入前重新校验状态，避免过期分类结果覆盖更新后的候选状态。

## Testing

- Watchlist：注入 session 后调用各写服务，确认没有 commit；调用方 rollback 后无数据残留。
- Fund refresh：验证 `session=` 兼容，且 collector 在任何写事务开始前执行。
- Knowledge ingestion：用事务状态探针确认 classifier 执行时无活动事务，并覆盖并发状态变化。
- Knowledge search：确认 embedding 执行时无活动事务，embedding 失败仍结构化降级。
- Market snapshot：缓存 miss 时确认网络 collector 不接收已执行查询的 session。
- AST contract：构造同文件非白名单函数违规用例，确认测试失败；确保不再整文件 skip。
- 运行相关 service 测试、事务契约测试和 PostgreSQL fixture 测试集。

## Non-goals

- 不修改业务计算公式、API response schema 或调度频率。
- 不恢复 SQLite fixture 或 SQLite 锁重试逻辑。
- 不在本轮引入跨进程任务锁；业务单飞语义维持现状。
