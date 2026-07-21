# 个人基金市场 Agent 助手 — 全局路线图

> 这是一份**轻量地图**：只列各阶段目标、依赖顺序、验收标准，不含实现细节。
> 每个阶段单独走一遍 `spec → plan → 实现 → 验证` 循环，做完一块再规划下一块。
> 施工图（详细实现计划）逐阶段绘制，不提前写死远期细节。
>
> **2026-07-21 更新**：原始六阶段规划已基本走完，本次更新把状态列同步到实际交付情况，
> 并在下方补充了六阶段之外已经完成的工作。阶段 5 的范围在实施中发生了转向，
> 详见该阶段说明。风险扫描（原阶段 6 的一部分）经讨论后明确暂缓，不在当前排期内。

## 项目定位

个人基金市场**信息助手**，以 **Agent 为主体**：Agent 负责理解问题、编排工具、汇总解释；
所有确定性能力（取净值、算指标、检索公告）封装为 Tool。Agent **不亲自计算、不编造数据、不给买卖建议、不接交易接口**。

## 技术选型（已定，随实施更新）

- 前端：Next.js / React，`@langchain/langgraph-sdk` / `useStream`
- 后端：Python，FastAPI / LangGraph Server
- Agent 框架：**LangChain**，编排用 **LangGraph**（QA Graph、简报 Graph）
- LLM：**DeepSeek**（`deepseek-chat`，OpenAI 兼容，经 `langchain-openai` 接入；key 走环境变量）
- 数据库：**PostgreSQL 16（唯一运行时数据库）**——SQLite 专用代码与降级路径已于
  `postgresql-only-runtime-cleanup` 移除
- 向量库：**PostgreSQL + pgvector**（未使用 Chroma/FAISS，与主数据库同库）
- 数据源：AKShare（净值/基础信息）+ 财联社电报（市场情报/知识库来源）；Tushare 仍未引入
- 定时任务：APScheduler

## 阶段总览

| 阶段 | 名称 | 依赖 | 状态 |
|------|------|------|------|
| 1 | 后端数据基础 + 薄 Agent 竖切片 | — | 已完成 |
| 2 | Next.js 前端基础页面 | 1 | 已完成 |
| 3 | LangChain Tools 全量封装 | 1 | 已完成 |
| 4 | LangGraph 问答流程 | 3 | 已完成 |
| 5 | RAG 公告系统 → 已转向为市场知识库 RAG | 3 | 已转向完成（原始范围未做，见下） |
| 6 | 每日简报 | 3,5 | 已完成 |
| 6b | 风险扫描（原阶段 6 的一部分） | 3,5 | 已暂缓（2026-07-21 讨论决定） |

六阶段之外，还完成了一批未在原始路线图中列出的功能与重构，见「六阶段之外的已完成工作」。

## 各阶段目标与验收

### 阶段 1：后端数据基础 + 薄 Agent 竖切片 —— 已完成
**目标**：确定性的基金数据基础设施，外加一个极薄 Agent 竖切片证明主链路通。
**验收**：
- 能增删改查自选基金池
- 能用 AKShare 拉真实净值并入库
- 指标计算（涨跌幅/阶段收益/最大回撤/波动率）单测全绿
- 薄 Agent 能就真实基金回答净值/回撤，并显示数据来源
- 不输出任何买卖建议
> 详见 `specs/2026-06-30-phase1-backend-foundation-design.md`。

### 阶段 2：Next.js 前端基础页面 —— 已完成
**目标**：首页、自选基金页、基金详情页、公告页的展示与基础 API 调用。
**验收**：能在浏览器查看自选池、净值曲线、阶段收益；前端不持有任何密钥、不直连数据库。
**实际交付**：`frontend/app` 下已有 `funds/[code]`、`watchlist`、`market`、`portfolio`、
`compare`、`briefing`、`qa`、`announcements` 等页面，超出原始验收范围。

### 阶段 3：LangChain Tools 全量封装 —— 已完成
**目标**：把方案中全部 Tools（自选池、基础信息、净值、指标、市场、公告、风险、日报查询）封装为标准 LangChain Tool。
**验收**：每个 Tool 输入输出结构化、可序列化、错误对 LLM 可读，并有单测。

### 阶段 4：LangGraph 问答流程 —— 已完成
**目标**：QA Graph —— 问题分类 → 选工具/RAG → 调用 → 生成回答 → 边界检查 → 流式返回。
**验收**：能就自选基金与市场问题给出带来源与日期的回答；流式中间状态可观测；边界检查拦截买卖建议类提问。

### 阶段 5：RAG 公告系统 —— 原始范围未做，已转向为市场知识库 RAG
**原目标**：公告获取 → 解析 → 切分 → embedding → 入向量库 → 检索 Tool → 摘要 Agent。
**实际情况**：`/api/announcements` 至今仍是占位实现，返回空列表并注明
"公告 RAG 检索将在阶段 5 接入"（见 `backend/api/routes/announcements.py`）——按原始定义，
这个阶段没有做。

取而代之的是范围更广、来源不同的
**基金自选池驱动的市场知识库**（`specs/2026-07-09-fund-watchlist-rag-knowledge-base-design.md`，
经 `2026-07-10`/`2026-07-13` 两次稳定化跟进）：以财联社电报 + `market_evidence` 为输入，
经 LLM 准入判断、标准化、主题打标后写入 pgvector，服务于简报证据召回与问答检索。
该 spec 明确将"基金真实重仓股穿透"和"泛财经新闻归档"列为非目标。
**如果仍需要原始定义的公告 RAG（交易所/基金公司公告），这是一块独立的待办，未被知识库工作覆盖。**

### 阶段 6：每日简报 —— 已完成
**目标**：简报 Graph + 定时任务 + 历史日报存储。
**验收**：每日自动生成简报，前端可展示，历史可查询。
> 详见 `specs/2026-07-09-daily-briefing-v2-design.md`；前端 Phase 2（摘要卡片/风险雷达卡片/
> 可折叠证据面板等展示层升级）在该 spec 中被标记为后续阶段，尚未做。

### 阶段 6b：风险扫描 —— 已暂缓
**原目标**：独立的风险扫描 Graph + 结构化风险评分/持久化 + 历史可查询，与每日简报并列。
**现状**：只有嵌在简报里的轻量 `risk_radar` 模块（`backend/services/briefing/modules.py`），
随简报一起生成，不单独持久化、不单独可查历史，检测范围是市场广度/板块退潮/自选池相关/数据缺口。
**决定**：2026-07-21 讨论后明确暂缓，不建独立的风险扫描服务；如未来重新排期，需重新走
spec → plan 流程。

## 六阶段之外的已完成工作

原始路线图只覆盖到"每日简报 + 风险扫描"，实际实施中还交付了以下未列入路线图的能力
（均有对应 spec，见 `docs/superpowers/specs/`）：

**产品功能**
- 基金诊断（`fund-diagnosis`）
- Portfolio 盈亏时间序列（`portfolio-pnl-series`）
- 定时刷新（`scheduled-refresh`）
- 市场简报情报 / 市场情报中心 / 市场页 UI 优化（`market-briefing-intelligence`、
  `market-intel-center`、`market-ui-optimization`）
- 财联社电报数据源接入（`cls-telegraph-source`）

**架构与技术债治理**（"hard cut" 系列重构，均为 spec → plan → 实现 → review 全流程）
- 事务边界与 repository 领域整理（`transaction-ownership`、`repository-domain-hard-cut`）
- PostgreSQL-only 运行时清理（移除 SQLite 降级路径）
- 简报领域、market-evidence 集成、scheduler、watchlist-drawer、qa-workbench 模块化拆分
- 前端 React Query 治理（查询键工厂、轮询策略统一，`react-query-governance`）

## 已知的悬而未决事项

- **前端类型治理（Phase 3B）**：LangGraph 事件类型仍是 `any`、API 错误类型仍是 `unknown`，
  在 `react-query-governance` 设计中被显式推迟。
- **原始定义的公告 RAG**：见阶段 5 说明，`/api/announcements` 仍是占位实现。
- **知识库多源扩展**：目前只吃财联社电报 + market_evidence；政策/宏观数据/公告等其他来源、
  用户反馈驱动的证据排序、基金真实持仓穿透均在原 spec 中列为 Phase 2+，未做。
- **风险扫描**：见阶段 6b，已暂缓。

## 合规边界（所有阶段适用）

系统是个人信息助手，不是投资顾问。只做公开信息整理、历史数据分析、风险提示、文档摘要。
不给买入/卖出/持有/加减仓/申购/赎回建议；不预测/承诺收益；不推荐基金组合；
不接任何交易接口；不调用支付宝；不自动下单。投资决策由用户本人完成。
