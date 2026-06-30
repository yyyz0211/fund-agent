# 第一阶段设计：后端数据基础 + 薄 Agent 竖切片

> 阶段 1 / 6。前置依赖：无。详见 `../roadmap.md`。
> 本阶段交付一个纯后端 Python 项目，不含前端、不含 Web 层。

## 1. 目标

1. 搭建确定性的基金数据基础设施（数据库、采集、入库、指标计算）。
2. 在末尾接一个**极薄的 Agent 竖切片**，验证「Agent 调 Tool 拿确定性结果」这条主链路。

**核心准则（Agent 为主体的落地）**：所有 service 层函数按「将来会变成一个 Tool」的标准编写——
结构化可序列化输出、带数据来源与时间、错误对 LLM 可读。Agent 只编排与解释，**绝不亲自计算或编造数据**。

## 2. 范围

**包含**：
- SQLite 数据库 + 四张表：`funds`、`watchlist`、`fund_nav`、`market_data`
- 自选基金池增删改查（纯函数，非 HTTP API）
- AKShare 采集：基金基础信息、最新净值、历史净值、市场指数
- 确定性指标计算：日涨跌幅、阶段收益（1周/1月/3月/6月/1年）、最大回撤、波动率
- 薄竖切片：`get_latest_fund_nav` + `calculate_fund_metrics` 封装为 LangChain Tool，
  接最小 `deepseek-chat` tool-calling agent
- 单元测试（指标计算 + 自选池，离线）

**不包含**（留后续阶段）：前端、FastAPI/Web 层、RAG/公告、多 Agent、LangGraph、定时任务、风险扫描、每日简报、Tushare。

## 3. 模块结构

```
fund-agent/backend/
├── config/
│   └── settings.py        # pydantic-settings，从 .env 读 DEEPSEEK_API_KEY 等
├── db/
│   ├── models.py          # 四张表 schema
│   ├── init_db.py         # 建库建表
│   └── repository.py      # 数据库读写（含 watchlist CRUD）
├── services/
│   ├── data_collector.py  # AKShare 采集 + 重试 + 来源留痕
│   ├── fund_service.py    # 基金信息/净值业务封装（tool-ready）
│   ├── market_service.py  # 市场指数（tool-ready）
│   └── metric_service.py  # 确定性指标计算（纯函数，可单测）
├── tools/
│   └── fund_tools.py      # 薄切片用的 2 个 LangChain @tool
├── agent/
│   └── thin_agent.py      # 最小 langchain tool-calling agent（deepseek-chat）
├── data/                  # fund_agent.db（gitignore）
├── scripts/
│   └── smoke_fetch.py     # 手动验证：真实拉一只基金数据
├── tests/
│   ├── test_metrics.py    # 指标单测（构造数据，离线）
│   └── test_repository.py # 自选池 CRUD 单测（临时 SQLite）
├── .env.example           # 仅键名占位，无真值
├── requirements.txt
└── README.md
```

## 4. tool-ready 接口约定

所有 service 返回函数遵守：
- 返回**结构化、可 JSON 序列化**结果（dataclass / dict），不返回裸 DataFrame
- 每条数据带 `source`（如 `"akshare"`）与 `as_of`（数据日期 / 抓取时间）
- 失败返回**对 LLM 可读的明确错误**，如 `{"error": "fund 110011 not found in source"}`，不抛裸异常、不返回 None
- `tools/fund_tools.py` 包装时几乎零转换，直接套 `@tool` 描述

## 5. 数据库表（第一阶段四张）

字段以方案文档为准，第一阶段建以下四张表：

**funds**：`fund_code`(PK)、`fund_name`、`fund_type`、`manager`、`company`、`inception_date`、`risk_level`、`created_at`、`updated_at`

**watchlist**：`id`(PK)、`fund_code`、`is_holding`、`is_focus`、`holding_amount`、`holding_share`、`cost_nav`、`buy_date`、`note`、`created_at`、`updated_at`

**fund_nav**：`id`(PK)、`fund_code`、`nav_date`、`unit_nav`、`accumulated_nav`、`daily_return`、`source`、`source_updated_at`、`created_at`；`(fund_code, nav_date)` 唯一

**market_data**：`id`(PK)、`market_date`、`symbol`、`name`、`category`、`close`、`change_pct`、`source`、`created_at`；`(symbol, market_date)` 唯一

## 6. 数据流

**确定性数据流（无 LLM）**：
```
add_fund_to_watchlist("110011")        # 写入 watchlist
  → data_collector 调 AKShare 取基础信息 + 历史净值（重试 + source/as_of）
  → 写入 funds / fund_nav
  → metric_service 读 fund_nav 算指标（纯函数）
  → 返回结构化 dict（带 source + as_of）
```

**薄 Agent 链路（有 LLM）**：
```
用户问 "110011 近一月回撤多少"
  → langchain tool-calling agent (deepseek-chat)
  → LLM 决定调用 calculate_fund_metrics(fund_code="110011", period="1m")
  → Tool 执行确定性计算，返回 {"max_drawdown": -0.083, "source": "akshare", "as_of": "2026-06-30"}
  → LLM 用自然语言解释 + 附数据来源/日期
```
数字由 Tool 算，LLM 只解释——这是「Agent 为主体但不碰计算」的落地。

## 7. 错误处理

- AKShare 失败 → `data_collector` 指数退避重试（最多 3 次），仍失败返回 `{"error": ..., "source": "akshare"}`，不抛裸异常
- 基金代码不存在 → service 返回明确 error dict，Agent 据此回复「未找到该基金」而非编造
- 未配 `DEEPSEEK_API_KEY` → 薄 Agent 启动时清晰报错；数据/指标层及其单测不受影响

## 8. LLM 接入

- DeepSeek 是 OpenAI 兼容 API，经 `langchain-openai` 的 `ChatOpenAI` 接入
- `base_url = https://api.deepseek.com`，`model = deepseek-chat`（V3，支持 function calling）
- **不可用 `deepseek-reasoner`（R1）**：当前不支持 tools，Agent 无法调用工具
- key 从环境变量 `DEEPSEEK_API_KEY` 读，仓库只放 `.env.example` 占位，`.env` 被 gitignore

## 9. 测试策略

- `test_metrics.py`：构造净值序列测指标（已知输入→已知输出），完全离线，本阶段质量核心
- `test_repository.py`：临时 SQLite 测自选池 CRUD
- AKShare 采集层不写联网单测；改提供 `scripts/smoke_fetch.py` 手动验证真实取数

## 10. 验收标准

1. 能增删改查自选基金池
2. 能用 AKShare 拉真实净值并入库
3. 指标计算单测全绿
4. 薄 Agent 能就真实基金回答净值/回撤，并显示数据来源
5. 系统不输出任何买卖建议（prompt 写死合规边界）

## 11. 第一阶段依赖

`langchain`、`langchain-openai`、`akshare`、`pandas`、`pydantic-settings`、`pytest`
（SQLite 用 Python 标准库 `sqlite3`，第一阶段不引入 ORM）
