# 基金自选池驱动的市场知识库与 RAG 检索系统设计

> 日期：2026-07-09
> 负责人：fund-agent 系统规划

## 1. 背景

fund-agent 已经具备基金自选池、持仓盈亏、市场情报页、每日简报、财联社电报同步和 `market_evidence` 证据面板。当前系统的主要短板不是信息抓取入口，而是缺少一层面向投资语境的知识筛选、归一化和检索能力。

现状问题：

- 财联社电报已经能同步到 `cls_telegraph_items`，但并不是每条电报都适合进入简报或问答上下文。
- `market_evidence` 是面板精选层，适合展示，但不适合承担完整知识库职责。
- 关键证据当前更接近“近期记录粗排”，缺少与基金自选池的主题匹配。
- 每日简报需要更稳定的证据召回，而不是依赖固定条数的最新信息。
- 问答系统需要可引用、可过滤、可解释的市场知识检索工具。

本 spec 规划一个长期 RAG 能力：以财联社电报和市场证据为起点，构建“基金自选池驱动的市场知识库”。知识库只收录与股票、基金、投资、宏观、产业链有关的信息，并以当前基金自选池画像作为检索和排序的重要信号。

## 2. 目标

### 2.1 产品目标

知识库服务三个核心场景：

1. **关键证据筛选**：找出今天和用户基金自选池、基金类型、基金主题最相关的信息。
2. **每日简报增强**：为市场状态、板块动向、自选池影响、风险雷达提供可追溯证据。
3. **问答检索**：支持用户询问“某个基金主题为什么受影响”“今天哪些消息和我的持仓相关”。

### 2.2 工程目标

- 原始信息先进入源表，确保不丢数据。
- 只有通过 LLM 准入判断的信息进入知识库。
- 入库前完成标准化、主题提取、基金主题标签、TTL 和索引状态记录。
- 支持增量写入、metadata filter、索引状态、失败重试和过期删除。
- 支持当前基金自选池画像匹配，不要求第一版支持股票自选池。
- 向量库不替代 SQL 原始表，只作为语义检索索引。

## 3. 非目标

本阶段不做：

- 泛财经新闻归档。
- 股票自选池和个股持仓体系。
- 基金真实重仓股穿透。
- 多来源权威性复杂裁决。
- 高频实时推送。
- 研报级长文本深度解析。
- 自动交易、买卖建议、仓位建议或收益预测。

## 4. 总体架构

```
财联社电报 / market_evidence / 后续公告政策
        ↓
原始表落库
        ↓
LLM 入库准入判断
        ↓
knowledge_documents 标准化写入
        ↓
embedding 队列
        ↓
向量索引 upsert
        ↓
基金自选池画像匹配
        ↓
混合检索与重排
        ↓
关键证据 / 每日简报 / QA Tool
```

核心原则：

- **原始数据和知识索引分离**：`cls_telegraph_items` 继续保存完整电报，知识库只保存可检索知识。
- **新信息优先可见**：原始表成功写入后即可通过 SQL/FTS 兜底检索，embedding 延迟不能导致最新信息完全不可见。
- **基金画像驱动召回**：检索结果不仅看语义相似度，还要看是否命中用户自选基金的主题和类型。
- **过期知识退出默认召回**：原文保留，向量索引删除或标记不可检索。

## 5. 数据来源

### 5.1 第一版来源

| 来源 | 原始表 | 入库策略 |
|------|--------|----------|
| 财联社电报 | `cls_telegraph_items` | LLM 判断后进入知识库 |
| 市场证据 | `market_evidence` | 直接进入准入流程，保留精选属性 |

### 5.2 后续来源

| 来源 | 说明 |
|------|------|
| 公告 | 接入公告系统后，长文本进入 chunk 流程 |
| 政策 | 监管、交易所、宏观政策文件 |
| 宏观数据 | 经济指标、利率、汇率、大宗商品 |
| 市场快照 | 板块、指数、资金流，可作为派生知识 |

## 6. 入库准入

入库准入由 LLM 完成，不使用关键词硬筛作为主判断。关键词、财联社 `subjects`、基金名称规则只作为 LLM 输入上下文和兜底信号。

### 6.1 准入输入

每条候选信息提交给 LLM 时包含：

```json
{
  "source_type": "cls_telegraph",
  "source_id": "123456",
  "title": "美股AI牛市熄火？逾六成科技股较近期高点暴跌逾20%",
  "brief": "...",
  "content": "...",
  "cls_subjects": ["人工智能", "半导体芯片", "美股动态"],
  "symbols": [],
  "published_at": "2026-07-09 10:31:00",
  "dedupe_hints": {
    "content_head_hash": "sha256:头200字hash",
    "source_url_slug": "detail/123456",
    "alternate_source_ids": [
      {"source_type": "market_evidence", "source_id": "ev-9981"}
    ]
  }
}
```

`dedupe_hints` 用于跨来源去重：同一篇内容如果同时被 `cls_telegraph_items` 和 `market_evidence` 收录（财联社常见情形），service 层依据归一化后的标题、正文前缀和发布时间窗口计算来源无关的 `canonical_content_hash`。`knowledge_documents.canonical_content_hash` 做唯一约束，避免重复入库、重复 embedding。来源关系不塞进去重键，而是写入 `knowledge_source_links` 用于溯源。

### 6.2 准入输出

LLM 必须返回严格 JSON：

```json
{
  "should_index": true,
  "relevance_score": 0.86,
  "summary": "美股AI相关科技股回调，可能影响科技成长类基金风险偏好。",
  "primary_topic": "人工智能",
  "topics": [
    {"name": "人工智能", "weight": "high", "source": "cls_subject"},
    {"name": "半导体芯片", "weight": "high", "source": "cls_subject"},
    {"name": "美股动态", "weight": "medium", "source": "cls_subject"}
  ],
  "topic_title": "人工智能 / 半导体芯片",
  "fund_theme_tags": ["科技成长", "人工智能", "半导体"],
  "fund_type_tags": ["股票型", "混合型", "指数型", "QDII"],
  "markets": ["美股", "A股"],
  "asset_classes": ["股票", "基金"],
  "impact_direction": "negative",
  "effective_ttl_days": 14,
  "reason": "内容涉及AI产业链和美股科技股回调，对科技成长类基金有参考价值。",
  "confidence": "high"
}
```

字段约束：

- `should_index=false` 时必须提供 `reason`，不得写入 `knowledge_documents`。
- `relevance_score` 范围为 `0.0-1.0`。
- `topics` 合并财联社 `subjects` 和 LLM 补充主题，去重后保存；每项必须带 `weight ∈ {high, medium, low}` 和 `source ∈ {cls_subject, llm}`。
- `effective_ttl_days` 由信息类型决定，缺省按来源类型兜底（详见 13 节）。
- `confidence` 取值为 `high`、`medium`、`low`。

### 6.3 准入失败处理

LLM 调用失败时：

- 原始数据保留。
- 不写入知识库。
- 在 `knowledge_classification_state` 记录 `status=failed`，并在 `knowledge_classification_log` 记录错误信息。
- 后台任务可重试。

LLM JSON 解析失败时：

- 记录失败原文摘要和错误。
- 不使用半结构化结果。
- 最多重试一次，仍失败则进入失败队列。

`should_index=false` 的候选**同样需要可观测**，否则"被拒绝的证据"会成为数据黑洞。约定：

- 所有候选的最新准入状态写入 `knowledge_classification_state`，不依赖 `knowledge_documents`。
- 每一次 LLM 调用尝试都追加写入 `knowledge_classification_log`，用于审计和排错。

`knowledge_classification_state` 字段：

```text
id
source_type
source_id
canonical_content_hash
latest_attempt_no
should_index          # bool
relevance_score       # float, LLM 自评
prompt_version        # 准入 prompt 版本号
status                # pending / accepted / rejected / failed
reason                # 最新 LLM 原因或失败摘要
document_id           # accepted 后关联 knowledge_documents.id；rejected/failed 为空
last_error_message
updated_at
created_at
```

唯一约束：`UNIQUE(source_type, source_id)`，保证同一来源只有一个最新状态。

`knowledge_classification_log` 字段：

```text
id
source_type
source_id
canonical_content_hash
attempt_no
prompt_version
status                # accepted / rejected / failed
should_index
relevance_score
reason
raw_response_json     # 完整 LLM 返回，便于事后审计
error_message
latency_ms
created_at
```

唯一约束：`UNIQUE(source_type, source_id, prompt_version, attempt_no)`，允许同一来源多次重试并保留每次结果。

## 7. 标准化知识格式

### 7.1 `knowledge_documents`

建议新增表 `knowledge_documents`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 主键 |
| `source_type` | string | `cls_telegraph` / `market_evidence` / `announcement` / `policy` |
| `source_id` | string | 原始表 id 或业务 id |
| `source_url` | string | 原文链接 |
| `title` | string | 标题 |
| `summary` | string | LLM 生成摘要 |
| `content` | string | 清洗后的正文或摘要正文 |
| `normalized_text` | string | 用于 embedding 的标准文本 |
| `primary_topic` | string | 主主题 |
| `topic_title` | string | 展示小标题 |
| `topics_json` | string | 主题对象数组，含 `name`、`weight`、`source` |
| `topic_names_json` | string | 主题名称数组，用于 metadata filter |
| `fund_theme_tags_json` | string | 基金主题标签 |
| `fund_type_tags_json` | string | 基金类型标签 |
| `markets_json` | string | 市场标签 |
| `asset_classes_json` | string | 资产类别 |
| `impact_direction` | string | `positive` / `negative` / `neutral` / `mixed` / `unknown` |
| `published_at` | string | 信息发布时间 |
| `effective_until` | string | 默认有效期截止时间 |
| `relevance_score` | float | LLM 入库相关性 |
| `classification_status` | string | 分类状态 |
| `index_status` | string | 索引状态 |
| `embedding_model` | string | embedding 模型 |
| `content_hash` | string | 去重 hash |
| `canonical_content_hash` | string | 来源无关的跨来源去重键 |
| `raw_reason` | string | LLM 入库原因 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

唯一约束：

```text
UNIQUE(source_type, source_id)
UNIQUE(content_hash)
UNIQUE(canonical_content_hash)
```

`knowledge_documents` 只保存通过准入的知识。`rejected` 和 `failed` 候选不会创建 document，其状态从 `knowledge_classification_state` / `knowledge_classification_log` 查询。

### 7.2 `knowledge_source_links`

建议新增表 `knowledge_source_links`，保存一个知识文档对应的一个或多个来源：

| 字段 | 说明 |
|------|------|
| `id` | 主键 |
| `document_id` | 关联 `knowledge_documents.id` |
| `source_type` | 来源类型 |
| `source_id` | 来源 id |
| `source_url` | 来源链接 |
| `is_primary` | 是否主来源 |
| `created_at` | 创建时间 |

唯一约束：

```text
UNIQUE(source_type, source_id)
UNIQUE(document_id, source_type, source_id)
```

同一内容跨来源重复出现时，只保留一个 `knowledge_documents`，并追加多条 `knowledge_source_links`。

### 7.3 `normalized_text`

`normalized_text` 使用固定模板，提升 embedding 稳定性：

```text
标题：...
摘要：...
正文：...
主题：人工智能 / 半导体芯片
基金主题：科技成长 / 人工智能 / 半导体
基金类型：股票型 / 混合型 / 指数型
市场：美股 / A股
发布时间：2026-07-09 10:31:00
来源：财联社电报
```

### 7.4 `knowledge_chunks`

第一版可不实际使用 chunk，但 schema 预留：

| 字段 | 说明 |
|------|------|
| `id` | 主键 |
| `document_id` | 关联 `knowledge_documents.id` |
| `chunk_index` | 分片序号 |
| `chunk_text` | 分片文本 |
| `content_hash` | 分片 hash |
| `index_status` | 分片索引状态 |

财联社电报默认一条 document 一个 chunk。公告、政策、研报类长文本后续按 500-800 中文字符切分。

## 8. 财联社 Tag 与小标题

财联社 `subjects` 是知识主题的第一来源。

主题生成规则：

```text
topics = 去重(财联社 subjects + LLM 补充主题),每项带 weight 与 source
primary_topic = weight=high 的 topics 中,按 cls subjects 顺序取第一个;若全无 high 则 LLM 在 medium 中指认
topic_title = weight=high 的 topics 按 cls subjects 顺序拼接,超过 2 个截断
```

展示示例：

```text
【人工智能 / 半导体芯片】美股AI相关科技股回调
```

如果财联社 `subjects` 为空，LLM 必须根据标题和正文生成 `topics` 并为每项标注 weight。如果 LLM 无法判断任何 high 权重主题，则 `should_index=false`，或写入低置信度并不进入默认简报召回。

## 9. 基金自选池画像

第一版只使用当前基金自选池，不支持股票自选池。

### 9.1 数据来源

| 来源 | 字段 |
|------|------|
| `Watchlist` | `fund_code`、`fund_name`、`is_holding`、`is_focus`、`holding_amount`、`note` |
| `Fund` | `fund_type` |
| `FundProfile` | `peer_category`、`top10_holding_pct`、`top_industry_pct` |

### 9.2 `fund_watchlist_profiles`

建议新增表 `fund_watchlist_profiles`：

| 字段 | 说明 |
|------|------|
| `fund_code` | 基金代码 |
| `fund_name` | 基金名称 |
| `priority` | `holding` / `focus` / `watching` |
| `holding_weight` | 按持仓金额归一化后的权重 |
| `fund_type` | 基金类型 |
| `peer_category` | 同类分类 |
| `theme_tags_json` | 主题标签 |
| `risk_tags_json` | 风险标签 |
| `match_basis_json` | 画像来源 |
| `profile_status` | `ready` / `partial` / `failed` |
| `updated_at` | 更新时间 |

画像示例：

```json
{
  "fund_code": "000000",
  "fund_name": "某人工智能主题混合",
  "priority": "holding",
  "holding_weight": 0.35,
  "fund_type": "混合型",
  "peer_category": "科技成长",
  "theme_tags": ["人工智能", "算力", "半导体", "科技成长"],
  "risk_tags": ["高波动", "成长风格"],
  "match_basis": ["fund_name", "fund_type", "peer_category", "note"]
}
```

### 9.3 画像刷新

触发条件：

- 新增、删除、编辑自选基金。
- `is_holding`、`is_focus`、`holding_amount` 变化。
- 基金基础信息或 `FundProfile` 更新。
- 手动刷新知识库匹配。

画像生成失败时保留旧画像，并标记 `profile_status=partial` 或 `failed`。

## 10. 知识与基金匹配

### 10.1 `knowledge_fund_matches`

建议新增表 `knowledge_fund_matches`，用于预计算知识和自选基金的关系：

| 字段 | 说明 |
|------|------|
| `document_id` | 知识 id |
| `fund_code` | 基金代码 |
| `match_score` | 匹配分 |
| `matched_topics_json` | 命中主题 |
| `match_reason` | 可展示原因 |
| `created_at` | 创建时间 |

唯一约束：

```text
UNIQUE(document_id, fund_code)
```

### 10.2 匹配规则

匹配分由以下因素组成，结果统一归一化到 `[0, 1]`：

```text
match_score =
  命中持仓基金主题 0.40
  + 命中关注基金主题 0.20
  + 命中 primary_topic 0.15
  + 命中 fund_theme_tags 0.15
  + 命中 fund_type_tags 0.05
  + holding_amount 归一化权重 0.05
最终截断到 [0, 1]
```

`holding_amount` 在所有命中基金之间按金额归一化为 [0, 1]，再叠加到 `holding_amount` 这一档。`match_score < 0.10` 视为弱命中，简报召回时降权但仍保留。

示例原因：

```text
命中持仓基金“某人工智能主题混合”的主题：人工智能、半导体。
```

### 10.3 实时与预计算

默认使用预计算 `knowledge_fund_matches`。当新知识已经入库但匹配任务尚未完成时，检索层可以临时实时计算匹配分，避免最新数据不可见。

## 11. 向量索引

### 11.1 后端选择

短期推荐：

```text
SQLite 原始表 + knowledge_documents + Qdrant local
```

备选：

```text
Chroma local
```

长期可迁移：

```text
Postgres + pgvector
```

实现时必须通过 `VectorStoreAdapter` 隔离向量库细节，避免业务层直接依赖具体后端。

### 11.2 Metadata

向量索引必须保存以下 metadata：

```json
{
  "document_id": 1,
  "source_type": "cls_telegraph",
  "source_id": "123456",
  "primary_topic": "人工智能",
  "topics": ["人工智能", "半导体芯片"],
  "topic_weights": {"人工智能": "high", "半导体芯片": "high"},
  "fund_theme_tags": ["科技成长", "半导体"],
  "fund_type_tags": ["混合型", "指数型"],
  "published_at": "2026-07-09 10:31:00",
  "effective_until": "2026-07-23 10:31:00",
  "index_status": "indexed"
}
```

### 11.3 索引状态

`index_status` 取值：

| 状态 | 含义 |
|------|------|
| `pending` | 等待 embedding |
| `processing` | 正在处理 |
| `indexed` | 已可检索 |
| `failed` | 索引失败 |
| `expired` | 已过期，不参与默认检索 |
| `deleted` | 已从向量索引删除 |

`classification_status` 取值：

| 状态 | 含义 |
|------|------|
| `pending` | 等待 LLM 准入判断 |
| `accepted` | 已通过准入 |
| `rejected` | 不进入知识库 |
| `failed` | 准入判断失败 |

`knowledge_documents.classification_status` 只保存已创建文档的状态，正常情况下为 `accepted`。`pending`、`rejected`、`failed` 的候选状态以 `knowledge_classification_state` 为准。

## 12. 检索设计

检索不是纯向量召回，而是混合检索：

```text
结构化过滤
  ↓
关键词 / FTS 兜底召回
  ↓
向量召回
  ↓
基金画像匹配加权
  ↓
时间新鲜度重排
  ↓
去重和覆盖度处理
```

### 12.1 Metadata Filter

必须支持：

```text
source_type
primary_topic
topics
fund_theme_tags
fund_type_tags
fund_code
impact_direction
published_at range
effective_until
classification_status
index_status
```

`topics` filter 使用 `topic_names_json` 或向量 metadata 里的字符串数组，不直接过滤 `topics_json` 对象数组。

`impact_direction` 在 filter 上以枚举值精确匹配；语义排序时若 `query` 中显式命中方向词（涨/跌/利好/利空/上行/下行/回调/反弹 等），命中方向 +0.05 作为 `direct_match_bonus`，避免一条"反向但语义相近"的消息盖过"同向但措辞略有不同"的命中。

### 12.2 排序公式

默认排序：

```text
final_score =
  min(
    1,
    semantic_score * 0.30
    + freshness_score * 0.20
    + fund_match_score * 0.30
    + relevance_score * 0.20
    + direct_match_bonus
  )
```

各项取值范围与定义：

- `semantic_score ∈ [0, 1]`，来自向量余弦相似度或 FTS 相关性归一化值。
- `freshness_score ∈ [0, 1]`，按 `published_at` 与当前时间的差做指数衰减：`freshness = exp(-age_hours / 72)`，半衰期约 50 小时；缺 `published_at` 时取 `0.5`。
- `fund_match_score ∈ [0, 1]`，定义见 10.2。
- `relevance_score ∈ [0, 1]`，LLM 入库准入打分。
- `direct_match_bonus ∈ {0, 0.05}`，见 12.1。

设计意图：相比通用 RAG 提升 `fund_match_score` 与 `relevance_score` 的权重，体现"自选池驱动 + LLM 入库预筛"的双信号；`semantic_score` 退居次位以避免和主题词面差异较大的高质量命中被埋没。

QA Tool 与简报共用同一排序公式；简报侧可叠加 `selection_reason` 文本（命中持仓主题 / 命中 primary_topic 等）。

### 12.3 兜底策略

检索模式分三档，各自能力边界：

| 模式 | 触发条件 | 能力 | 局限 |
|------|---------|------|------|
| `hybrid` | 向量 + FTS 都可用 | 语义 + 关键词 + 画像 + 时间 全套 | 无 |
| `vector_only` | FTS 不可用（SQLite 缺 fts5 扩展等） | 语义 + 画像 + 时间 | 召回对中文分词不友好 |
| `structured_fallback` | 向量库不可用 | 关键词 + metadata filter + 时间 | 无法处理语义相近但词面不同的召回；命中文档需在结果里打 `semantic_unavailable=true` 标记 |

`structured_fallback` 模式下，API 返回增加 `coverage_warning` 字段，简报消费方据此降级展示口径：

```json
{
  "retrieval_mode": "structured_fallback",
  "coverage_warning": "语义索引暂不可用，已使用结构化检索兜底；本次结果仅基于标题/主题/基金标签关键词匹配，可能遗漏语义相近但词面不同的命中。",
  "items": [...]
}
```

如果 embedding 滞后：

- `indexed` 数据优先。
- 最近 `pending` 且 `classification_status=accepted` 的数据可以通过 SQL/FTS 参与关键证据候选，结果项携带 `index_status=pending` 标记。

## 13. 生命周期与旧知识删除

知识生命周期按信息类型区分。

| 类型 | 默认 TTL |
|------|----------|
| 财联社电报 | 7-30 天 |
| 行情异动 | 3-14 天 |
| 公告 | 90-365 天 |
| 政策 | 180-730 天 |
| 宏观数据 | 90-365 天 |

`effective_ttl_days` fallback（LLM 未返回或返回非法值时按来源类型兜底）：

```text
cls_telegraph     → 14
market_evidence   → 14
announcement      → 180
policy            → 365
macro_data        → 180
其他 / 未知来源   → KNOWLEDGE_DEFAULT_TTL_DAYS（默认 14）
```

fallback 在 service 层应用，不重新询问 LLM；如果 LLM 返回的 `effective_ttl_days` 超出上表区间（例如 telegram 返回 365），截断到区间上界并在 `raw_reason` 里记 `ttl_clamped=true`。

分层：

```text
热知识：0-7 天，默认参与简报和问答
温知识：8-90 天，相关性高时参与
冷知识：90 天以上，不默认召回
过期知识：退出向量索引，原文保留
```

过期任务行为：

1. 找到 `effective_until < now` 的知识。
2. 从向量索引删除或标记不可检索。
3. 更新 `index_status=expired`。
4. 保留 `knowledge_documents` 记录和原始表数据。

## 14. 简化冲突处理

当前系统来源不多，第一版不做复杂来源权威性比较。

规则：

```text
同主题、同事实、同标的出现矛盾时，默认使用 published_at 更新的数据。
旧数据标记 superseded，不参与默认召回。
```

建议预留字段：

| 字段 | 说明 |
|------|------|
| `supersedes_id` | 当前知识替代的旧知识 |
| `conflict_group_id` | 冲突组 |
| `conflict_status` | `active` / `superseded` / `conflicting` |

第一版只实现 `superseded` 标记，不实现 LLM 自动裁决。

## 15. API 与工具接口

### 15.1 后端 API

建议新增：

```text
GET /api/knowledge/search
POST /api/knowledge/reindex
GET /api/knowledge/status
GET /api/knowledge/queue-status
GET /api/knowledge/documents/{id}
GET /api/knowledge/fund-matches?fund_code=
```

`GET /api/knowledge/queue-status` 参数：

```text
source_type       # 可选，过滤 cls_telegraph / market_evidence / announcement / policy
classification_status  # 可选，pending / accepted / rejected / failed
index_status      # 可选，pending / processing / indexed / failed / expired
since             # 可选 ISO 时间，过滤 created_at > since
limit             # 默认 50，上限 KNOWLEDGE_MAX_SEARCH_LIMIT
```

返回：

```json
{
  "counts": {
    "by_classification": {"accepted": 120, "rejected": 35, "failed": 4, "pending": 8},
    "by_index": {"indexed": 115, "pending": 6, "failed": 3, "expired": 0}
  },
  "items": [
    {
      "document_id": 201,
      "source_type": "cls_telegraph",
      "source_id": "123456",
      "title": "...",
      "classification_status": "accepted",
      "index_status": "indexed",
      "created_at": "2026-07-09 10:31:00"
    }
  ]
}
```

`rejected` 和 `failed` 候选从 `knowledge_classification_state` 返回，`document_id` 为空；只有 `accepted` 且写入成功的候选才返回 `document_id`。

`GET /api/knowledge/search` 参数：

```text
query
fund_code
topic
source_type
date_from
date_to
limit
include_pending
```

`fund_code` filter 从 Phase 2 开始启用。Phase 1 如果收到 `fund_code`，API 返回 `400`，错误信息为 `"fund_code filter requires knowledge fund matching"`，避免用户误以为已按自选池过滤。

返回示例：

```json
{
  "count": 3,
  "retrieval_mode": "hybrid",
  "items": [
    {
      "document_id": 1,
      "title": "美股AI相关科技股回调",
      "topic_title": "人工智能 / 半导体芯片",
      "summary": "...",
      "source_url": "https://www.cls.cn/detail/123456",
      "published_at": "2026-07-09 10:31:00",
      "final_score": 0.82,
      "match_reason": "命中持仓基金主题：人工智能、半导体",
      "matched_funds": ["000000"]
    }
  ]
}
```

### 15.2 LangChain Tool

建议新增工具：

```text
search_market_knowledge
```

`search_market_knowledge` 是 `GET /api/knowledge/search` 的 LangChain 包装层：共用同一组 query 参数、返回结构、`retrieval_mode` / `coverage_warning` 字段；agent 切换到 Tool 调用时不需要重新适配口径。

输入：

```json
{
  "query": "今天人工智能主题有什么重要消息",
  "fund_code": "",
  "topic": "人工智能",
  "date_range": "recent",
  "limit": 8
}
```

输出必须包含：

- 标题
- 摘要
- 来源
- 发布时间
- 匹配原因
- 关联基金或主题

工具不得输出买卖建议。

## 16. 每日简报接入

每日简报的 `key_evidence` 模块应从知识库检索，而不是直接取最新若干条 `market_evidence`。

建议流程：

```text
生成简报 profile
  ↓
构造模块 query
  ↓
知识库检索 top 30
  ↓
按模块和基金画像重排
  ↓
选 top 8-10 条作为关键证据
  ↓
写入 evidence_ids、selection_reason、matched_funds
```

关键证据输出应包含：

```text
title
topic_title
summary
source
published_at
selection_reason
matched_funds
```

## 17. 时效 SLA

目标 SLA：

| 环节 | 目标 |
|------|------|
| 财联社原始同步 | 6 分钟一轮 |
| 原始数据入库 | 同步成功后立即完成 |
| LLM 准入判断 | 原始入库后 1-3 分钟内 |
| embedding 入库 | 准入通过后 1-3 分钟内 |
| 基金匹配计算 | 知识入库后 1 分钟内 |
| 关键证据可见 | 原始数据入库后尽快通过兜底检索可见 |

当 LLM 或 embedding 失败时，不清空已有知识，不影响原始同步。具体策略：

- LLM 调用失败：指数退避重试（1s / 5s / 30s，最多 3 次），最终失败入 `knowledge_classification_log.status=failed`。
- embedding 失败：同上重试策略，最终失败置 `index_status=failed`，文档**仍可被 SQL/FTS 兜底召回**，但结果项携带 `index_status=failed` 标记，前端可降级展示“未向量化”。
- 简报生成时若知识库为空或全部 `failed`：走 `structured_fallback` 并打 `coverage_warning`，前端展示“暂无关键证据”。

区分两类 SLA：

- **提示用户 SLA**（上方表格 6 行）：embedding 1-3 分钟、关键证据可见“尽快”。
- **内部质量 SLA**（不直接告诉用户，但用于监控）：准入命中率 ≥ 80%、embedding 24h 成功率 ≥ 95%、简报关键证据中 `index_status=indexed` 占比 ≥ 90%。

## 18. 配置

建议新增配置：

```text
KNOWLEDGE_RAG_ENABLED=true
KNOWLEDGE_VECTOR_BACKEND=qdrant
KNOWLEDGE_EMBEDDING_MODEL=
KNOWLEDGE_EMBEDDING_VERSION=
KNOWLEDGE_CLASSIFICATION_MODEL=
KNOWLEDGE_CLASSIFICATION_PROMPT_VERSION=v1
KNOWLEDGE_CLASSIFICATION_BATCH_SIZE=10
KNOWLEDGE_INDEX_BATCH_SIZE=20
KNOWLEDGE_DEFAULT_TTL_DAYS=14
KNOWLEDGE_INCLUDE_PENDING_FALLBACK=true
KNOWLEDGE_MAX_SEARCH_LIMIT=50
KNOWLEDGE_MAX_QUEUE_STATUS_LIMIT=200
```

模型配置遵循现有 LLM 配置方式，不在前端暴露密钥。

### 18.1 数据库连接池

按方言自动选择 pool，配置项仅对非 SQLite 方言生效：

```text
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT_SECONDS=10.0
```

- `sqlite:///:memory:` 与 `sqlite://` → `StaticPool`（测试专用）。
- 其他 `sqlite://` 文件库 → `NullPool`，每个 Session 用完即关，SQLite 全局写锁是唯一的同步点；`busy_timeout=15000` + WAL 把锁等待交给 SQLite 而非 SQLAlchemy 队列。
- Postgres / MySQL 等 → `QueuePool(pool_size, max_overflow, pool_timeout, pool_pre_ping=True)`。`pool_timeout` 默认 10s（不再是 30s），避免一次写锁争用拖垮 uvicorn 同步工作线程池。

### 18.2 调度器单飞锁 (`scheduler_lock`)

写入型 scheduler job（`cls_telegraph_sync`、`knowledge_ingest_index`、手动 `POST /api/knowledge/reindex`）共享 [`backend/services/scheduler_lock.py`](../../backend/services/scheduler_lock.py) 提供的进程级 `threading.Lock`。锁非阻塞，锁被占时本次触发直接放弃（`SchedulerLockBusy`），由 APScheduler 在下一轮 interval 自然重试，不积压。

### 18.3 手动 reindex 异步化

[`POST /api/knowledge/reindex`](../../backend/api/routes/knowledge.py) 不再在请求线程里同步跑 pipeline：

1. 立刻在 `knowledge_reindex_jobs` 表落一行 `pending` 并返回 `202 {"status": "started", "job_id": ..., "poll_url": "/api/knowledge/reindex/{job_id}"}`。
2. 后台 daemon 线程进入 `scheduler_lock` 跑 `run_knowledge_pipeline_once`，并发时锁被占则 `busy_skipped`。
3. 前端用 `GET /api/knowledge/reindex/{job_id}` 轮询状态（`pending / running / completed / failed / busy_skipped`）。
4. `GET /api/knowledge/reindex?limit=N` 列出最近 N 条任务，方便排查。

端点必须带 `X-Local-Trigger: 1` 头（部署端不会被外部误触发）。

### 18.4 `cls_telegraph_sync` 失败路径

财联社同步异常时 `update_cls_telegraph_sync_state` 写 `last_error` 这一步本身可能再次失败（典型场景：SQLite database is locked）。`backend/services/cls_telegraph_sync_service.py` 已把这一步异常吞掉降级为 `logger.warning`，不让「记错误」把整个 scheduler 触发器搞崩；下一轮 tick 再试。

## 19. 可观测性

需要记录：

- 原始候选条数。
- LLM 接受、拒绝、失败数量。
- embedding 成功、失败数量。
- 向量索引状态分布。
- 过期删除数量。
- 检索耗时。
- 检索模式：`hybrid` / `vector_only` / `structured_fallback`。
- 简报关键证据命中基金画像的比例。

建议新增 `knowledge_retrieval_logs`：

| 字段 | 说明 |
|------|------|
| `query` | 检索问题 |
| `filters_json` | 过滤条件 |
| `retrieval_mode` | 检索模式 |
| `result_count` | 结果数 |
| `latency_ms` | 耗时 |
| `created_at` | 时间 |

## 20. 安全与合规

- 系统只做信息整理、证据检索和风险提示。
- 不输出买入、卖出、持有、加仓、减仓、申购、赎回建议。
- RAG 结果必须引用来源和时间。
- LLM 生成的摘要不得覆盖原始事实。
- 用户自选池画像只在本地系统内使用，不发送到前端之外的第三方服务，除非用户配置的 LLM 调用本身需要必要上下文。
- 对外展示时必须保留“仅供研究参考”声明。

## 21. 分阶段路线

### Phase 1：知识库 MVP

范围：

- `cls_telegraph_items` 和 `market_evidence` 进入准入流程。
- LLM 判断是否入库。
- 写入 `knowledge_documents`。
- 支持基础 embedding 和向量索引。
- 支持 `GET /api/knowledge/search`。
- 不支持 `fund_code` filter；基金画像匹配在 Phase 2 实现。

验收：

- 原始财联社电报不会因准入失败丢失。
- `GET /api/knowledge/queue-status` 能按 `classification_status`、`index_status` 列出待处理 / 失败清单。
- 能按 query 和 topic 返回带来源的知识结果。
- `fund_code` filter 在 Phase 1 明确返回 400，不静默忽略。

### Phase 2：基金画像匹配

范围：

- 新增 `fund_watchlist_profiles`。
- 生成基金主题标签。
- 新增 `knowledge_fund_matches`。
- 检索排序加入基金画像匹配。

验收：

- 系统能说明某条知识命中了哪些自选基金主题。
- 持仓基金相关信息优先于普通关注信息。

### Phase 3：每日简报接入

范围：

- `key_evidence` 模块改用知识库检索。
- 简报保留 `selection_reason` 和 `matched_funds`。
- 前端展示小标题和匹配原因。

验收：

- 关键证据不是简单最新 10 条。
- 每条关键证据能解释为什么被选中。

### Phase 4：生命周期治理

范围：

- 过期任务。
- 索引失败重试。
- 状态 API。
- 检索日志。

验收：

- 过期知识不参与默认召回。
- 管理接口能区分未抓取、未分类、未索引、索引失败。

### Phase 5：长文本扩展

范围：

- 公告、政策、研报类长文本。
- `knowledge_chunks` 实际启用。
- 段落级引用。

验收：

- 长文本检索返回具体片段和原文位置。
- 财联社短文本路径不受影响。

## 22. 测试计划

### 单元测试

- LLM 准入 JSON schema 校验。
- `subjects` 和 LLM topics 合并去重。
- `normalized_text` 生成稳定。
- TTL 计算。
- content hash 去重。
- 基金画像主题生成。
- 知识和基金主题匹配分计算。
- 排序公式稳定。

### 集成测试

- 财联社电报候选进入准入流程。
- `should_index=true` 写入 `knowledge_documents`。
- `should_index=false` 不写入知识库但保留原始记录。
- embedding 成功后更新 `index_status=indexed`。
- 向量不可用时走结构化兜底。
- 过期任务更新 `index_status=expired`。

### 回归测试

- 现有 `market_evidence` 面板继续可用。
- 财联社同步失败不清空知识库。
- 每日简报在知识库为空时降级展示“暂无关键证据”。
- QA Tool 不输出投资建议。

## 23. 验收标准

Phase 1 + Phase 2 完成后应满足：

1. 财联社电报可以按 LLM 准入结果进入或拒绝进入知识库。
2. 每条知识都有 `topics`、`topic_title`、`summary`、`relevance_score`、`index_status`。
3. 检索支持 topic、时间、source_type、fund_code 过滤。
4. 自选基金画像能参与排序。
5. 关键证据可以解释选择原因。
6. embedding 或向量库失败时有结构化兜底。
7. 过期知识不参与默认召回。
8. 所有输出保留来源和发布时间。

## 24. 设计决策

- 第一版使用当前基金自选池、基金类型、基金主题做匹配，不做股票自选池。
- 入库筛选使用 LLM，不以关键词作为主过滤条件。
- 财联社 `subjects` 作为小标题和主题标签的重要来源。
- 向量库只做检索索引，不做事实源。
- 冲突处理第一版采用“更新发布时间优先”，不做复杂来源权威排序。
- 长文本切分能力预留，但不作为第一版重点。
- embedding 模型可换，但向量维度一旦确定不可热切换，切换需触发全量重 embedding；`knowledge_documents` 增加 `embedding_model` 与 `embedding_version` 字段记录模型版本，避免历史向量被误用。
- `fund_watchlist_profiles.theme_tags` 采用 LLM 生成 + 用户手动覆盖双轨制：用户手动编辑的标签写入 `manual_overrides_json`，下次自动刷新不被覆盖，只在用户主动重置时清空。
- 跨来源去重以来源无关的 `canonical_content_hash` 为准，财联社电报与市场证据重复收录的情形视为同一知识；多来源关系写入 `knowledge_source_links`。
