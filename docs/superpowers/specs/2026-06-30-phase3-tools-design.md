# 第三阶段设计：LangChain Tools 全量封装（数据就绪域）

> 阶段 3 / 6。前置依赖：阶段一（数据基础 + 薄 Agent 竖切片，已完成）。详见 `../roadmap.md`。
> 本阶段把"数据已就绪"的能力封装为标准 LangChain Tool，凑齐「基金 + 市场 + 自选池」完整能力域。
> 公告 / RAG / 风险 / 日报相关 Tool 依赖阶段五、六的数据源，留到那些阶段封装。

## 1. 目标

把后端已有的确定性能力，按 tool-ready 标准封装为 LangChain Tool，使阶段四的问答 Graph
有完整的工具集可调用。本阶段不引入新数据源，只封装阶段一已落地的数据能力（+少量只读查询 service）。

## 2. 范围

**本阶段交付 11 个 Tool**：

已有（阶段一，2 个，不改动）：
- `get_latest_fund_nav`、`calculate_fund_metrics`

新增查询类（纯读本地库，7 个）：
- `get_watchlist`、`add_fund_to_watchlist`、`remove_fund_from_watchlist`、`update_fund_note`
- `get_fund_basic_info`、`get_fund_nav_history`、`get_market_indices`

新增刷新类（读写 + 联网，2 个）：
- `refresh_fund`、`refresh_market`

**不包含**（留后续阶段）：公告查询、RAG 检索、风险检测、日报生成/查询相关 Tool；行业行情；
HTTP/Web 层；LangGraph 问答编排。

## 3. 核心约定（延续阶段一）

- 所有 Tool 是 service 的**薄包装**：每个 Tool 对应一个 service 函数，Tool 内不写业务逻辑。
- 查询类 Tool **纯读**：只读本地库，不联网、不写库；本地无数据返回**对 LLM 可读的 error dict**，
  提示先调用对应的 refresh Tool。**读写分离**——联网抓取只发生在刷新类 Tool。
- 数据类返回带 `source` 与 `as_of`；自选池类是本地用户数据，不带 source/as_of。
- 失败返回 `{"error": "..."}`，不抛裸异常、不返回 None。
- 可选参数（`note` / `start_date` / `end_date`）用**空字符串默认值**而非 `None`，
  使 DeepSeek function calling 的 JSON Schema 更干净、更不易漏传或类型错误。

## 4. Tool 输入输出契约

**自选池类（包 repository，无 source/as_of）**
- `get_watchlist() -> list[dict]` — 自选池全部行；空时返回 `[]`
- `add_fund_to_watchlist(fund_code: str, note: str = "") -> dict` — 幂等，返回该行 dict
- `remove_fund_from_watchlist(fund_code: str) -> dict` — `{"removed": true/false}`
- `update_fund_note(fund_code: str, note: str) -> dict` — 返回更新后的行；不在池中 → `{"error": ...}`

**基金查询类（纯读本地库，带 source/as_of）**
- `get_fund_basic_info(fund_code: str) -> dict` — `{fund_code, fund_name, fund_type, manager, company, source, as_of}`；
  库中无 → `{"error": "本地无 <code> 基础信息，请先 refresh_fund"}`
- `get_fund_nav_history(fund_code: str, start_date: str = "", end_date: str = "") -> dict` —
  `{fund_code, navs: [{nav_date, accumulated_nav, daily_return}], count, source, as_of}`；
  日期空字符串=不限；无数据 → error

**市场类（纯读本地库，带 source/as_of）**
- `get_market_indices() -> dict` — `{indices: [{symbol, name, close, change_pct, market_date}], source, as_of}`；
  无数据 → `{"error": "本地无市场数据，请先 refresh_market"}`

**刷新类（读写，联网）**
- `refresh_fund(fund_code: str) -> dict` — 包现有 service，`{fund_code, navs_inserted, source, as_of}` 或 error
- `refresh_market() -> dict` — 包现有 service，`{inserted, source, as_of}` 或 error

## 5. 需新建的 service 方法（3 个）

所有 Tool 背后都对应一个 service 函数，保持「Tool 是薄包装」的一致性。

1. `fund_service.get_basic_info(fund_code, session=None) -> dict`
   - 读 `Fund` 表；返回基础信息 dict（带 source/as_of），无 → error dict

2. `fund_service.get_nav_history(fund_code, start_date="", end_date="", session=None) -> dict`
   - 读 `FundNav` 表，按 `nav_date` 升序；空字符串日期=不限，否则按字符串区间过滤
     （`nav_date` 为 `YYYY-MM-DD`，可直接字符串比较）
   - 返回 `{fund_code, navs: [{nav_date, accumulated_nav, daily_return}], count, source, as_of}`，无 → error

3. `market_service.get_indices(session=None) -> dict`
   - 读 `market_data` 表中最新一个 `market_date` 的全部指数行
   - 返回 `{indices: [...], source, as_of}`，无 → error

`refresh_fund` / `refresh_market` 已存在，不新建。

## 6. 文件结构（扩充为主，不新建目录）

```
backend/
├── services/
│   ├── fund_service.py     # 扩充：+ get_basic_info, get_nav_history
│   └── market_service.py   # 扩充：+ get_indices
├── tools/
│   ├── fund_tools.py       # 扩充：基金类 Tool + refresh_fund + ALL_TOOLS 聚合
│   ├── watchlist_tools.py  # 新建：4 个自选池 Tool
│   └── market_tools.py     # 新建：get_market_indices + refresh_market
└── tests/
    ├── test_fund_service.py   # 扩充：get_basic_info / get_nav_history
    ├── test_market_service.py # 新建：get_indices
    └── test_tools.py          # 扩充：覆盖全部 11 个 Tool
```

按 Tool 域拆三个文件（fund / watchlist / market），每文件单一职责。
`fund_tools.py` 暴露统一聚合 `ALL_TOOLS`（汇总三文件全部 Tool），供阶段四 Agent 引用。
阶段一的 `TOOLS`（2 个）保留以兼容现有薄 Agent，`ALL_TOOLS` 为新的全量入口。

## 7. 测试策略（延续阶段一，全离线）

- service 新方法：内存 SQLite + 构造数据，测区间过滤、无数据 error、最新批次筛选
- Tool：monkeypatch 背后 service，验证 Tool 正确转发参数与返回（不调 LLM、不联网）
- 不为 LLM 真实调用写自动化测试；薄 Agent 端到端仍靠 `smoke_fetch.py` 手动验证

## 8. 验收标准

1. 11 个 Tool 全部可被 `.invoke()` 调用并返回结构化结果
2. 新 service 方法单测全绿（区间过滤、无数据、最新批次）
3. `ALL_TOOLS` 聚合暴露 11 个 Tool、命名无冲突
4. 全量测试套件保持绿（阶段一 26 个 + 本阶段新增）
5. 查询 Tool 纯读、无数据返回可读 error；刷新 Tool 能补数据

## 9. 本阶段依赖

无新增依赖。沿用 `langchain` / `langchain-core` / `SQLAlchemy`（均已安装）。
