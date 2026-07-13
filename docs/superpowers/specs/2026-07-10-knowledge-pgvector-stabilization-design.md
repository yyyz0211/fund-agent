# 知识库 pgvector 稳定化设计

> 状态：已确认方案，待实施。本文修订 2026-07-09 知识库设计中“SQLite + Qdrant local”的短期选型，使其与当前 PostgreSQL Docker 部署保持一致。

## 1. 背景

当前知识库代码已经包含准入分类、知识文档、基金画像、匹配关系和向量存储抽象，但存在以下交付阻塞：

- Docker 业务数据库已经是 PostgreSQL，配置却仍默认声明 Qdrant；仓库没有 Qdrant 服务或 Qdrant adapter。
- 生产路径使用测试用 deterministic embedding 和进程内向量库，进程重启后向量丢失，但文档仍会被标记为 `indexed`。
- FastAPI 请求 Session 没有统一的关闭和事务边界，手动 reindex 任务在提交前启动，后台线程看不到任务记录。
- 调度器会反复分类相同内容；过期知识仍参与检索；索引失败不会重试；基金画像和匹配关系会留下陈旧记录。
- 前端存在一条失败的源码正则测试，以及为迎合静态测试加入的死字符串。

## 2. 目标

本轮交付目标：

1. PostgreSQL 部署使用 pgvector 作为持久语义索引。
2. SQLite 本地开发和单元测试无需安装向量扩展，明确使用结构化检索降级。
3. 向量能力不可用时不伪报 `indexed` 或 `hybrid`。
4. 修复 Session 生命周期、异步任务事务可见性和检索日志持久化。
5. 让准入分类、索引、TTL 和基金匹配具备幂等且可重试的生命周期。
6. 保持所有离线测试不访问真实 LLM、embedding API、PostgreSQL 或网络。

## 3. 非目标

本轮不包含：

- 引入独立 Qdrant 或 Chroma 服务。
- 强制所有本地开发者使用 PostgreSQL。
- 引入 Celery、Redis 等外部任务队列。
- 完整替换为 Alembic 迁移体系。
- 改造现有 Tailscale 信任模型或为全部管理接口增加用户系统。
- 处理多 Uvicorn worker、多副本调度器的分布式选主；部署仍明确限制为单 backend worker。

上述事项可作为独立后续工作，避免本轮稳定化范围失控。

## 4. 总体架构

采用双模式：

```text
PostgreSQL
  knowledge_documents（事实与结构化 metadata）
          |
          +--> knowledge_embeddings（pgvector 持久索引）
          |
          +--> 结构化候选 + 向量候选 --> 合并去重 --> 基金匹配/时效重排

SQLite
  knowledge_documents --> 结构化过滤与关键词召回
                       --> retrieval_mode=structured_fallback
```

`knowledge_documents` 继续是知识状态的权威来源。`knowledge_embeddings` 只是可重建索引，不保存唯一事实。业务服务只能依赖 `VectorStoreAdapter`，不得直接依赖 pgvector SQL。

## 5. pgvector 存储设计

### 5.1 PostgreSQL 镜像与扩展

Docker PostgreSQL 16 改用带 pgvector 扩展的 PostgreSQL 16 镜像。数据库初始化执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

只有 PostgreSQL 方言执行 pgvector DDL；SQLite 不创建 embedding 表。

### 5.2 向量表

新增 PostgreSQL 专用表：

```text
knowledge_embeddings
  document_id        bigint primary key references knowledge_documents(id) on delete cascade
  embedding          vector(KNOWLEDGE_EMBEDDING_DIMENSIONS)
  embedding_model    varchar not null
  embedding_version  varchar not null
  content_hash       varchar(64) not null
  created_at         timestamptz not null
  updated_at         timestamptz not null
```

向量维度来自必填配置 `KNOWLEDGE_EMBEDDING_DIMENSIONS`。启用 pgvector 时若模型、版本、维度或文档 `content_hash` 不一致，文档进入重新索引队列。维度变化不能热切换，必须重建向量表及索引。

首版使用 cosine distance，并建立 pgvector cosine 索引。数据量很小时允许数据库选择顺序扫描；索引参数不在业务代码中硬编码为规模假设。

### 5.3 Embedding provider

真实 embedding 通过 OpenAI-compatible 接口调用，配置与聊天模型分离：

```text
KNOWLEDGE_EMBEDDING_BASE_URL=
KNOWLEDGE_EMBEDDING_API_KEY=
KNOWLEDGE_EMBEDDING_MODEL=
KNOWLEDGE_EMBEDDING_VERSION=
KNOWLEDGE_EMBEDDING_DIMENSIONS=
```

不得默认复用 DeepSeek key/base URL，因为聊天接口可用不代表提供 embedding。任一必要配置缺失时：

- 应用仍能启动；
- PostgreSQL 和 SQLite 都使用 `structured_fallback`；
- 文档保持 `pending`，不得标记为 `indexed`；
- API 返回可观察的 coverage warning。

测试继续使用 `DeterministicEmbeddingProvider` 和 `InMemoryVectorStore`，但生产 factory 不得自动选择它们。

## 6. 检索流程

### 6.1 PostgreSQL 完整模式

当 pgvector 和 embedding provider 均健康时：

1. 校验查询参数并生成 query embedding。
2. 在 pgvector 中按 source、topic、时间和有效期 metadata 过滤，获取扩大后的向量候选集。
3. 同时执行结构化/关键词候选查询。
4. 按 `document_id` 合并去重。
5. 综合 semantic、freshness、classification relevance 和 fund match 得分重排。
6. 截取最终 `limit`，返回 `retrieval_mode=hybrid`。

查询 embedding 或向量 SQL 失败时，不中断请求，记录错误并执行结构化降级。

### 6.2 SQLite 与故障降级

SQLite 或 pgvector 不可用时：

- 只运行结构化检索；
- 返回 `retrieval_mode=structured_fallback` 和 `coverage_warning`；
- 结果项不得宣称存在 semantic score；
- `include_pending=false` 不应错误排除所有尚未向量化但可结构化召回的 accepted 文档。

### 6.3 TTL

默认召回必须满足：

```text
effective_until IS NULL OR effective_until >= 当前时间
```

只有内部诊断接口可显式包含过期文档。日期输入使用日期/时间类型校验，不接受任意字符串比较。

## 7. 事务与 Session 生命周期

所有 FastAPI 数据库依赖统一为 generator dependency：

```text
创建 Session -> yield -> 成功时按路由/服务约定提交 -> 异常回滚 -> finally 关闭
```

具体规则：

- 纯只读路由不提交；带 retrieval audit side effect 的搜索路由在成功返回前只提交该日志写入。
- 写路由由最外层事务所有者提交一次。
- service 接收外部 Session 时不得偷偷提交，只允许 flush；service 自建 Session 时负责 commit/rollback/close。
- reindex 路由先提交 `pending` job，再启动后台线程。
- 后台线程始终创建自己的 Session。
- retrieval log 与搜索查询使用同一请求 Session，并在查询成功后由路由提交；查询失败则回滚，不留下误导性成功日志。

必须有真实 API 集成测试证明 `POST /reindex` 返回后，新的 Session 能立即读取任务记录。

## 8. 准入、索引与重试生命周期

### 8.1 分类幂等

分类前读取 `KnowledgeClassificationState`：

- `canonical_content_hash` 和 `prompt_version` 均未变化，且状态为 accepted/rejected：跳过 LLM。
- 内容 hash 或 prompt 版本变化：重新分类。
- failed 且未超过最大尝试次数、已到 `next_retry_at`：重试。
- failed 超过上限：留在失败队列，等待人工 reindex。

调度批次使用 `knowledge_classification_batch_size`；索引批次独立使用 `knowledge_index_batch_size`。

### 8.2 索引状态

状态含义固定为：

- `pending`：需要首次索引或重新索引。
- `indexed`：持久向量表中存在与当前 model/version/content hash 一致的向量。
- `failed`：最近一次索引失败，但允许按退避策略重试。

索引失败记录尝试次数、最近错误和下次重试时间。不能把整批文档永久停在 `failed`。
向量能力是否启用属于运行时 backend health，不写成文档的永久索引状态；缺少 embedding 配置时文档保持 `pending`，以后补齐配置即可继续索引。

## 9. 基金画像与匹配同步

画像和匹配刷新使用集合同步，而不是只做 upsert：

1. 计算当前自选池目标 profile 集合。
2. upsert 目标 profiles。
3. 删除已经不在自选池中的 profiles。
4. 重新计算目标 `(document_id, fund_code)` match 集合。
5. upsert 正向匹配并删除不再命中的旧匹配。

默认只为 accepted 且未过期文档生成匹配。`fund_code` API 参数在匹配功能可用时正式启用，不再由默认参数永久返回 400。

## 10. 后台任务与调度约束

本轮保留轻量后台线程，但增加以下约束：

- job 行必须先提交再启动线程。
- 进程启动时把长期停留在 `pending/running` 且超过阈值的任务标记为 interrupted，允许重新触发。
- 文档明确 backend 只能运行一个 worker；进程锁不能描述成跨进程锁。
- scheduled pipeline 也写 `KnowledgeReindexJob`，保证手动与定时任务可统一观察。

分布式任务队列和 PostgreSQL advisory lock 留待独立设计。

## 11. 前端与测试

修复当前 briefing 测试和页面文案不一致的问题，并删除 `_evidence_api_ref` 死代码。新的测试应验证实际可见行为，不再依赖为源码正则准备的字符串锚点。

测试分层：

- 纯单元测试：分类跳过规则、TTL、重排、adapter factory、失败状态转换。
- SQLite 集成测试：结构化降级、Session 关闭、reindex 事务可见性、基金匹配集合清理。
- PostgreSQL/pgvector 可选集成测试：扩展初始化、upsert、cosine search、metadata filter、删除级联。
- 前端：生产构建和现有 Node 测试全部通过。

离线默认测试不得连接外部 embedding 或 PostgreSQL。CI 若提供 PostgreSQL 服务，再通过独立 marker 执行 pgvector 集成测试。

## 12. 配置与兼容性

默认配置调整为：

```text
KNOWLEDGE_VECTOR_BACKEND=auto
```

`auto` 的确定性语义：

- PostgreSQL + 完整 embedding 配置 + vector 扩展可用：`pgvector`。
- 其他情况：`structured`。

也允许显式 `pgvector` 或 `structured`。显式选择 `pgvector` 但前置条件不满足时，启动健康状态应报告 degraded，检索仍降级而不是令整个 API 无法启动。

删除 Qdrant 依赖和相关默认配置，更新 README、Docker 文档及环境变量示例。

## 13. 验收标准

1. `POST /api/knowledge/reindex` 返回的 job 可以被随后请求立即读取并最终进入终态。
2. 相同内容和 prompt 版本不会重复调用分类模型。
3. PostgreSQL 完整配置下，向量在进程重启后仍可检索。
4. SQLite 和 embedding 未配置场景明确返回结构化降级，不伪报 `indexed`。
5. 过期知识不参与默认召回，失败索引可按策略重试。
6. 移除基金或改变主题后，不再返回旧 profile/match。
7. scheduled 和 manual reindex 都有统一可查询的 job 记录。
8. 后端完整测试、前端完整测试和前端生产构建全部通过。
9. 所有现有业务 API 保持兼容，新增字段只做向后兼容扩展。

## 14. 实施顺序

1. 先修复 Session/事务边界并用集成测试锁定。
2. 实现分类幂等、TTL、重试和匹配集合清理。
3. 实现 pgvector DDL、adapter factory 和 embedding provider。
4. 接通 hybrid search 和 structured fallback。
5. 修复前端测试，更新配置与文档。
6. 运行完整回归和可选 PostgreSQL/pgvector 集成验证。

这个顺序保证每一步都能独立测试，并且即使真实 embedding 尚未配置，项目也能先获得正确、可观察的结构化降级行为。
