# 知识库稳定化补充修复设计

## 背景

2026-07-10 的 pgvector 稳定化实现已经建立持久向量适配、结构化降级、重试和任务记录，但项目审查发现六个实际运行缺口：测试会写入开发数据库、两个 360 秒调度任务持续碰撞、旧 embedding 不会重新入队、dimension 变化缺少安全重建路径、健康检查永远返回正常、内容变化后分类尝试次数不重置。

## 范围

本轮只在现有 FastAPI、SQLAlchemy 和 APScheduler 架构内修复上述缺口，不引入 Celery、Redis、Alembic、多 worker 选主、鉴权或新的前端页面。

## 设计

### 测试隔离与数据清理

- `test_knowledge_reindex_with_local_trigger` 必须覆盖 `get_db_session`，使用临时 SQLite 文件；测试不得导入或写入默认 `backend/data/fund_agent.db`。
- 增加测试证明请求结束后临时库存在 job，默认开发库不参与测试。
- 清理只删除可明确识别为测试产生、从未启动且没有结果/错误的 `manual + pending` reindex 记录；不删除 running、terminal、scheduled 或已有业务结果的记录。

### 调度错峰

- `IntervalTrigger` 自身接收 `jitter`，不得把 jitter 作为 `add_job()` 的无效 trigger 参数传入。
- CLS 与 knowledge 即使默认周期都为 360 秒，也必须拥有不同的首次执行偏移；knowledge 首次执行至少晚于 CLS 一个固定错峰窗口。
- 继续保留进程级 fast-fail 单飞锁和单 backend worker 约束。

### 向量重新入队与维度重建

- 索引选择集合包含：`pending`、可重试 `failed`、以及 `indexed` 但 `embedding_model` 或 `embedding_version` 与当前 provider 不一致的文档。
- 内容变化仍由 document 写入路径把 `index_status` 设为 `pending`；pgvector 查询继续校验 vector row 的 content hash。
- 普通 `/reindex` 不隐式删除向量表。
- 新增显式管理函数重建 PostgreSQL `knowledge_embeddings` 表；调用方必须提供确认标志。SQLite 返回不支持，维度缺失返回校验错误。
- 文档在表重建后统一变为 `pending`，清空 embedding model/version 和索引错误状态，等待正常批次重建。

### 运行健康状态

- `/api/health` 保持顶层 `status` 向后兼容，并新增 `database`、`knowledge_vector`、`scheduler` 子状态。
- 数据库不可查询时顶层为 `degraded`。
- 显式选择 `pgvector` 但配置、方言或 schema 前置条件不满足时，`knowledge_vector.status=degraded`；structured 模式为 `disabled`；auto 降级为 `structured_fallback`。
- 健康检查不得调用远程 embedding API。

### 分类重试

- attempt number 在 prompt version 或 canonical content hash 任一变化时重置为 1。
- 同一内容、同一 prompt 的失败仍按最大次数和退避时间限制。

## 验证

- 针对性后端测试覆盖测试隔离、jitter/错峰、模型版本重新入队、维度重建状态转换、health 降级和分类计数重置。
- 后端全量 pytest、Python compileall、前端 Node 测试和 Next.js production build 必须通过。
- 有 `TEST_PGVECTOR_DATABASE_URL` 时执行 live pgvector 集成测试；没有时明确报告 skipped。
- Docker 不可用时不得宣称 compose 验证通过。

