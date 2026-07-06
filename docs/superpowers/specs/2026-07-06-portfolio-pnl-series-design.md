# 持仓组合时间序列收益曲线设计

> 本 spec 规划一个新增能力：基于 `FundTransaction` + 历史 NAV 计算并展示
> 用户持仓组合每天的市值 / 投入 / 盈亏时间序列，配套前端曲线与基础统计。
> 目标是把现有的 "point-in-time" PnL（`/api/portfolio/pnl`）
> 升级成 "随时间演变的 PnL 曲线"。

## 1. 背景

当前项目已经具备：

- 单只基金当前时点的盈亏：`/api/portfolio/pnl` 返回基于最新 NAV 的 `invested / market_value / pnl_abs / pnl_pct`。
- 多只基金净值历史对比：`/api/portfolio/compare`（只画净值曲线，不算盈亏）。
- 自选池 / 持仓明细：`Watchlist` + `FundTransaction`（逐笔 buy）。

但缺一个最直观的"用户体验"维度：**我这笔投入每天值多少钱、累计盈亏多少**。
把这条曲线画出来，就能看到：

- 持仓建立后到现在的累计浮盈 / 浮亏走势。
- 不同基金各自对组合的贡献。
- 一次性大笔买入 vs 多次加仓的曲线对比。

roadmap 没明确列这个能力，但在「每日简报 + 风险扫描」之前是最有用的补全。

## 2. 目标

- 在后端新增一个只读的 "组合随时间演变的盈亏" 接口，可指定基金子集或全部 `is_holding=true` 行。
- 该接口基于 `FundTransaction`（含未来扩展的 sell）与本地日级 NAV，
  确定性计算每一日的 `invested_total / market_value_total / pnl_abs_total / pnl_pct_total`
  以及每只基金的明细。
- 前端新增组合盈亏曲线页面，复用现有 Recharts 样式。
- 数据全部确定性本地计算；不调 AkShare；不输出任何建议。

## 3. 范围

本阶段包含：

- 后端服务 `services/portfolio_history.py` 与函数 `calculate_pnl_series(fund_codes=None, start=None, end=None, session=None)`，返回每日 + 汇总 + 每只基金明细。
- 后端路由：`GET /api/portfolio/pnl-series?codes=&start=&end=`。
- 前端：组合盈亏曲线页 `app/portfolio/page.tsx`，附顶部 KPI 卡（投入 / 市值 / 累计盈亏 / 累计收益率）。
- 在自选池详情中加一个 "组合表现" 入口链接。
- 单元测试。

本阶段不包含：

- 真实减仓 / 分红：`FundTransaction.kind` 目前只支持 `"buy"`（已在模型注释里标注）。
  本阶段只按 buy 计算；如果未来加 sell，需要扩展 recompute。
  在此之前不要假装减仓被支持。
- 持仓外的 "关注基金" 不计入市值（在途待确认申购 `FundPendingBuy` 不进曲线，等到确认成 `FundTransaction` 才进）。
- 收益归因 / 风险分解（每只基金对组合盈亏贡献目前只算绝对金额占比，不做 Brinson 那一类）。
- 期货 / 衍生品 / 跨境结算（项目本地单用户，纯人民币公募基金口径）。
- 自动记账 / 报税对接。

## 4. 产品行为

用户打开 `/portfolio` 页面，看到：

- 顶部 4 张 KPI 卡：累计投入 / 当前市值 / 累计盈亏（元）/ 累计收益率（%）。
- 一张时间序列图，三条线：`invested_total`（已投入本金）、`market_value_total`（市值）、`cumulative_pnl_total`（累计盈亏）。
- 一张 "各基金贡献" 图：当前市值 / 累计盈亏按基金拆分（堆叠柱或纯色柱）。
- 一个时间区间切换（"近 1 月 / 近 3 月 / 近 6 月 / 近 1 年 / 全部"）。
- 一个自选基金子集切换（默认 = 全部 `is_holding=true`）。

详情页交互：

- 自选池每行（或 KPI 卡旁）有 "查看组合" 链接，跳到 `/portfolio?codes=<code>`，预选该基金。

## 5. 工程分析

### 5.1 复用现有能力

- `pnl_service.calculate_pnl(fund_codes=...)`：point-in-time 版本。新的 `calculate_pnl_series` 把这个时间轴拉长，依赖其 `_row_to_pnl_item` 的字段构造保持兼容。
- `metric_service.daily_returns` / `cumulative_return` 可以沿用，不重复实现。
- `Watchlist` + `FundTransaction` + `FundNav` 已经是真相源；不需要新表。
- `FundTransaction.kind` 当前为 `"buy"` 时同一 row 表示一次 buy 本金增加；shape 不变。

### 5.2 算法

**每日 `invested_total` 计算**：把每个基金的 buy 交易按日期排序，逐笔累加 `amount - fee`（`fee` 在数据上记账到 `amount`，沿用现有 `recalc_holding` 口径：fee 不从 amount 扣，等同外加成本）。

**每日 `market_value_total` 计算**：

- 每日每只基金的份额 `share`：把直到当天的 buy 交易金额除以当天 NAV，得到份额加总（一致性优先用累计净值 `accumulated_nav`，与现有 PnL 一致）。
- 当日市值：`share * 当日累计净值`。
- 若当日某基金无 NAV，按线性插值（视为缺失，前端 missing-data 标灰）或直接前向填充昨日 NAV，本阶段选**前向填充** + 显式打 `nav_filled_yesterday=True` 标记 —— 简单且对 UX 友好；空缺日仅指 NAV 表里完全找不到该基金 NAV 的情况，那一日整行跳过。

**累计盈亏**：每日 `market_value_total - invested_total`。
**累计收益率**：`累计盈亏 / invested_total`（当日无投入时为 0，不是 None；前向展示更直观）。

整体算法伪代码：

```
for nav_date in sorted(all_dates):
    invested_today = sum_over_funds(sum_tx_amount_until(nav_date))
    market_today = 0
    for fund in funds:
        share = sum(tx.amount / fund.nav_at(tx.tx_date) for tx in txs_of_fund_until(nav_date))
        # 当日 NAV 不存在 → 前向填充到最近一个 NAV
        nav_today = fund.nav_at_or_before(nav_date)
        if nav_today is None: skip this fund for this day
        market_today += share * nav_today
    pnl_today = market_today - invested_today
    record(nav_date=nav_date, invested=invested_today, market=market_today, pnl=pnl_today)
```

返回值：

```json
{
  "start": "2026-01-06",
  "end":   "2026-07-06",
  "as_of": "2026-07-06",
  "source": "akshare",
  "dates": [
    {"date": "2026-01-06", "invested": 1000.0, "market": 1000.0, "pnl": 0.0,
     "pnl_pct": 0.0, "missing_funds": []},
    ...
  ],
  "per_fund": [
    {"fund_code": "110011", "fund_name": "...",
     "invested": 1000.0, "current_share": 1000.0,
     "current_market_value": 1100.0, "current_pnl": 100.0}
  ],
  "summary": {
    "invested": 5000.0, "market_value": 5450.0,
    "pnl_abs": 450.0, "pnl_pct": 0.09,
    "daily_points": 180
  }
}
```

- `dates[*].missing_funds` 列出当日本该计入但 NAV 缺位的基金代码，让前端可以打标。

### 5.3 性能

- 自选基金几只到几十只，2-3 年的日级 NAV 数据在内存里完全没问题（一次性几 MB）。
- service 接口明确 `start/end`，默认 1 年窗口；超过窗口由前端显式选择。
- 不用 DB 预聚合（引入 schema 改动超出本阶段）。后续阶段如果有需要，可以加 `portfolio_pnl_snapshot` 日级缓存表。

## 6. 数据契约

不引入新表；只复用 `Watchlist` / `FundTransaction` / `FundNav`。

口径记录（写入 `_row_to_pnl_item` 注释中已有，本阶段不重写）：

- 市值：`holding_share * accumulated_nav`（沿用 `pnl_service` 既有口径）。
- 投入：`holding_share * cost_nav`（来自 `recalc_holding`）。
- 累计盈亏：`market_value - invested`。
- 累计收益率：`pnl_abs / invested`，投入为 0 当日填 0 而非 None。
- 不计入市值：`FundPendingBuy`、`is_focus=true && is_holding=false`、`is_holding=true` 但 share/cost 任一为空。

## 7. 接口

```http
GET /api/portfolio/pnl-series?codes=&start=&end=
```

- `codes`：逗号分隔。空 = 全部 `is_holding=true`。
- `start` / `end`：ISO YYYY-MM-DD。空 = 默认 1 年窗口（用 `end=今天, start=end-365 天`）。
- 默认周期：`_PERIOD_ROWS` 里的 `"1y"`；前端切换器 override。

返回结构如 §5.2 所示。

`pnl` point-in-time 接口保留不动（不破坏现有前端 / 数据契约）。

## 8. 前端设计

新增 `frontend/app/portfolio/page.tsx`：

- 用 React Query 拉 `pnl-series`，默认近 1 年。
- 顶部 4 个 KPI 卡（沿用现有 `<MetricCard>` 组件）。
- 时间序列线图：三条线 / 双 Y 轴。
- 各基金贡献：堆叠柱或条形。
- 区间切换按钮组。
- 空状态：未持仓 → StateBlock 提示 "尚未添加持仓，请在自选池标记 is_holding"。
- 加载 / 错误态用现有的 `StateBlock`。

入口：从 `/watchlist` KPI 卡顶部 "组合表现" 链接过来；在自选池每行右侧加 "查看组合" 链接跳转 `/portfolio?codes=...`。

## 9. 测试计划

后端：

- 单只基金多笔买入：买卖时刻投入正确跳升。
- 多只基金合并：单日 `invested_total` = 各基金当日累计投入之和。
- 前向填充：缺 NAV 日沿用前一日，未标红。
- 投入为 0 当日 pnl_pct 为 0。
- 空 watchlist：返回空 series 与 summary。
- 完全空数据：返回 404 / 200 + 显式提示（建议 200 + 明确 empty 字段）。
- API：`GET /pnl-series` 默认参数 / 指定 codes / 非法日期。

前端单元：

- 区间切换后 query key 变化，fetch 触发。
- 空数据 / loading / error 三态。
- KPI 卡正向 / 负向颜色（pnl 负数红，正数绿）。

验证：

```bash
.venv/bin/python -m pytest backend/tests -q
npm test
npx tsc --noEmit
npm run build
```

## 10. 验收标准

- `/portfolio` 页可访问，展示 KPI 卡 + 三线图 + 各基金贡献图。
- 区间切换、基金子集切换都触发正确的 query re-fetch。
- 缺数据 / 空持仓 / 全部 NAV 缺失 三种情况下页面不崩、有明确空态提示。
- 接口返回的 `invested / market / pnl` 三条线，单笔买入后 invested 出现阶跃。
- 所有测试和构建命令通过。

## 11. 假设与边界

- `FundTransaction.kind` 仅支持 `"buy"`，本阶段不引入 sell 业务路径。
- 用户首笔 buy 之前的日期不计入（"我没买时市值是 0" 才合理）。
- 等功能 1（定时刷新）落地后，本曲线才会反映最新数据；本阶段不依赖，仅要求接口在 NAV 更新时可重算。

## 12. Out of Scope

- 真实卖仓（含税 + 份额减少）+ 分红再投。
- 风险归因 / Brinson / 行业暴露贡献。
- 多币种 / 跨境结算。
- 自动报税 / 记账工具对接。
- 日级快照持久化（仅在内存 / 计算时聚合）。
