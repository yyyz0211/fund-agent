# 财联社电报信息源接入设计

> 本 spec 规划把财联社电报作为理财/市场信息源接入当前系统。
> 第一版范围是自动沉淀到 `market_evidence`，并提供后端实时搜索能力；
> 不新增前端新闻中心，不把财联社作为唯一或主行情数据源。

## 1. 背景

当前系统已经具备：

- AKShare 驱动的基金、指数、板块、公告等数据采集。
- `market_sources` adapter 体系，用于把外部政策、宏观、公告、行业热点转成统一 evidence。
- `market_evidence` 表，支持按 `trade_date`、`brief_type`、`category`、`query` 检索证据。
- 定时任务：`pre_market_evidence` 与 `post_market_evidence`。
- LangGraph QA 工具：可以调用 `search_market_evidence` 查询本地证据。

但当前信息源偏“数据”和“官方公告”，缺少更及时的财经快讯源。用户希望以财联社作为信息源补充基金、看盘、公司、港美股、提醒类资讯，让系统能回答“今天有什么重要市场消息”“最近某主题有什么新闻”“基金相关快讯有哪些”。

前期探测结论：

- `https://www.cls.cn/telegraph` 可访问，普通无 UA 请求会触发 WAF 418。
- 带浏览器 UA 后，`/api/cache` 可返回最新电报 JSON。
- 前端签名逻辑可复现：参数排序后拼接 query string，先 `SHA1`，再对 SHA1 结果做 `MD5`。
- 加签后，`/v1/roll/get_roll_list` 可分页获取分类电报。
- `/api/csw` 可做关键词搜索。
- `https://www.cls.cn/detail/{id}` 页面内的 `__NEXT_DATA__` 包含结构化 `articleDetail`。

实测单次响应在 2-4 秒之间。这个速度适合后台定时采集和按需搜索，但不适合每轮问答都批量抓详情页。

## 2. 目标

第一版目标：

- 自动采集财联社电报分类列表，写入现有 `market_evidence`。
- 提供后端实时搜索函数和 QA tool，支持按关键词和分类查询财联社。
- 保持失败隔离：财联社失败不影响现有 AKShare、FRED、政策、公告 adapter。
- 保持证据可追溯：每条结果有 `source_url` 指向财联社原文。
- 控制内容存储边界：只保存标题、短摘要、元数据和链接，不长期保存完整长文。

## 3. 非目标

第一版不做：

- 前端新闻中心、筛选面板、详情页或手动刷新按钮。
- 单独 `cls_news` 表。
- 大规模历史回补。
- 批量抓详情页。
- 绕过登录、付费墙或 VIP 内容。
- 把财联社作为基金净值、行情、公告的唯一来源。
- 自动交易、买卖建议或投资推荐。

## 4. 方案选择

采用“证据库 adapter + 实时搜索 service/tool”的方案。

新增一个财联社客户端模块负责协议细节：

- 签名。
- 请求头。
- 分页。
- 搜索。
- JSON 解析和字段清洗。

新增 `ClsTelegraphAdapter` 负责把客户端返回转换成 `market_evidence` 行。这样财联社接口变化时，只需要调整客户端；业务层仍沿用现有 ingestion、repository、scheduler 和 QA 工具模式。

不单独建表的原因：

- 当前需求是为简报和问答补充证据，`market_evidence` 已能表达。
- `source_url` 唯一键足以做幂等 upsert。
- 单独新闻表会引入迁移、查询接口和前端展示范围，超出第一版目标。

## 5. 架构

新增模块建议：

文件组织（遵循现有代码风格）：

```
backend/services/
├── cls_telegraph_client.py      # 协议客户端
│   ├── sign_params(params: dict) -> str
│   ├── fetch_roll_list(category: str, limit: int, last_time: int | None = None) -> list[dict]
│   ├── search_telegraph(keyword: str, category: str = "", limit: int = 10) -> list[dict]
│   └── normalize_telegraph_item(item: dict, category: str | None = None) -> dict | None

backend/services/market_sources/
├── cls_telegraph.py             # ClsTelegraphAdapter

backend/tools/market_tools.py    # 新增 search_cls_telegraph tool

backend/config/settings.py        # 新增 CLS 配置项
```

> 注意：`cls_client.py` 命名过于宽泛，使用 `cls_telegraph_client.py` 更明确。`ClsTelegraphAdapter` 与 `PolicyPageAdapter`、`FredSeriesAdapter` 等命名风格一致。

接入点：

- `build_default_adapters(..., brief_type="post_market")` 在 `CLS_ENABLED=true` 时追加 `ClsTelegraphAdapter`。
- `pre_market` 不默认接入财联社，避免盘前噪音过多。
- 现有 `post_market_evidence` cron 复用，不新增 cron。

## 6. 数据流

自动采集：

```text
APScheduler post_market_evidence
  -> market_evidence_service.refresh_market_evidence_async
  -> market_evidence_service.collect_and_run_for_brief_type
  -> build_default_adapters
  -> ClsTelegraphAdapter.fetch
  -> ingest_market_evidence
  -> market_evidence
```

实时搜索：

```text
LangGraph QA
  -> search_cls_telegraph tool
  -> cls_telegraph_client.search_telegraph
  -> normalized items
  -> QA answer with source_url
```

实时搜索第一版不写库。它用于回答即时问题；如果用户后续需要“搜索结果也沉淀为 evidence”，再增加显式入库参数或独立任务。

## 7. 财联社接口约定

基础域名：

- `https://www.cls.cn`

固定参数：

- `app=CailianpressWeb`
- `os=web`
- `sv=8.7.9`

请求头：

- `User-Agent`: 常见桌面浏览器 UA。
- `Referer`: `https://www.cls.cn/telegraph`

签名：

1. 合并业务参数和固定参数。
2. 按参数名大小写不敏感排序。
3. 拼成 `key=value&key=value`。
4. `sha1 = SHA1(query_string).hexdigest()`
5. `sign = MD5(sha1).hexdigest()`
6. `sign` 放入 query 参数。

列表接口：

- `GET /v1/roll/get_roll_list`
- 参数：`refresh_type=1`、`rn`、`last_time`、可选 `category`

搜索接口：

- `POST /api/csw`
- query 带固定参数和 `sign`
- JSON body 包含 `lastTime`、`keyword`、`category` 以及固定参数

详情页：

- `GET /detail/{id}`
- 第一版不批量抓详情页，只保留 `source_url`。

## 8. 分类策略

自动采集默认分类：

- `fund`: 基金
- `watch`: 看盘
- `announcement`: 公司
- `hk_us`: 港美股
- `red`: 加红
- `remind`: 提醒

写入 `market_evidence.category` 时统一使用 `news`。

原因：

- 财联社电报横跨基金、看盘、公司、港美股、提醒，硬塞到现有 `announcement`、`sector`、`macro` 会污染语义。
- `MarketEvidence.category` 是字符串列，不需要迁移即可支持 `news`。
- QA 工具可以显式使用 `category="news"` 查询财联社新闻证据。

原始财联社分类保存在 `metrics.cls_category`，用于后续筛选。

## 9. 字段映射

标准 evidence 字段：

- `source`: `财联社`
- `source_url`: `https://www.cls.cn/detail/{id}`
- `title`: 优先 `title`，为空时从 `brief` 或 `content` 截取前 80 字。
- `summary`: 清洗 HTML 后的 `brief` 或 `content`，截断为短摘要。
- `published_at`: `ctime` 转 `YYYY-MM-DD HH:mm:ss`。**注意**：财联社接口返回的 `ctime` 可能是 Unix 时间戳（秒或毫秒），客户端需要在 `normalize_telegraph_item` 中做时间戳检测与转换；若是 ISO 8601 字符串则直接解析。转换失败时 fallback 为当前采集时间。
- `reliability`: `wire`
- `category`: `news`

`symbols`：

- `stock_list` 中的 `name` 和 `StockID`。
- `subjects` 中的 `subject_name`。

`metrics`：

```json
{
  "cls_id": 2420082,
  "cls_category": "watch",
  "level": "B",
  "reading_num": 49031,
  "comment_num": 47,
  "share_num": 243,
  "images": ["https://..."],
  "audio_url": ["https://..."]
}
```

内容边界：

- `summary` 存短摘要，不保存完整长文。
- 搜索返回里的 `<em>` 高亮标签要清洗。
- 回答中必须带 `source_url`。

> 依赖：`backend/requirements.txt` 中已有 `selectolax>=0.3.21`（用于 HTML 解析）。客户端在清洗 `brief`/`content` 中的 HTML 标签时使用 `selectolax` 的 HTML parser；具体 API 以当前安装版本为准。若财联社返回纯 JSON 则无需 HTML 解析。

## 10. 配置

新增配置项：

- `CLS_ENABLED=true`
- `CLS_SEARCH_ENABLED=true`
- `CLS_TIMEOUT_SECONDS=5`
- `CLS_CATEGORIES=fund,watch,announcement,hk_us,red,remind`
- `CLS_PER_CATEGORY_LIMIT=10`
- `CLS_MAX_SEARCH_LIMIT=10`
- `CLS_APP_VERSION=8.7.9`

默认行为：

- 自动采集启用。
- 实时搜索启用。
- 每类最多 10 条。
- 单次请求 5 秒超时。
- 配置关闭时，不注册 adapter，不暴露实时搜索结果。

> `.env.example` 同步更新：参考上述配置项添加对应的环境变量模板（`CLS_ENABLED`、`CLS_SEARCH_ENABLED`、`CLS_TIMEOUT_SECONDS`、`CLS_CATEGORIES`、`CLS_PER_CATEGORY_LIMIT`、`CLS_MAX_SEARCH_LIMIT`）。

## 11. 错误处理与降级

客户端：

- 网络错误、超时、非 JSON、非 200、签名错误、WAF 响应都转成受控空结果或错误对象。
- 不在日志中打印整篇内容。
- 可以记录接口路径、category、errno、HTTP 状态和异常类型。

Adapter：

- 遵守现有 `market_sources` 契约，`fetch` 永不抛出。
- 单个分类失败不影响其他分类。
- 单条新闻缺 `id` 或无法生成 `source_url` 时跳过。
- 缺 `title` 时 fallback；缺 `ctime` 时使用当前采集时间。

实时搜索：

- 返回结构：`{"items": [...], "error": ""}`。
- 搜索失败时返回 `items=[]` 和可读错误。
- QA 可以向用户说明“财联社实时搜索暂不可用”，而不是整轮失败。

## 11a. 日志规范

客户端日志（使用标准库 `logging`）：

- 记录：接口路径、HTTP 方法、category、HTTP 状态码、错误类型。
- **禁止打印**：`title`、`summary`、全文内容、签名结果、stock_list 详情。
- 日志级别：`INFO` 记录正常请求；`WARNING` 记录 WAF 触发；`ERROR` 记录网络/解析异常。
- 参考格式：`"[cls] GET /v1/roll/get_roll_list category=watch status=200 elapsed=2.4s"`。

Adapter 日志：

- 遵循 `market_sources` 现有风格，由 `ingest_market_evidence` 返回 `fetched`、`inserted`、`categories` 和 `errors` 统计；不新增统一 adapter 日志职责。
- 采集失败时记录 adapter 名称、category 和异常类型，不打印 traceback。


## 12. 性能与限频

实测单次请求：

- 签名分页拿 20 条约 2.4 秒。
- 搜索约 2.5 秒。
- 详情页约 3.4 秒。
- 最新缓存约 3.9 秒。

第一版策略：

- 自动采集只抓列表，不抓详情。
- 每类 10 条，默认 6 类，总量约 60 条。
- 使用一个 `httpx.Client` 复用连接。
- 不做高频轮询。
- 后台任务失败只降级，不重试风暴。

如果后续增加盘中提醒，应新增独立 cron，并设置更严格的总量和间隔。


> 首次启动行为：`post_market` cron 首次运行时，客户端会采集当天（trade_date = 今天）的所有分类列表。若财联社接口历史数据不全，`published_at` 时间戳在当前交易日之前的记录仍会写入（由 ingestion 层的 `trade_date` 字段覆盖），但不会做大规模回补。盘中重复采集由 upsert 幂等保证不重复。


## 13. QA 行为

现有 `search_market_evidence`：

- 支持 `category="news"`。
- 在 `backend/graph/prompts.py` 的 `SYSTEM_PROMPT` 中补充：涉及"新闻、快讯、财联社、市场消息、基金资讯"时，优先在 `search_market_evidence` 中查 `category="news"` 证据。

新增 `search_cls_telegraph`：

- 参数：`keyword`、`category`、`limit`。
- 返回：`count`、`items`、`error`。
- 每条 item 包含 `title`、`summary`、`published_at`、`source`、`source_url`、`symbols`、`metrics`。

使用规则：

- 用户问"今天有什么重要市场消息"时，优先查本地 `market_evidence(category="news")`。
- 用户明确要求"最新/实时/财联社"时，调用 `search_cls_telegraph`。
- 回答不直接复述长文，只总结要点并附来源链接。
- 避免引用过多快讯导致"交易建议"倾向——prompt 应控制"事实整理"而非"结论推断"。

> Prompt 更新位置：`backend/graph/prompts.py` → `SYSTEM_PROMPT` 第 8 条（工具使用约定）区域。

## 14. 测试策略

单元测试：

- `sign_params` 使用固定参数验证签名结果。
- `normalize_telegraph_item` 覆盖：
  - 正常标题。
  - `title` 为空。
  - `brief/content` 含 HTML 或 `<em>`。
  - `stock_list` 和 `subjects` 提取。
  - `summary` 截断。

Adapter 测试：

- mock client 返回财联社列表 JSON。
- 确认输出符合 `market_evidence` 契约。
- 确认分类失败时返回其他分类结果。
- 确认异常时返回 `[]`。

Ingestion 测试：

- `category=news` 可以 upsert。
- 同一 `source_url` 重复采集不重复写入。
- 缺关键字段的行被跳过并记录错误。

Service/tool 测试：

- mock 搜索接口返回 JSON，确认 `keyword/category/limit` 生效。
- 搜索失败返回 `items=[]` 和错误信息。

配置测试：

- `CLS_ENABLED=false` 时 `build_default_adapters(post_market)` 不包含 `ClsTelegraphAdapter`。
- `pre_market` 不包含 `ClsTelegraphAdapter`。
- `post_market` 且配置开启时包含 `ClsTelegraphAdapter`。

## 15. 验收标准

- 手动触发 `post_market` evidence 后，`market_evidence` 中出现 `source="财联社"`、`category="news"` 的记录。
- 重复触发不会重复插入同一 `source_url`。
- QA 可以通过本地 `search_market_evidence(category="news")` 找到财联社证据。
- QA 可以在用户明确要求实时财联社搜索时调用 `search_cls_telegraph`。
- 财联社网络失败时，现有 market evidence 采集仍完成。
- 测试覆盖签名、规范化、adapter、ingestion、tool 和配置分支。

## 16. 风险

- 财联社前端接口、签名或版本号可能变化。
- WAF 策略可能收紧，导致请求失败。
- 新闻内容版权边界需要持续遵守，只保存短摘要和链接。
- `news` 类证据增加后，简报可能引用过多快讯，需要 prompt 控制“事实整理”而不是“交易建议”。

## 17. 后续扩展

可以在第一版稳定后再做：

- 盘中低频快讯采集任务。
- 详情页按需补全。
- 前端 evidence/news 筛选视图。
- 搜索结果选择性入库。
- `cls_news` 专表和全文索引。
- 更细的 `news` 子分类筛选。
