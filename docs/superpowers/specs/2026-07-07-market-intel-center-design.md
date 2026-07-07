# 市场情报中心设计

> 日期：2026-07-07
> 负责人：fund-agent 系统规划

## 1. 背景

fund-agent 目前已有：

- **每日简报 Wave 3.3**：指数 + 市场宽度（涨跌家数/涨停跌停） + 板块快照 + 自选池涨跌，风险提示、操作观察
- **Phase A 市场情报 spec**（`2026-07-07-market-briefing-intelligence-design.md`）：规划了盘前/早盘/收盘简报、市场情报采集、evidence 存储、LangGraph 工具

差距在于：

- 每日简报的板块数据仅来自 THS 行业快照，缺少**概念板块**、**板块资金流向**、**热门题材**、**情绪指标**（连板高度/炸板率）
- 没有独立**市场情报页**，用户无法主动浏览历史市场数据、筛选时间范围
- 没有**外围市场**参考（美股/港股/原油/汇率）
- **公告列表**为 stub，未接入真实数据

本 spec 在 Wave 3.3 的基础上扩展，同时满足以下两个目标：

- **目标 A**：把 Phase A+ 扩入每日简报（概念板块 + 板块资金流向）
- **目标 B**：新建 `/market` 市场情报页（独立浏览 + 时间筛选 + 一键刷新）

---

## 2. 目标

### 目标 A：每日简报升级（Phase A++）

在现有简报基础上新增：

| 新增数据 | 数据源 |
|---------|--------|
| 概念板块涨跌幅 top/bottom | `akshare.stock_board_concept_spot_em()` |
| 行业板块资金流向（净流入 top/bottom） | `akshare.stock_board_industry_spot_em()`（含净流入列） |
| 概念板块资金流向（净流入 top/bottom） | `akshare.stock_board_concept_summary_ths()` |

简报 prompt 扩展输出 sections：

```
1. 指数表现（已有）
2. 赚钱效应（已有）
3. 板块动向（行业 top3/bottom3）
4. 概念板块动向（新增：概念 top3/bottom3）
5. 板块资金流向（新增：行业净流入 top3/bottom3）
6. 自选池涨跌（已有）
7. 风险提示（已有）
8. 操作观察（已有）
9. 数据声明（已有）
```

禁止内容不变（无投资建议/无涨跌预测）。

### 目标 B：独立市场情报页 `/market`

路由：`frontend/app/market/page.tsx`

#### 2.1 页面结构

```
/market
├── 时间范围筛选器（今日 / 昨日 / 本周 / 本月 / 近1月 / 自定义）
├── 市场概览卡片组
│   ├── 主要指数（复用 NavChart/MetricCard 组件）
│   ├── 赚钱效应（上涨/下跌/涨停/跌停/成交额）
│   └── 情绪指标（炸板率、连板高度）
├── 行业板块
│   ├── 涨跌幅排名表（全行业按涨跌幅降序）
│   └── 资金流向表（行业净流入 top/bottom）
├── 概念板块
│   ├── 涨跌幅排名表（概念按涨跌幅降序）
│   └── 资金流向表（概念净流入 top/bottom）
├── 热门题材（连板高度 top 标的 + 涨停原因归类）
├── 外围市场（美股/港股/原油/汇率参考）
├── 重要公告（按基金关联展示）
└── 一键刷新按钮
```

#### 2.2 数据窗口语义

| 简报类型 | 生成时间 | 数据范围 | 描述重点 |
|---------|---------|---------|---------|
| `morning` | 09:30-11:30 | 当日上午实时 | 早盘资金流向、强势板块 |
| `post_market` | 15:30-18:00 | 全天行情 | 收盘总结、连板/炸板统计 |

用户切换时间范围时，前端请求 `/api/market/snapshot?type=morning&date=YYYY-MM-DD`，后端返回对应日期的结构化快照（见第 3 节数据模型）。

---

## 3. 数据模型

### 3.1 新增 ORM 模型

```python
# backend/db/models.py

class MarketSnapshot(Base):
    """市场快照：按交易日 + 类型（morning/post_market）存储当日市场全量快照。"""
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(10))  # "2026-07-07"
    snapshot_type: Mapped[str] = mapped_column(String(16))  # "morning" | "post_market"
    indices_json: Mapped[str] = mapped_column(Text)       # JSON: [index_rows]
    breadth_json: Mapped[str] = mapped_column(Text)        # JSON: breadth dict
    industry_sectors_json: Mapped[str] = mapped_column(Text)   # JSON: [sector_rows]
    concept_sectors_json: Mapped[str] = mapped_column(Text)    # JSON: [sector_rows]
    industry_flows_json: Mapped[str] = mapped_column(Text)     # JSON: [flow_rows]
    concept_flows_json: Mapped[str] = mapped_column(Text)      # JSON: [flow_rows]
    themes_json: Mapped[str] = mapped_column(Text)             # JSON: [theme_rows]
    breadth_indicators_json: Mapped[str] = mapped_column(Text) # JSON: {board_height, rejection_rate}
    overseas_json: Mapped[str] = mapped_column(Text)           # JSON: overseas markets
    announcements_json: Mapped[str] = mapped_column(Text)      # JSON: [announcement_rows]
    source: Mapped[str] = mapped_column(String(32), default="akshare")
    as_of: Mapped[str] = mapped_column(String(10))           # 快照生成时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("trade_date", "snapshot_type"),
    )
```

### 3.2 现有模型兼容

- `Briefing`：简报 markdown 中嵌入 market_snapshot（兼容 Phase A+）
- `MarketData`：指数数据继续用（供 `/market/latest` 快速读取）
- 不新增 `market_evidence` 表（Phase B/C 才需要，v1 先不做）

---

## 4. API 设计

### 4.1 新增路由

#### `GET /api/market/snapshot`

获取指定交易日/类型的市场快照。

**Query 参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `date` | string | 今天 | 交易日，格式 YYYY-MM-DD |
| `type` | string | "post_market" | "morning" 或 "post_market" |

**响应**：

```json
{
  "trade_date": "2026-07-07",
  "snapshot_type": "post_market",
  "indices": [...],
  "breadth": {"up": 669, "down": 4494, ...},
  "industry_sectors": [...],
  "concept_sectors": [...],
  "industry_flows": [...],
  "concept_flows": [...],
  "themes": [...],
  "breadth_indicators": {"board_height": "...", "rejection_rate": "..."},
  "overseas": [...],
  "announcements": [...],
  "source": "akshare",
  "as_of": "2026-07-07"
}
```

**降级**：快照不存在时自动采集（morning 09:30 后 / post_market 15:30 后），返回实时数据；否则返回 404。

#### `GET /api/market/latest`

返回今日已缓存的市场概览（快速读取，不触发采集）。

#### `POST /api/market/refresh`

手动触发一次市场数据采集（需 `X-Local-Trigger` header），立即采集并写 `MarketSnapshot`。

返回：`{"status": "started", "job_id": "..."}`，异步执行。

#### `GET /api/market/sectors`

返回行业/概念板块数据（带可选 `type=industry|concept&sort=change_pct|flow&limit=10` 筛选）。

### 4.2 修改现有路由

- `GET /api/briefing/latest`：返回的 `briefing.markdown` 已是 Phase A++ 版本（7 sections + 新数据）
- `POST /api/briefing/run`：compose 时已传入完整的 market_breadth + sector_snapshot + concept_snapshot

---

## 5. 数据采集（后端服务层）

### 5.1 新增 `market_intel_service.py`

```
backend/services/market_intel_service.py
```

#### 5.1.1 数据源确认

| 所需数据 | akshare 函数 | 数据窗口 |
|---------|-------------|---------|
| 行业板块涨跌幅 | `akshare.stock_board_industry_summary_ths()` | 实时 |
| 概念板块涨跌幅 | `akshare.stock_board_concept_spot_em()` | 实时 |
| 行业板块资金流向 | `akshare.stock_board_industry_summary_ths()`（含净流入列） | 实时 |
| 概念板块资金流向 | `akshare.stock_board_concept_summary_ths()` | 实时 |
| 涨停板归类（题材） | `akshare.stock_zt_pool_em()` | 收盘后 |
| 炸板率 | `akshare.stock_zt_pool_em()` 计算 | 收盘后 |
| 连板高度 | `akshare.stock_zt_pool_strong_ths()` | 收盘后 |
| 外围市场 | `akshare.index_global_hist_sina()`（美股指数）、`akshare.stock_hk_index_daily_sina()`（港股） | 盘后 |
| 原油 | `akshare.futures_oil_crude()` | 实时 |
| 公告 | `akshare.stock_announcement_em()`（按基金代码过滤） | 日更 |
| 北向资金 | `akshare.stock_hsgt_north_net_flow_in_em()` | 日更（收盘后） |

#### 5.1.2 服务函数

```python
# backend/services/market_intel_service.py

def collect_market_intel(trade_date: str, snapshot_type: str) -> dict:
    """编排: 采集全量市场情报，upsert MarketSnapshot，返回快照 dict。
    
    采集顺序（可并行）：
    1. 指数（复用 market_service.get_indices）
    2. 市场宽度（复用 data_collector.fetch_market_breadth）
    3. 行业板块（涨跌 + 资金流向）
    4. 概念板块（涨跌 + 资金流向）
    5. 情绪指标（涨停池、连板、炸板率）
    6. 外围市场（美股/港股/原油/汇率）
    7. 重要公告
    
    单项失败不影响整体，记录 errors，降级展示。
    """
    ...

def get_market_snapshot(trade_date: str, snapshot_type: str, session=None) -> dict:
    """从 DB 读取 MarketSnapshot；不存在则触发采集。"""
    ...

def refresh_market_intel_async(trigger: str = "manual") -> dict:
    """后台线程采集，API 触发用。"""
    ...
```

#### 5.1.3 数据新鲜度策略

- `morning` 快照：09:30 之后才可采集（scheduler 09:35 触发）；采集时涨停池可能为空，提示"数据待更新"
- `post_market` 快照：15:30 之后采集（scheduler 15:35 触发）；此时涨停池数据完整
- 用户主动刷新：直接采集最新数据，不写 DB，返回实时 dict

### 5.2 更新 `data_collector.py`

新增函数：

```python
def fetch_concept_sectors() -> list[dict]:
    """拉取概念板块涨跌幅 top/bottom。"""
    # akshare.stock_board_concept_spot_em()

def fetch_concept_flows() -> list[dict]:
    """拉取概念板块资金流向 top/bottom。"""
    # akshare.stock_board_concept_summary_ths()

def fetch_industry_flows() -> list[dict]:
    """拉取行业板块资金流向 top/bottom。"""
    # 从 stock_board_industry_summary_ths() 提取净流入列

def fetch_theme_boards() -> list[dict]:
    """拉取当日涨停板归类（题材）。"""
    # akshare.stock_zt_pool_em() 过滤涨停板，按涨停原因归类

def fetch_breadth_indicators() -> dict:
    """拉取情绪指标：连板高度、炸板率。"""
    # akshare.stock_zt_pool_strong_ths() + 炸板率计算

def fetch_overseas_markets() -> list[dict]:
    """拉取外围市场：美股主要指数、港股、原油、汇率。"""
    # akshare.index_global_hist_sina() + akshare.futures_oil_crude()

def fetch_announcements(limit: int = 50) -> list[dict]:
    """拉取近 N 天重要公告。"""
    # akshare.stock_announcement_em()，返回关联基金代码、标题、日期
```

### 5.3 更新 scheduler

```python
# backend/scheduler.py

# 新增两个 job
sched.add_job(
    collect_market_intel, "cron", hour=9, minute=35,
    args=["today", "morning"], id="morning_market_intel",
    max_instances=1, coalesce=True,
    misfire_grace_time=3600,
)

sched.add_job(
    collect_market_intel, "cron", hour=15, minute=35,
    args=["today", "post_market"], id="post_market_market_intel",
    max_instances=1, coalesce=True,
    misfire_grace_time=3600,
)
```

---

## 6. 前端设计

### 6.1 新增页面

**路由**：`/market`

**文件**：`frontend/app/market/page.tsx`

**组件**：`frontend/src/components/market/` 目录下：

```
market/
├── MarketOverviewCards.tsx    # 指数 + 赚钱效应 + 情绪指标卡片组
├── IndustrySectorTable.tsx    # 行业板块涨跌幅 + 资金流向表
├── ConceptSectorTable.tsx     # 概念板块涨跌幅 + 资金流向表
├── ThemeBoards.tsx            # 热门题材（涨停归类）
├── OverseasMarkets.tsx        # 外围市场参考
├── AnnouncementList.tsx       # 重要公告列表
└── SnapshotRefreshButton.tsx  # 一键刷新
```

**共享组件复用**：

- `MetricCard`：指数卡片复用
- `StateBlock`：加载/空状态复用
- `NavChart`：指数历史走势复用

### 6.2 API 交互

```typescript
// frontend/src/lib/market.ts（新增）

export function useMarketSnapshot(date: string, type: string) {
  // GET /api/market/snapshot?date=...&type=...
  // 缓存：staleTime 5min
}

export function useMarketSectors(type: 'industry' | 'concept', sort: 'change_pct' | 'flow', limit: number) {
  // GET /api/market/sectors?type=...&sort=...&limit=...
}

export function useRefreshMarket() {
  // POST /api/market/refresh（需 X-Local-Trigger）
  // 返回 job_id，前端轮询状态
}
```

### 6.3 导航入口

在 `AppShell.tsx` nav 中新增：

```tsx
<NavLink href="/market" icon={<TrendingUp />}>
  市场情报
</NavLink>
```

---

## 7. LangGraph 集成（可选，Phase B）

Phase B 才接入 LangGraph 工具：

```
get_market_briefing(trade_date?: string, type?: "morning" | "post_market")
refresh_market_intel()
search_announcements(fund_code: string, keywords?: string)
```

QA 机器人可以回答"今天市场主线是什么"、"哪些板块有资金流入"、"某基金的最新公告"。

Phase B 不在本 spec 范围内。

---

## 8. 实施范围（v1）

### 包含

- 目标 A：每日简报升级（行业 + 概念板块 + 资金流向）
- 目标 B：市场情报页（除公告外的全功能）
- `MarketSnapshot` ORM + `market_intel_service`
- `data_collector` 新增 6 个采集函数
- `market_intel_service.collect_market_intel()` 编排
- 新增 `/api/market/snapshot`、`/api/market/sectors`、`/api/market/refresh` 路由
- 更新 scheduler（morning/post_market 两个 job）
- `/market` 前端页 + 组件
- nav 入口
- 单元测试 + E2E 验证

### 不包含

- 公告 RAG（公告接入只做 API 列表，RAG Phase B 再说）
- LangGraph 工具（Phase B）
- `market_evidence` 表（Phase C）
- 盘前/早盘/收盘三类简报生成逻辑分离（统一用 `collect_market_intel` + 前端筛选）
- 用户偏好记忆（Wave 2）
- 多用户支持

---

## 9. 测试策略

### 单元测试

- `test_data_collector.py`：mock akshare 返回 DataFrame，验证解析逻辑
- `test_market_intel_service.py`：
  - `test_collect_market_intel_all_fields_present`
  - `test_collect_market_intel_partial_failure_continues`
  - `test_market_snapshot_upsert_idempotent`
  - `test_get_market_snapshot_falls_back_to_collection`

### 集成测试

- `test_market_intel_route.py`：验证 API 响应结构、状态码、降级逻辑

### E2E

- 手动跑一次 `collect_market_intel`，验证所有数据字段非空（除"数据待更新"场景）
- 浏览器打开 `/market` 页面截图验证

---

## 10. 非功能约束

| 约束 | 说明 |
|------|------|
| 数据延迟 | akshare 为免费接口，存在分钟级延迟；简报注明 `as_of` |
| 非交易日 | `stock_market_activity_legu` 返回上一个交易日数据；morning/post_market job 应跳过非交易日 |
| 采集超时 | 单个 akshare 接口超时 5s，超时记 error，降级展示 |
| 并发安全 | scheduler `max_instances=1` 防重复采集 |
| 隐私 | 公告接口不传用户持仓数据，纯公开信息 |
