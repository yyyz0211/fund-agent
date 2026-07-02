# 基金体检与本地决策辅助设计

> 本 spec 规划一个新增阶段：基金体检与本地决策辅助。
> 目标是在现有基金详情页、FastAPI API、LangGraph QA 和本地数据缓存之上，输出可解释、可降级、可测试的基金体检结果。

## 1. 背景

当前项目已经具备：

- 本地基金基础信息、历史净值、最新净值、日涨跌幅。
- 阶段收益、累计收益、最大回撤、波动率等确定性指标。
- 自选池、持仓交易、PnL、基金对比页。
- LangGraph QA 流程和合规 policy。

外部建议中包含“基金代码解析 + 一句话结论”“风险灯系统”“同类基金对比”“基金避坑检测”“适配人群判断”等能力。这些能力和当前项目方向一致，但原始建议里的“买/不买/小仓位/定投建议”会突破既有合规边界。

本阶段采用“本地自用放宽”原则：允许输出本地辅助判断标签，但仍不代操作、不承诺收益、不预测未来净值、不接交易接口。

## 2. 目标

新增“基金体检”能力，把用户输入的基金代码或自然语言问题转成结构化辅助判断。

核心目标：

- 解析基金代码，例如 `110011`、`110011怎么样`、`这只基金能买吗`。
- 输出一句话结论和标签：`暂不碰`、`观察`、`小仓试验`、`候选`。
- 用红黄绿灰风险灯展示关键风险。
- 给出避坑提示、适配人群、同类候选。
- 在详情页展示体检卡片，并在 QA 中通过工具返回同样的结构化依据。

## 3. 范围

本阶段包含：

- 基金代码解析。
- 基于本地 summary / NAV / metrics 的确定性体检规则。
- 增强数据缓存：规模、同类分类/排名、持仓集中度、行业集中度、经理摘要。
- 诊断 API、同类候选 API、显式刷新增强数据 API。
- LangGraph tool 和 policy v2。
- 前端详情页体检卡片和同类候选入口。

本阶段不包含：

- 代用户买入、卖出、申购、赎回。
- 自动下单或连接支付宝、券商、基金交易平台。
- 具体仓位百分比、定投节奏、止盈止损点位。
- 收益承诺、净值预测、明日涨跌预测。
- 复杂组合持仓重合度。
- 涨跌原因强解释。
- 完整基金经理画像。

## 4. 产品行为

用户在基金详情页或 QA 中输入基金代码相关问题时，系统返回基金体检结果。

示例输入：

- `110011`
- `110011怎么样`
- `110011能买吗`
- `帮我体检一下 110011`
- `这只基金适合稳健型吗`

体检结果必须包含：

- `decision_label`：`暂不碰 | 观察 | 小仓试验 | 候选`
- `confidence`：`low | medium | high`
- `summary`：一句话结论
- `reasons`：最多 3 条核心理由
- `risk_lights`：红/黄/绿/灰风险灯
- `pitfalls`：避坑提示
- `suitable_for`：适合/不适合人群
- `peers`：3-5 只同类候选，缺失时为空列表。
- `missing_data`：缺失数据项
- `source` / `as_of`

`peers` 取数策略：

- 主路径：刷新 job 中调用 `fund_open_fund_rank_em` 按 `peer_category` 拉同类榜单，并把候选代码缓存到 `fund_profiles.peer_candidates_json`。
- 优先选本地已有净值缓存的基金，确保 `period_return / max_drawdown / volatility` 在前端能展示。
- GET `/peers` 只读本地缓存，不在请求线程里联网；取不到时返回 `[]`，前端展示"暂无同类候选，可先刷新体检数据"。

数据不足时仍返回 200 和低置信度结果，例如“数据不足，暂列观察”，并把缺失项写入 `missing_data`。

## 5. 工程分析

### 5.1 当前可直接复用的数据

- `fund_service.get_summary()`：基金详情页首屏聚合数据。
- `fund_service.get_metrics()`：阶段收益、累计收益、最大回撤、波动率。
- `fund_service.get_nav_history()`：历史净值和 `daily_return`。
- `portfolio/compare`：多基金历史净值对比能力。
- `ALL_TOOLS`：LangGraph 工具聚合入口。

### 5.2 当前缺口

当前本地库缺少以下增强字段：

- 基金规模。
- 同类排名和同类候选。
- Top10 持仓集中度。
- 行业集中度。
- 基金经理摘要。

这些数据可从 AkShare 候选接口补充，但稳定性不能假设。因此增强数据必须是可选缓存，缺失时诊断降级为灰灯，不能让详情页或 QA 整体失败。

### 5.3 性能约束

诊断 GET 接口优先读本地缓存，不在详情页首屏自动慢联网。

增强数据通过显式刷新接口写入本地缓存：

- 用户点击“刷新体检数据”。
- 后续可由日报/定时任务复用。

刷新链路使用后台 job，不在 FastAPI 请求线程里同步等待 AkShare：

- `POST /diagnosis/refresh` 只创建或复用刷新 job，并立即返回 `job_id/status`。
- 前端通过 status endpoint 轮询 job，刷新完成后 invalidate `fundDiagnosis`。
- 后端每只基金同一时间最多一个刷新 job，重复点击返回同一个 active job。
- AkShare 子任务使用有界线程池，默认 `max_workers=3`，避免一次性打满请求线程或上游接口。
- 单个 AkShare 源设置短超时，失败写入 `missing_data/raw_errors`，不阻塞其他源。
- profile 缓存设置 TTL，默认 24 小时；未过期时 `POST refresh` 可直接返回 `done`，避免重复刷新。
- 同类候选只在 refresh job 中联网抓取并缓存；诊断和 peers GET 接口不直接请求 AkShare。

## 6. 数据设计

新增轻量缓存表 `fund_profiles`，按 `fund_code` 一行保存增强诊断数据。

建议字段：

- `fund_code`：主键。
- `scale`：基金规模，单位亿元。
- `scale_date`：规模数据日期。
- `peer_category`：同类分类，例如股票型、混合型、债券型、指数型、QDII、FOF。
- `rank_total`：同类总数。
- `rank_position`：同类排名。
- `peer_candidates_json`：同类候选缓存，JSON 字符串，元素包含 `fund_code/fund_name/fund_type/rank_position`。
- `top10_holding_pct`：Top10 持仓合计占比。
- `top_industry_pct`：第一大行业占比。
- `manager_summary`：基金经理摘要。
- `source`：数据源。
- `as_of`：采集日期。
- `raw_errors`：增强数据采集失败摘要，可用 JSON 字符串。
- `created_at` / `updated_at`。

SQLite 仍使用现有 `init_db` 轻量补列/建表机制，不引入 Alembic。

刷新 job 状态使用进程内 job registry，不进入 SQLite schema。项目当前是本地单用户开发模式，进程重启后丢失 running job 可接受；下一次刷新会重新创建 job。

## 7. 数据源设计

AkShare 候选接口（v1 上线前需逐个跑通，跑不通的字段从 §6 schema 中删除）：

- 同类/排名：`fund_open_fund_rank_em`
- 规模：`fund_scale_change_em` 或 `fund_scale_open_sina`
- 持仓：`fund_portfolio_hold_em`
- 行业配置：`fund_portfolio_industry_allocation_em`
- 经理：`fund_manager_em`（不稳定，跑不通则降级为 `missing_data`）
- 评级：`fund_rating_all`（名称不稳定，v1 暂不接入，schema 也不建 `rating` 字段）

采集策略：

- 每个增强源单独 try/except。
- 单个源失败只记录 `missing_data` 或 `raw_errors`。
- 已成功字段正常写入缓存。
- 不因增强数据失败回滚基础 NAV 或 metrics。

## 8. 诊断规则

### 8.1 风险灯

风险灯 level：

- `red`：高风险。
- `yellow`：需要观察。
- `green`：相对健康。
- `gray`：缺数据。

v1 规则：

阈值按 `peer_category`（股票型 / 偏股混合 / 偏债混合 / 债券型 / 指数型 / QDII / FOF）分组。A 股偏股基金波动天然高于债基，统一阈值会导致绝大多数偏股基金掉到 `观察 / 暂不碰`，label 分布失真。

共用阈值（仅债券型 / 货基 / FOF）：

- 最大回撤：`<= -10%` 红，`<= -5%` 黄，否则绿。
- 年化波动率：`>= 12%` 红，`>= 7%` 黄，否则绿。
- 规模：缺失灰，`< 0.5 亿` 红，`< 2 亿` 黄，`>= 2 亿` 绿。

偏股 / 偏股混合 / 指数 / QDII 阈值：

- 最大回撤：`<= -30%` 红，`<= -18%` 黄，否则绿。
- 年化波动率：`>= 30%` 红，`>= 18%` 黄，否则绿。
- 近 1 月涨跌：`>= 20%` 或 `<= -15%` 红，`>= 10%` 或 `<= -8%` 黄，否则绿。

偏债混合阈值取偏股和纯债的中位数（v1 复用偏股阈值，避免再次细分）。

成立时间（所有分类共用）：

- 缺失灰，`< 1 年` 红，`< 3 年` 黄，`>= 3 年` 绿。

集中度（所有分类共用）：

- 持仓集中度：缺失灰，Top10 持仓 `> 60%` 红，`> 40%` 黄，否则绿。
- 行业集中度：缺失灰，第一大行业 `> 60%` 红，`> 40%` 黄，否则绿。

数据完整度：

- 缺 NAV 或 metrics 红。
- 缺增强数据灰，但**不**判为红。

注意：`gray` 等级不参与红黄判断，避免把"未知"误算成"红灯"。

### 8.2 标签规则

- `暂不碰`：任一**核心**风险灯红，或 NAV / metrics 缺失。
- `观察`：无核心红灯但存在 2 个以上黄灯，或增强数据缺失较多。
- `小仓试验`：核心指标可接受，但波动或回撤偏高，仅适合激进型。
- `候选`：核心风险灯绿为主，同类对比不落后，数据完整度高。

`小仓试验` 是本地风险标签，不输出具体仓位比例，不自动生成交易动作。

`choose_decision_label(lights, missing_data)` 必须显式把 `gray` 灯排除在"红/黄统计"之外。

### 8.3 置信度

- `high`：NAV、metrics、规模、同类数据齐全。
- `medium`：NAV 和 metrics 齐全，但增强数据部分缺失。
- `low`：核心数据不足，或诊断主要依赖缺失降级。

## 9. 后端接口

新增接口：

```http
GET /api/funds/{code}/diagnosis?period=1y
GET /api/funds/{code}/peers?limit=5&period=1y
POST /api/funds/{code}/diagnosis/refresh
GET /api/funds/{code}/diagnosis/refresh/{job_id}
```

`period` 沿用现有 metrics 支持集合：`1w | 1m | 3m | 6m | 1y`。

`limit` 范围：`1..10`。

`POST /{code}/diagnosis/refresh` 不在请求线程同步阻塞 AkShare。接口返回 refresh job：

```json
{
  "job_id": "110011-20260702-120000",
  "fund_code": "110011",
  "status": "started",
  "started_at": "2026-07-02T12:00:00",
  "finished_at": null,
  "missing_data": [],
  "error": null,
  "as_of": "2026-07-02"
}
```

`status` 取值：

- `started`：新建后台刷新任务。
- `running`：同基金已有任务正在运行，返回既有 job。
- `done`：缓存未过期或后台任务已完成。
- `failed`：刷新主流程异常；已成功写入的字段仍保留，错误写入 `error/raw_errors`。

一次性刷新全部 AkShare 接口可能耗时 5-15s，同步阻塞会拖慢请求线程；后台 job + 轮询能让详情页保持可交互。

诊断响应结构：

```json
{
  "fund_code": "110011",
  "decision_label": "观察",
  "confidence": "medium",
  "summary": "该基金核心数据可用，但存在回撤和增强数据缺失，建议先观察。",
  "reasons": ["近一年最大回撤处于观察区间", "增强数据尚未完整刷新"],
  "risk_lights": [
    {
      "key": "max_drawdown",
      "label": "最大回撤",
      "level": "yellow",
      "value": -0.18,
      "reason": "近一年最大回撤为 -18.00%",
      "source": "akshare",
      "as_of": "2026-07-02"
    }
  ],
  "pitfalls": [
    {
      "key": "profile_missing",
      "severity": "info",
      "title": "增强数据缺失",
      "detail": "规模、持仓或行业数据尚未刷新。",
      "source": "local",
      "as_of": "2026-07-02"
    }
  ],
  "suitable_for": {
    "fit": ["能接受中等波动的用户"],
    "avoid": ["低回撤要求较高的稳健型用户"]
  },
  "peers": [],
  "missing_data": ["scale", "holdings", "industry"],
  "source": "akshare",
  "as_of": "2026-07-02"
}
```

## 10. LangGraph 与 Policy v2

新增 LangGraph tool：

```python
diagnose_fund(fund_code: str, period: str = "1y") -> dict
```

Policy v2 放行诊断类问题：

- `能买吗`
- `怎么样`
- `适合我吗`
- `值得关注吗`
- `体检`
- `避坑`
- `风险`

继续拒绝：

- 代操作：`帮我买`、`帮我卖`、`申购`、`赎回`、`下单`。
- 明确交易指令：`现在买入`、`现在卖出`、`满仓`、`清仓`。
- 收益承诺/预测：`保证收益`、`下个月收益多少`、`明天涨跌`、`净值预测`。
- 止损/加仓指令：`我想止损`、`现在加仓`、`立刻清仓`。这类带行动倾向的句子不是诊断问题，由 policy 层先拒，避免模型绕过诊断工具直接给行动建议。

policy 优先级：

1. **拒答模式先于放行模式**：所有"代操作 / 明确交易 / 收益预测 / 止损加仓"关键词在 `check_question` 中先匹配，命中即拒绝，不放行到 `diagnose_fund` tool。
2. **放行只决定是否调用 tool**：放行后 LLM 调用 `diagnose_fund`，工具返回结构化 `decision_label/risk_lights/pitfalls`，后置 `check_answer` 仍然禁止"立刻买入""保证赚钱""一定涨"等确定性表述。
3. **带风险表达但不要求立即行动的问题走诊断**：例如 `110011 风险大吗`、`110011 回撤太大怎么办` 可以放行到诊断工具；`我想止损`、`现在加仓`、`立刻清仓` 属于行动意图，必须拒绝。

后置检查允许出现 `暂不碰`、`观察`、`小仓试验`、`候选`，但继续禁止"保证赚钱""一定涨""立刻买入"等确定性措辞。

## 11. 前端设计

基金详情页新增 "基金体检" 卡片，放在基础信息 / 最新净值之后、持仓盈亏卡之前。让用户进详情页先看到体检结论再看到自己的浮盈亏，避免先被自己持仓盈亏影响判断。

展示内容：

- 大号结论标签。
- 置信度。
- 一句话 summary。
- 3 条以内 reasons。
- 风险灯网格。
- 避坑列表。
- 适配人群。
- 缺失数据提示。
- 同类候选列表。
- “加入对比”跳转 `/compare?codes=主基金,候选1,候选2`。
- “刷新体检数据”按钮，调用显式刷新接口。

颜色规则：

- 红：高风险。
- 黄：观察。
- 绿：相对健康。
- 灰：无数据。

## 12. 测试计划

后端：

- 基金代码解析：纯代码、中文句子、无代码、多个代码。
- 诊断规则：红/黄/绿/灰边界、标签选择、置信度选择。
- 诊断服务：数据齐全、缺 NAV、缺 metrics、缺 profile、缺 peers。
- API：diagnosis、peers、diagnosis refresh happy path 和非法参数。
- Tools：`diagnose_fund` 转发 service，`ALL_TOOLS` 唯一集合更新。
- Policy：诊断类放行，代操作和预测类拒绝。
- QA Graph：fake model 验证诊断 tool call 不被后置误拦截。

前端：

- API client URL 测试。
- 风险灯颜色/标签映射纯函数测试。
- compare URL 生成测试。
- TypeScript 覆盖新增类型。
- 浏览器 smoke：有数据、缺增强数据、同类候选为空、刷新按钮。

验证命令：

```bash
.venv/bin/python -m pytest backend/tests -q
npm test
npx tsc --noEmit
npm run build
```

## 13. 验收标准

- 基金详情页能展示基金体检卡片（位置在基础信息/最新净值之后、持仓卡之前）。
- 缺增强数据时页面不崩，诊断显示灰灯和 `missing_data`。
- 点击“刷新体检数据”时页面不被 5-15s AkShare 调用阻塞；按钮进入 refreshing 状态，并通过 job status 轮询刷新结果。
- QA 输入 `110011能买吗` 能走诊断工具并返回带 source/as_of 的体检结果。
- QA 输入 `帮我买1000块110011` 仍拒绝。
- QA 输入 `110011 跌太多了我想止损` 仍拒绝，不进入诊断工具。
- 所有测试和构建命令通过。

## 14. 假设

- 实施前先收口当前每日涨跌幅工作树，避免体检改动和未提交改动混在一起。
- 本阶段是本地单用户辅助判断，不面向生产投资顾问场景。
- "小仓试验"只是本地风险标签，不是交易指令。
- AkShare 扩展数据不稳定时必须降级，不允许导致详情页整体失败。

## 15. Out of Scope（v1 不做）

明确把以下外部建议里的能力划入 v1 之后，避免到交付时被误追问：

- **持仓重合度分析**（用户多只基金重合度）：v1 只对单只基金体检，不做组合维度。
- **完整适配人群判断**：v1 只输出 `suitable_for.avoid` 兜底，不输出风险等级问卷。
- **涨跌原因强解释**：v1 不解释当日涨跌归因，由现有公告 + 市场指数兜底。
- **定投 / 分批建议**：v1 明确不输出仓位百分比、节奏、止盈止损点位。
- **自选基金组合体检**：v1 只对单只基金；"每周/月输出组合风险变化"不在本阶段。
- **基金经理完整画像**：v1 仅抓 `manager` + `manager_summary` 字符串，不做任期年限、历史业绩排行榜。
- **公开评级**：v1 不接入 `fund_rating_all`，schema 不建 `rating` 字段。

后续阶段如果重新激活任意一项，需要重新走 spec 评审。
