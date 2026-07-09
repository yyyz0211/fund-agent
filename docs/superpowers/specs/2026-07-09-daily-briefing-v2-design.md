# 每日简报 V2 设计

> 本 spec 规划把当前每日简报从“数据汇总型文章”升级为“市场状态 + 自选池影响 + 风险雷达 + 证据引用”的研究辅助简报。
> 第一阶段优先建立 brief type profile、module builder 和 final composer，保持现有 `Briefing` 表和 `/api/briefing/*` 接口兼容。

## 1. 背景

当前系统已经具备：

- 主要指数、市场宽度、行业板块、概念板块和资金流向采集。
- 自选池基金的 1 日、1 周、1 月收益率。
- `market_evidence` 证据层，包含政策、公告、宏观、财联社电报等来源。
- 每日简报生成服务：`collect_watchlist_snapshot -> compose_briefing -> upsert Briefing`。
- 简报数据质量字段：`data_quality`、`confidence`、`missing_data`、`evidence_count`。
- `/briefing` 前端页面，展示最新简报、数据质量、证据列表和历史简报。

现有问题：

- 输出偏“把数据列出来”，用户需要自己判断重点。
- 市场主线和自选池的关系不够明确。
- 风险提示偏泛，缺少结构化风险来源。
- 证据更多作为底部列表存在，没有嵌入关键判断。
- prompt 中存在“证据数据（财联社快讯）”这类来源写死表述，但实际 evidence 并不全来自财联社。
- 盘前、盘中、盘后简报目标混在一起，后续扩展成本较高。



## 2. 目标

每日简报 V2 的核心目标：

> 用 30-60 秒帮助用户理解今日市场状态、自选池受影响方向、关键风险和证据可信度。

具体目标：

- 结论前置：开头给出 30 秒摘要。
- 明确市场状态：偏强、偏弱、分化、退潮或数据不足。
- 提炼主线：从板块涨跌、概念涨跌和资金流中识别 1-2 条核心方向。
- 关联自选池：说明哪些自选基金可能与今日主线或弱势方向相关。
- 结构化风险：按市场、板块、自选池、数据四类输出风险雷达。
- 证据驱动：涉及新闻、政策、公告、宏观原因时必须引用 evidence。
- 类型分层：按 `brief_type` 选择模块组合，避免盘前、盘中、盘后共用一套臃肿正文。
- 保持合规：不输出买卖建议、仓位建议或未来涨跌预测。



## 3. 非目标

本阶段不做：

- 不做自动交易、买卖建议、加仓/减仓建议。
- 不做明日涨跌预测。
- 不做完整新闻流或财联社电报列表页。
- 不强行把所有 evidence 塞入正文。
- 不做真实基金持仓穿透。第一阶段只基于基金名称、备注和关键词做弱关联。
- 不重建 `Briefing` 表。
- 不破坏现有 `/api/briefing/latest`、`/api/briefing/list`、`/api/briefing/run`。
- Phase 1-4 不做用户反馈循环（Phase 5 再考虑）。



## 4. 简报类型与模块组合

V2 使用 `Brief Type Profile + Module Builder + Final Composer` 架构。

核心原则：

- `brief_type` 只负责决定“应该生成哪些模块”。
- 每个模块独立产出结构化 section。
- 最后由统一 composer 生成 markdown 和前端可渲染的 `sections`。
- 第一阶段可只实现 `post_market` profile，但模块接口需要支持后续扩展。



### 4.1 Brief Type Profile

每种简报类型定义一个 profile：

```json
{
  "brief_type": "post_market",
  "title": "盘后简报",
  "required_modules": [
    "quick_summary",
    "market_state",
    "themes_and_flows",
    "watchlist_impact",
    "risk_radar",
    "key_evidence",
    "data_statement"
  ],
  "optional_modules": [],
  "forbidden_modules": ["overnight", "intraday_anomaly"],
  "data_window": "trade_date_full_day",
  "max_markdown_words": 1000
}
```

字段说明：

- `required_modules`：该类型必须生成的模块。
- `optional_modules`：数据存在时才生成的模块。
- `forbidden_modules`：该类型不允许生成的模块，防止语义串场。
- `data_window`：采集和解释数据的时间窗口。
- `max_markdown_words`：控制最终 markdown 篇幅。



### 4.2 模块注册表

模块作为稳定的能力单元存在，由 profile 选择组合。

基础模块：

- `quick_summary`：30 秒摘要。
- `data_statement`：数据质量和免责声明。

市场模块：

- `market_state`：指数、宽度、赚钱效应。
- `themes_and_flows`：行业/概念强弱与资金。
- `overnight`：隔夜外围和盘前事件。
- `intraday_anomaly`：盘中异动、宽度背离、主题突变。

自选池模块：

- `watchlist_impact`：市场主线与自选池关联。

内部上下文：

- `theme_context`：供 `watchlist_impact` 使用的统一主题上下文。
  - `post_market` / `intraday`：主要来自 `themes_and_flows`。
  - `pre_market`：主要来自 `overnight`、盘前 evidence 和财联社电报。
  - 如果无法生成主题上下文，`watchlist_impact` 返回 `status=partial`，只展示自选池自身涨跌，不强行关联主题。

风险和证据模块：

- `risk_radar`：市场、板块、自选池、数据四类风险。
- `key_evidence`：支撑关键判断的证据列表。



### 4.3 `pre_market`

盘前简报，重点回答“今天开盘前需要观察什么”。

默认模块组合：

- `quick_summary`
- `overnight`
- `key_evidence`
- `watchlist_impact`
- `risk_radar`
- `data_statement`

不默认生成：

- `themes_and_flows`：盘前没有当日 A 股板块全量交易结果时不得强行复盘。
- `intraday_anomaly`：盘前没有盘中异动。

可选扩展（V2.1）：盘前事件日历（重要经济数据、季报公告、央行会议）可在 `overnight_module.events` 中展示。



### 4.4 `intraday`

盘中简报，重点回答“现在市场强弱和资金方向是什么”。

默认模块组合：

- `quick_summary`
- `market_state`
- `themes_and_flows`
- `intraday_anomaly`
- `watchlist_impact`
- `risk_radar`
- `data_statement`

不默认生成：

- `overnight`：盘中简报不回顾隔夜背景，除非 evidence 明确仍影响当日。
- 过长证据清单：只保留与异动相关的关键证据。



### 4.5 `post_market`

盘后简报，重点回答“今天市场发生了什么，以及自选池受到什么影响”。

默认模块组合：

- `quick_summary`
- `market_state`
- `themes_and_flows`
- `watchlist_impact`
- `risk_radar`
- `key_evidence`
- `data_statement`

不默认生成：

- `overnight`：盘后正文不把隔夜信息当成当天行情原因，除非 evidence 直接支撑。
- `intraday_anomaly`：第一阶段盘后不单独生成盘中异动模块，后续可作为 optional module。



## 5. 输出结构

每日简报 V2 不再要求所有类型固定输出同一套模块。实际输出由 `brief_type profile` 决定。

通用约束：

- 所有简报必须包含 `quick_summary` 和 `data_statement`。
- 其他模块按 profile 的 `required_modules` 和 `optional_modules` 生成。
- 模块缺少数据时不隐藏，而是返回 `status=missing` 或 `status=partial`，并说明原因。
- 第一阶段 `post_market` profile 默认输出下列 7 个模块，因此仍兼容原“7 段结构”的内容目标。



### 5.1 30 秒摘要

位置：正文最顶部。

必须包含：

- 市场状态：偏强 / 偏弱 / 分化 / 退潮 / 数据不足。
- 今日主线：最多 3 个；没有足够数据时可为 0 个，但必须说明数据不足。
- 主要风险：最多 3 个；没有足够风险信号时可为 0 个，但必须说明未识别到明确风险。
- 自选池影响：正向 / 负向 / 中性 / 分化 / 自选池为空。
- 置信度：高 / 中 / 低。

同时输出结构化字段，便于前端直接渲染 badge：

```json
{
  "market_state": "分化",
  "main_themes": ["AI 算力", "半导体"],
  "top_risks": ["市场宽度不足", "主线退潮风险"],
  "watchlist_impact": "mixed",
  "confidence": "medium"
}
```

字段说明：

- `market_state`：与正文文字对应的状态枚举。
- `main_themes`：当日最强主题列表。
- `top_risks`：最重要的 0-3 个风险信号。
- `watchlist_impact`：自选池整体受影响方向枚举（positive/negative/neutral/mixed/empty）。
- `confidence`：整体置信度，影响前端是否显示"数据不足"提示。

示例正文：

```text
今日市场偏分化，AI 算力和半导体仍是主要活跃方向，但市场宽度一般，说明赚钱效应未全面扩散。自选池中偏科技成长方向的基金更容易受到主线影响，医药和消费相关基金受当日主线带动较弱。当前证据主要来自行情和资讯来源，宏观证据不足，简报置信度为中。
```



### 5.2 市场状态

回答“今天市场整体是什么状态”。

输入：

- 指数涨跌。
- 上涨/下跌家数。
- 涨停/跌停数。
- 成交额。
- 行业和概念板块涨跌分布。

判断规则：

- 指数普涨且上涨家数占优：偏强。
- 指数上涨但下跌家数较多：指数强、宽度弱。
- 指数普跌且下跌家数占优：偏弱。
- 少数主题上涨、多数板块走弱：结构性分化。
- 宽度、板块、指数均缺失：数据不足。



### 5.3 主线与资金

回答“今天强在哪里，资金是否配合”。

输入：

- 行业领涨 top5、领跌 bottom5。
- 概念领涨 top5、领跌 bottom5。
- 行业资金净流入 top5、净流出 bottom5。
- 概念资金净流入 top5、净流出 bottom5。

输出重点：

- 涨幅强且资金流入：主线确认度较高。
- 涨幅强但资金流出：涨幅与资金信号冲突，谨慎表述。
- 资金流入但涨幅一般：只描述资金变化，不推断后续表现。
- 资金流全 0 或为空：不得输出资金流强判断。
- 概念数据为空：不得输出概念强弱判断。



### 5.4 自选池影响

回答“今天市场和我的基金有什么关系”。

输入：

- 自选池基金 1d / 1w / 1m 表现。
- 基金名称。
- 用户备注，如果已有。
- 市场主线。
- 行业/概念关键词。

第一阶段采用关键词弱映射：

```text
AI / 人工智能 / 算力 / 半导体 / 芯片 -> 科技成长
新能源 / 电池 / 光伏 / 储能 -> 新能源
医药 / 创新药 / 医疗 -> 医药
消费 / 白酒 / 食品 -> 消费
军工 -> 军工
港股 / 恒生 / 中概 -> 港股
```

> 建议：上述关键词映射应在代码中定义为常量或配置文件，便于后续维护和扩展。

输出分组：

- 正向关联：基金名称或备注与当日强势主题匹配。
- 负向关联：基金名称或备注与当日弱势主题匹配。
- 背离：基金短期表现与相关主题明显不一致。
- 中性：没有明确主题关联。

约束：

- 只能写“可能相关”“受主线影响更直接”“主题匹配”，不能写“确定受益”。
- 没有主题标签或关键词时，不强行关联。
- 自选池为空时，输出“自选池为空，无法生成自选池影响”。



### 5.5 风险雷达

替代泛泛的风险提示。

固定四类：

- 市场风险：宽度恶化、跌停增加、成交缩量、指数和宽度背离。
- 板块风险：高位主线退潮、领跌扩散、资金流和涨幅冲突。
- 自选池风险：单只基金明显跑输、主题集中度过高、短期波动放大。
- 数据风险：宏观、公告、政策、资金流或概念数据缺失。

每类最多 2 条。

**优先级字段**：每条风险增加 `level` 字段，区分紧急程度：

```json
{
  "market": [
    {
      "level": "high",
      "signal": "指数和宽度持续背离",
      "detail": "主要指数上涨但下跌家数持续高于上涨家数，宽度指标走弱"
    }
  ]
}
```

`level` 取值：

- `high`：需要立即关注，可能影响当日决策。
- `medium`：需要观察，暂不直接影响当日判断。
- `low`：提示性信号，值得留意但不必紧张。

前端可根据 `level` 决定风险卡片的视觉权重（如 high 用红色边框，medium 用橙色，low 用灰色）。

允许措辞：

- “需要观察”。
- “风险信号”。
- “数据不足，无法确认”。
- “该判断仅基于本地证据”。

禁止措辞：

- “建议规避”。
- “建议减仓”。
- “可以买入”。
- “明日大概率上涨/下跌”。



### 5.6 关键证据

证据需要支撑正文判断，而不是只作为底部列表。

正文引用原则：

- 涉及新闻原因，必须有 `category=news` 或来源为资讯类 evidence。
- 涉及政策原因，必须有 `category=policy`。
- 涉及公告原因，必须有 `category=announcement`。
- 涉及宏观原因，必须有 `category=macro`。
- 没有 evidence 时，只能写“行情数据显示”，不得写政策、公告、宏观原因。

**证据质量评分**：每条 evidence 增加以下字段，影响展示优先级：

- `freshness`：新鲜度评分（realtime/today/recent/older），基于 `published_at` 计算。realtime 和 today 证据优先展示。
- `weight`：可信度权重（high/medium/low），基于来源类型预设。政策原文和交易所公告权重高于转载资讯。

证据展示格式：

```text
来源：{evidence.source} 或按 category 动态展示（news/policy/announcement/macro）
标题：美股 AI 牛市熄火？通用算力板块出现调整
时间：2026-07-09 14:35（当日 | 高权重）
链接：source_url
```

### 5.7 数据质量声明

保留在末尾，但需要比当前更清晰。

必须包含：

- 行情数据日期 `as_of`。
- 简报生成日期。
- 证据数量。
- 缺失维度。
- `data_quality`。
- `confidence`。
- **各数据源最后更新时间** `data_sources_last_updated`：记录行情、财联社电报、公告等数据源的最后采集时间，便于用户判断数据延迟。
- 固定免责声明。

示例：

```text
数据质量：partial，置信度：medium。当前缺失：macro_evidence、announcement_evidence。行情来源为 akshare，证据来源包括资讯、公告、政策等 market_evidence。本简报为本地数据自动生成，不构成投资建议。
```



## 6. 数据输入



### 6.1 Market Snapshot

继续使用现有 snapshot 字段：

- `market_snapshot`
- `market_breadth`
- `industry_sectors`
- `industry_flows`
- `concept_sectors`
- `concept_flows`
- `sector_snapshot`
- `watchlist_changes`
- `errors`
- `collect_meta`



### 6.2 Evidence

继续使用 `market_evidence`，但 prompt 和 UI 必须按实际来源展示。

来源类型包括：

- 财联社电报。
- 公告。
- 政策页。
- 宏观数据。
- 本地表。
- 其他公开资讯源。

需要修正的表述：

```text
证据数据（market_evidence，包含财联社电报、公告、政策、宏观等来源）
```

替代当前容易误导的“证据数据（财联社快讯）”。

### 6.3 Watchlist Context

第一阶段可在服务层生成派生结构，不需要新增表。

建议结构：

```json
{
  "fund_code": "012345",
  "fund_name": "示例半导体主题基金",
  "period_returns": {
    "1d": 0.012,
    "1w": -0.005,
    "1m": 0.034
  },
  "theme_tags": ["科技成长", "半导体"],
  "impact_reason": "基金名称或备注包含半导体关键词"
}
```



### 6.4 Historical Context

V2.1 可加入历史对比，第一阶段只预留。

候选输入：

- 近 3 个交易日行业 top/bottom。
- 近 3 个交易日概念 top/bottom。
- 自选池近 5 日表现。
- 主线是否延续或切换（`trend` 字段）。

V2.1 需要实现 `trend` 判断时，需要传入历史 context，module builder 才能判断 `continuing/emerging/fading/new`。如果历史数据不可用，builder 应返回不带 `trend` 的输出。



## 7. 后端设计



### 7.1 服务分层

建议把当前简报生成拆成以下阶段：

```text
collect_briefing_context(brief_type, trade_date)
get_brief_type_profile(brief_type)
run_module_builders(context, profile)
run_quick_summary(context, profile, module_sections)
run_data_statement(context, profile, module_sections)
compose_briefing_v2(context, profile, module_sections)
upsert_briefing()
```

原则：

- 确定性判断尽量在后端完成。
- LLM 负责组织语言、压缩内容和引用证据。
- 不让 LLM 单独从原始 JSON 自由归因。
- `brief_type` 不直接写业务逻辑，而是通过 profile 选择模块。
- 单个模块失败不导致整篇简报失败，失败模块返回 `status=failed` 和 `warnings`。
- `data_statement` 必须最后生成，因为它需要汇总所有模块的 `status`、`warnings` 和 `missing_data`。



### 7.2 `BriefTypeProfile`

内部结构建议：

```json
{
  "brief_type": "post_market",
  "title": "盘后简报",
  "required_modules": [
    "quick_summary",
    "market_state",
    "themes_and_flows",
    "watchlist_impact",
    "risk_radar",
    "key_evidence",
    "data_statement"
  ],
  "optional_modules": [],
  "forbidden_modules": ["overnight", "intraday_anomaly"],
  "data_window": "trade_date_full_day",
  "max_markdown_words": 1000
}
```

实现要求：

- 未知 `brief_type` 默认回退到 `post_market`，同时写入 warning。
- profile 必须可单测，不依赖 LLM。
- profile 的 `required_modules` 顺序即前端默认渲染顺序。



### 7.3 模块输出协议

所有 module builder 返回统一 envelope：

```json
{
  "key": "market_state",
  "title": "市场状态",
  "status": "ready",
  "summary": "指数上涨但市场宽度一般，整体呈分化状态。",
  "content": {},
  "evidence_ids": [],
  "missing_data": [],
  "warnings": [],
  "confidence": "medium"
}
```

字段说明：

- `key`：模块唯一标识，与 module key 一致。
- `title`：前端展示标题。
- `status`：数据就绪状态。
- `summary`：模块核心结论，一句话概括。
- `content`：模块具体内容，结构由各 builder 定义（见各 builder 输出示例）。
- `evidence_ids`：引用的 evidence ID 列表。
- `missing_data`：本次缺失的数据维度。
- `warnings`：执行警告，不影响模块展示但需要用户注意。
- `confidence`：模块结论置信度。

**字段命名统一约定**：各 builder 的输出结构中，与核心结论相关的字段统一命名为 `summary`，具体数据统一放在 `content` 对象内，便于 final composer 和前端统一访问。

`status` 取值：

- `ready`：模块可正常展示。
- `partial`：模块可展示，但数据不完整。
- `missing`：关键数据缺失，模块只输出缺失说明。
- `failed`：模块执行失败，正文不使用该模块判断。



### 7.4 Module Builders

第一阶段建议实现以下 builders。

#### `quick_summary_module`

输入：

- profile。
- 已生成的其他 module sections。
- `data_quality`。

输出：

- 市场状态。
- 主线。
- 自选池影响。
- 主要风险。
- 置信度。

注意：该模块建议在其他模块之后执行，因为它需要聚合其他模块结果。

#### `market_state_module`

输入：

- `market_snapshot`
- `market_breadth`
- `industry_sectors`
- `concept_sectors`

输出：

```json
{
  "key": "market_state",
  "title": "市场状态",
  "status": "ready",
  "summary": "指数上涨但市场宽度一般，整体呈分化状态。",
  "content": {
    "state": "divergent",
    "label": "分化",
    "reasons": [
      "主要指数上涨，但下跌家数较多",
      "领涨集中在 AI 和半导体"
    ]
  },
  "evidence_ids": [],
  "missing_data": [],
  "warnings": [],
  "confidence": "medium"
}
```



#### `themes_and_flows_module`

输入：

- 行业涨跌。
- 概念涨跌。
- 行业资金流。
- 概念资金流。
- evidence 标题和标签。

输出：

```json
{
  "key": "themes_and_flows",
  "title": "主线与资金",
  "status": "partial",
  "summary": "AI 算力和半导体领涨，但概念资金流数据不完整。",
  "content": {
    "leading_themes": [
      {
        "name": "AI 算力",
        "evidence": ["concept_sector", "cls_telegraph"],
        "change_pct": 3.2,
        "net_flow": 12.5,
        "trend": "continuing",
        "confidence": "high"
      }
    ],
    "lagging_themes": []
  },
  "evidence_ids": [],
  "missing_data": ["concept_flows"],
  "warnings": ["概念资金流为空，未输出概念资金判断"],
  "confidence": "medium"
}
```

`trend` 取值：

- `continuing`：该主题近 3 日持续强势，主线地位延续。
- `emerging`：该主题今日首次出现在领涨位置，可能是新主线。
- `fading`：该主题今日从领涨跌至落后，强度减弱。
- `new`：该主题今日首次出现，信号强度待观察。

**跨日趋势信号**：如果历史上下文（近 3 日数据）可用，`themes_and_flows_module` 应判断每个主线的趋势方向。如果历史数据不可用，该字段可省略，frontend 不做展示。

规则：

- 概念数据为空时返回 `status=partial` 或 `missing`，不得输出概念强弱判断。
- 资金流全 0 或为空时返回资金流缺失 warning，不得写“资金明显流入”。
- 涨幅和资金冲突时只输出冲突事实，不给方向性结论。



#### `watchlist_impact_module`

输入：

- `watchlist_changes`
- 基金名称和备注。
- `theme_context`
  - `post_market` / `intraday` 来自 `themes_and_flows_module`。
  - `pre_market` 来自 `overnight_module` 和盘前 evidence。

输出：

```json
{
  "key": "watchlist_impact",
  "title": "自选池影响",
  "status": "ready",
  "summary": "自选池与今日科技成长主线呈分化关联。",
  "content": {
    "overall": "mixed",
    "positive": [
      {
        "fund_code": "012345",
        "fund_name": "示例半导体主题基金",
        "reason": "名称/备注匹配半导体主题，今日半导体板块走强"
      }
    ],
    "negative": [],
    "neutral": [],
    "divergent": []
  },
  "evidence_ids": [],
  "missing_data": [],
  "warnings": [],
  "confidence": "medium"
}
```

分类说明：

- `positive`：基金名称或备注与当日强势主题匹配。
- `negative`：基金名称或备注与当日弱势主题匹配。
- `neutral`：没有明确主题关联的基金。
- `divergent`：基金短期表现与相关主题明显不一致。



#### `risk_radar_module`

输入：

- 市场状态。
- 板块强弱。
- 资金流。
- 自选池表现。
- `missing_data`。

输出：

```json
{
  "key": "risk_radar",
  "title": "风险雷达",
  "status": "ready",
  "summary": "主要风险来自指数与市场宽度背离。",
  "content": {
    "market": [
      {
        "level": "high",
        "signal": "指数和宽度持续背离",
        "detail": "主要指数上涨但下跌家数持续高于上涨家数，宽度指标走弱"
      }
    ],
    "sector": [],
    "watchlist": [],
    "data": []
  },
  "evidence_ids": [],
  "missing_data": [],
  "warnings": [],
  "confidence": "medium"
}
```



#### `key_evidence_module`

输入：

- `market_evidence`。
- `themes_and_flows`。
- `risk_radar`。
- profile。

输出：

```json
{
  "key": "key_evidence",
  "title": "关键证据",
  "status": "ready",
  "summary": "本次简报使用 3 条关键证据支撑主要判断。",
  "content": {
    "items": [
      {
        "evidence_id": 123,
        "category": "news",
        "title": "美股 AI 牛市熄火？通用算力板块出现调整",
        "source": "财联社",
        "source_url": "https://www.cls.cn/detail/123",
        "published_at": "2026-07-09T14:35:00+08:00",
        "freshness": "today",
        "weight": "medium"
      }
    ]
  },
  "missing_data": [],
  "warnings": [],
  "confidence": "medium"
}
```



#### `data_statement_module`

输入：

- `as_of`。
- `briefing_date`。
- `data_quality`。
- `confidence`。
- `missing_data`。
- evidence count。
- 所有模块的 status（用于汇总失败模块）。
- `collect_meta`（用于提取各数据源最后更新时间）。

输出：

- 数据日期。
- 生成日期。
- 证据数量。
- 缺失维度。
- **失败模块汇总**：如果有任何内容模块返回 `status=failed`，在此列出并说明原因。
- 固定免责声明。

降级策略对用户透明要求：

- 模块失败时，`data_statement` 必须明确列出失败的模块名称和失败原因（如"L7M JSON 解析失败"、"数据采集超时"），而非只写 `status=failed` 状态码。
- 前端根据 `modules.data_statement.content.failed_modules` 渲染"该模块因数据原因未生成"提示，而不是直接折叠。
- 所有内容模块都失败时，简报仍可保存，`modules.data_statement.content.failed_modules` 列出全部失败模块，并在正文顶部添加"简报生成部分失败"警告。

输出示例中的 `data_sources_last_updated`：

```json
{
  "data_sources_last_updated": {
    "market_snapshot": "2026-07-09T15:30:00+08:00",
    "cls_telegraph": "2026-07-09T17:00:00+08:00",
    "announcements": "2026-07-09T16:45:00+08:00"
  }
}
```

前端展示时，如果某数据源更新时间早于当前时间超过一定阈值（如行情数据超过 30 分钟未更新），应显示"数据可能存在延迟"提示。



#### `overnight_module`

仅 `pre_market` 默认启用。

输入：

- 隔夜海外市场。
- 盘前政策、公告、宏观、财联社电报。
- **盘前事件日历**：今日重要经济数据发布、基金季报/公告、央行会议等。

第一阶段如果没有海外数据源，该模块返回 `status=missing`，不得由 LLM 编造外围市场。

**盘前事件日历**：如果市场 evidence 中有今日盘前事件，可在 `overnight_module` 的 `events` 字段中输出：

```json
{
  "events": [
    {
      "type": "economic_data",
      "time": "10:00",
      "name": "中国6月CPI/PPI",
      "impact": "high"
    },
    {
      "type": "fund_announcement",
      "name": "XX基金季报发布",
      "impact": "medium"
    },
    {
      "type": "central_bank",
      "name": "美联储官员讲话",
      "impact": "high"
    }
  ]
}
```

`impact` 取值：high/medium/low，用于前端决定事件卡片的视觉权重。如果没有事件数据，该字段可省略。

#### `intraday_anomaly_module`

仅 `intraday` 默认启用。

输入：

- 盘中指数。
- 市场宽度。
- 板块异动。
- 资金流。

第一阶段可先不实现；如果 profile 启用了但 builder 不存在，返回 `status=missing` 和 warning。

### 7.5 Module Runner

执行规则：

- 先执行除 `quick_summary` 和 `data_statement` 外的 profile modules。
- 再执行 `quick_summary_module`，用于汇总已完成内容模块。
- 最后执行 `data_statement_module`，用于汇总所有模块状态、失败原因、数据质量和免责声明。
- 每个模块独立 try/catch，失败时写入 module envelope。
- `forbidden_modules` 中的模块即使数据存在也不得生成。
- `optional_modules` 数据不足时可以跳过，但需要在 `data_statement` 中说明。

伪流程：

```text
profile = get_brief_type_profile(brief_type)
context = collect_briefing_context(brief_type, trade_date, profile.data_window)
sections = []
for module_key in profile.required_modules + profile.optional_modules:
    if module_key in ["quick_summary", "data_statement"]:
        continue
    if module_key in profile.forbidden_modules:
        continue
    sections.append(run_builder(module_key, context, profile))
sections.prepend(run_builder("quick_summary", context, profile, sections))
sections.append(run_builder("data_statement", context, profile, sections))
markdown = compose_briefing_v2(context, profile, sections)
upsert_briefing(markdown, sections)
```

约束检查顺序：`quick_summary/data_statement` 延后 → `forbidden_modules` 过滤 → 执行内容模块 → 生成 `quick_summary` → 生成 `data_statement`。



### 7.6 Prompt 输入

新的 prompt 不再只输入原始 `snapshot_json` 和 `evidence_json`，而是输入 profile、context 和模块结果：

```json
{
  "brief_type": "post_market",
  "profile": {
    "required_modules": ["quick_summary", "market_state", "themes_and_flows"],
    "max_markdown_words": 1000
  },
  "context": {},
  "module_sections": [],
  "evidence": [],
  "data_quality": {},
  "warnings": [],
  "missing_data": []
}
```

字段说明：

- `warnings`：本次生成过程中的执行警告。
- `missing_data`：本次缺失的数据维度列表。

LLM 负责：

- 按 profile 的模块顺序组织 markdown。
- 压缩冗余数据。
- 将关键判断与证据绑定。
- 不编造 evidence 中没有的政策、公告、宏观原因。
- 返回可解析 JSON，但 JSON 中只允许包含 `markdown` 和 `markdown_warnings`。

LLM 不负责：

- 决定 `brief_type` 应该有哪些模块。
- 生成 profile 中禁止的模块。
- 直接从原始 evidence 推断未被模块确认的结论。
- 修改、补充或删除 `module_sections`。
- 生成 `modules` 结构；`modules` 只来自后端 module builders。

LLM 输出格式：

```json
{
  "markdown": "...",
  "markdown_warnings": []
}
```

如果 LLM 返回了 `modules`、`sections` 或其他结构化事实字段，后端必须忽略这些字段，只使用 `markdown` 和 `markdown_warnings`。

**边界情况处理**：

- 所有内容模块都返回 `status=failed`：简报仍可保存，`sections_json.modules` 中保留失败模块 envelope，并在 `data_statement` 中添加"简报生成部分失败"警告。
- LLM 输出 JSON 解析失败：使用原始文本作为 `Briefing.markdown`，`sections_json` 仍保存后端 module builders 产出的结构化模块；记录 error 并写入 `sections_json.warnings`。
- `profile.required_modules` 与 `profile.forbidden_modules` 有交集：执行时按 `forbidden_modules` 优先，该模块不生成；代码层面应在 profile 定义时避免此冲突。



## 8. 输出 JSON Schema

建议最终保存到 `Briefing.sections_json` 的结构：

```json
{
  "brief_type": "post_market",
  "profile_version": "daily_briefing_v2_2026_07_09",
  "module_order": [
    "quick_summary",
    "market_state",
    "themes_and_flows",
    "watchlist_impact",
    "risk_radar",
    "key_evidence",
    "data_statement"
  ],
  "modules": {
    "quick_summary": {
      "key": "quick_summary",
      "title": "30 秒摘要",
      "status": "ready",
      "summary": "今日市场偏分化，AI 算力和半导体是主要活跃方向。",
      "content": {
        "market_state": "分化",
        "main_themes": ["AI 算力", "半导体"],
        "watchlist_impact": "mixed",
        "top_risks": ["市场宽度不足"]
      },
      "evidence_ids": [],
      "missing_data": [],
      "warnings": [],
      "confidence": "medium"
    },
    "market_state": {
      "key": "market_state",
      "title": "市场状态",
      "status": "ready",
      "summary": "指数上涨但市场宽度一般，整体呈分化状态。",
      "content": {
        "label": "分化",
        "signals": []
      },
      "evidence_ids": [],
      "missing_data": [],
      "warnings": [],
      "confidence": "medium"
    },
    "themes_and_flows": {
      "key": "themes_and_flows",
      "title": "主线与资金",
      "status": "partial",
      "summary": "AI 算力和半导体领涨，但概念资金流数据不完整。",
      "content": {
        "items": [
          {
            "name": "AI 算力",
            "direction": "leading",
            "change_pct": 3.2,
            "net_flow": 12.5,
            "trend": "continuing",
            "confidence": "high"
          }
        ]
      },
      "evidence_ids": [],
      "missing_data": ["concept_flows"],
      "warnings": ["概念资金流为空，未输出概念资金判断"],
      "confidence": "medium"
    },
    "watchlist_impact": {
      "key": "watchlist_impact",
      "title": "自选池影响",
      "status": "ready",
      "summary": "自选池与今日科技成长主线呈分化关联。",
      "content": {
        "positive": [],
        "negative": [],
        "neutral": [],
        "divergent": []
      },
      "evidence_ids": [],
      "missing_data": [],
      "warnings": [],
      "confidence": "medium"
    },
    "risk_radar": {
      "key": "risk_radar",
      "title": "风险雷达",
      "status": "ready",
      "summary": "主要风险来自指数与市场宽度背离。",
      "content": {
        "market": [
          {
            "level": "high",
            "signal": "指数和宽度持续背离",
            "detail": "主要指数上涨但下跌家数持续高于上涨家数，宽度指标走弱"
          }
        ],
        "sector": [],
        "watchlist": [],
        "data": []
      },
      "evidence_ids": [],
      "missing_data": [],
      "warnings": [],
      "confidence": "medium"
    },
    "key_evidence": {
      "key": "key_evidence",
      "title": "关键证据",
      "status": "ready",
      "summary": "本次简报使用 3 条关键证据支撑主要判断。",
      "content": {
        "items": []
      },
      "evidence_ids": [],
      "missing_data": [],
      "warnings": [],
      "confidence": "medium"
    },
    "data_statement": {
      "key": "data_statement",
      "title": "数据质量",
      "status": "ready",
      "summary": "数据质量为 partial，宏观和公告证据不足。",
      "content": {
        "data_quality": "partial",
        "confidence": "medium",
        "missing_data": [],
        "failed_modules": [],
        "data_sources_last_updated": {},
        "disclaimer": "本简报为本地数据自动生成，不构成投资建议。"
      },
      "evidence_ids": [],
      "missing_data": [],
      "warnings": [],
      "confidence": "medium"
    }
  },
  "warnings": []
}
```

兼容要求：

- `markdown` 仍保存在 `Briefing.markdown` 顶层字段，用于旧前端降级展示；不要重复写入 `sections_json`。
- `sections_json` 可以包含 V2 新字段，也可以是旧结构。
- `module_order` 缺失时，前端按旧逻辑展示 markdown。
- module section 的 `status` 缺失时，前端按 `ready` 处理。
- 旧简报缺少 V2 fields 时，前端继续渲染 `markdown`。
- **特别注意**：V2 的 `briefing.sections` 是一个 JSON 对象，包含 `module_order` 和 `modules`；旧版 `sections` 可能只是 `market_snapshot/watchlist_changes/errors` 等简单结构。前端需要先判断是否存在 `module_order`，再决定走 V2 模块渲染还是旧版 markdown 降级渲染。
- `/api/briefing/latest` 返回 V2 sections 时，API response 结构保持不变，仍通过 `data.briefing.sections` 承载结构化数据。



## 9. 前端设计

`/briefing` 页面从“文章阅读页”逐步调整为“简报工作台”。

### 9.1 顶部摘要区

首屏展示：

- 市场状态 badge。
- 主线 badge。
- 自选池影响 badge。
- 置信度 badge。
- 更新时间。

用户不滚动也能看到“今天重要的是什么”。

### 9.2 正文区

按 `briefing.sections.module_order` 展示模块：

1. 读取 `module_order`。
2. 从 `briefing.sections.modules[module_key]` 读取对应模块。
3. `status=ready` 正常展示。
4. `status=partial` 展示内容和 warning。
5. `status=missing` 展示缺失原因，避免用户误以为系统没有生成。
6. `status=failed` 默认折叠，但根据 `modules.data_statement.content.failed_modules` 列表展示"以下模块因数据原因未生成：模块名称"，用户点击后可展开失败详情。

如果没有 `module_order`，说明是旧简报：

- 继续渲染 `markdown`。
- 不强行展示 V2 模块卡片。
- 数据质量卡片仍使用顶层 `data_quality`、`confidence`、`missing_data`。



### 9.3 右侧信息栏

保留：

- 简报状态。
- 数据质量。
- 缺失维度。
- 历史简报。
- 快捷入口。

优化：

- 历史简报支持点击切换详情。
- 证据数量可点击跳转 `/market` 或展开证据。
- 数据质量 badge 使用中文说明，不只展示枚举值。
- 失败模块列表：展示 `modules.data_statement.content.failed_modules`，每项显示模块名称和失败原因。



## 10. 验收标准



### 10.1 内容验收

生成的简报必须满足：

- 顶部有 30 秒摘要。
- `quick_summary` 和 `data_statement` 必须始终生成。
- `post_market` 必须明确市场状态。
- `post_market` 至少说明一个自选池相关影响，除非自选池为空。
- `risk_radar` 启用时至少包含数据风险。
- profile 禁止的模块不得出现在正文中。
- 任何政策、公告、宏观归因必须能在 evidence 中找到。
- 不出现买卖建议。
- 不出现明日涨跌预测。
- 缺失数据必须显式说明。



### 10.2 数据验收

- evidence 为空时，正文不得写政策、公告、宏观原因。
- concept 数据为空时，不输出概念强弱判断。
- net_flow 全 0 或为空时，不输出资金流强判断。
- watchlist 为空时，输出“自选池为空”。
- 行情日期和生成日期不一致时，必须显示真实 `as_of`。
- 单个模块失败时，整篇简报仍可保存，但失败模块必须有 `status=failed`。



### 10.3 UI 验收

- 用户打开页面后，首屏能看到摘要、市场状态和风险。
- 前端按 `module_order` 渲染 V2 sections。
- 证据不占用过多主阅读区域。
- 缺失数据不隐藏。
- 历史简报能区分生成日期和数据日期。
- 老简报仍可通过 markdown 正常展示。



## 11. 测试计划



### 11.1 后端单测

覆盖：

- `get_brief_type_profile`
  - `post_market` 返回盘后模块组合。
  - `pre_market` 不包含 `themes_and_flows` 默认复盘模块。
  - 未知 `brief_type` 回退到 `post_market` 并记录 warning。
- `run_module_builders`
  - 按 profile 顺序执行。
  - 单模块异常时返回 `status=failed`，不终止整篇。
  - `forbidden_modules` 不会执行。
- `market_state_module`
  - 普涨。
  - 普跌。
  - 指数涨但宽度弱。
  - 数据缺失。
- `themes_and_flows_module`
  - 涨幅和资金一致。
  - 涨幅强但资金缺失。
  - 概念数据为空。
- `watchlist_impact_module`
  - 基金名称匹配主题。
  - 无匹配主题。
  - 自选池为空。
- `risk_radar_module`
  - 宽度恶化。
  - 跌停增加。
  - 数据缺失。
  - 单只基金跑输。
- `compose_briefing_v2`
  - evidence 为空不编造原因。
  - LLM 输出 JSON 可解析，且只使用 `markdown` / `markdown_warnings`。
  - markdown 按 `module_order` 组织。
  - 不输出 profile 禁止模块。
  - 如果 LLM 返回 `modules` 或 `sections`，后端必须忽略。
  - disclaimer 保留。
  - LLM 输出 JSON 解析失败时，使用原始文本作为 markdown，但保留 module builders 产出的 `sections_json`。
- Module Runner
  - 所有内容模块都返回 `status=failed` 时，简报仍可保存，并保留失败模块 envelope 与 `data_statement`。



### 11.2 前端测试

覆盖：

- 有 V2 sections 时展示 30 秒摘要。
- 按 `module_order` 渲染模块。
- `status=partial` 时展示 warning。
- `status=missing` 时展示缺失说明。
- 老简报缺少 `module_order` 时降级展示 markdown。
- `data_quality=partial` 时展示缺失维度。
- `evidence_count=0` 时显示证据不足。
- 证据新鲜度和权重 badge 正常展示。
- 失败模块列表正常展示，显示 `modules.data_statement.content.failed_modules` 中的模块名称和失败原因。
- 历史简报列表正常展示。



### 11.3 回归测试

覆盖：

- `/api/briefing/latest` 保持兼容。
- `/api/briefing/list` 不破坏历史简报。
- `/api/briefing/run` 仍可手动触发。
- 原有 `Briefing` 表不需要重建。
- 每日简报不输出投资建议。

### 11.4 Phase 4 迁移测试

覆盖：

- 老 `briefings` 数据迁移后 `brief_type` 默认等于 `post_market`。
- 同一 `briefing_date` 下可同时保存 `pre_market` 和 `post_market`。
- `/api/briefing/latest?type=pre_market` 只返回盘前简报。
- `/api/briefing/list?type=post_market` 只返回盘后简报列表。
- 未传 `brief_type` 的旧调用仍默认走 `post_market`。



## 12. 分阶段实施



### Phase 1: Profile 与模块协议

目标：建立类型 profile 和模块输出协议，保持现有简报接口兼容。

- 新增 `BriefTypeProfile` 定义。
- 新增 `post_market` profile。
- 新增统一 module section envelope。
- 新增 `module_order`。
- 修正“证据数据（财联社快讯）”写死问题。
- 保留当前数据收集逻辑。
- 保留当前 `Briefing` 表结构。



### Phase 2: Module Builders

目标：把核心判断拆成可测试模块，减少 LLM 自由发挥。

- 新增 `market_state_module`。
- 新增 `themes_and_flows_module`。
- 新增 `watchlist_impact_module`。
- 新增 `risk_radar_module`。
- 新增 `key_evidence_module`。
- 新增 `data_statement_module`。
- 新增 `quick_summary_module`。
- 把 module sections 传给 LLM final composer。



### Phase 3: 前端工作台优化

目标：从文章页变成简报面板。

- 顶部摘要卡片。
- 风险雷达卡片。
- 自选池影响卡片。
- 证据折叠面板。
- 证据新鲜度和权重展示（基于 `freshness` 和 `weight` 字段）。
- 按 `module_order` 动态渲染。
- 按 `status` 展示 ready / partial / missing / failed。
- 历史简报详情切换。



### Phase 4: 盘前 / 盘中 / 盘后

目标：让简报适配不同交易时段。

- 增加 `brief_type`。
- 数据库迁移：
  - `briefings` 新增 `brief_type` 字段，老数据默认回填为 `post_market`。
  - 唯一键从 `briefing_date` 调整为 `(briefing_date, brief_type)`。
  - 如果沿用轻量迁移方案，需要明确旧唯一约束无法自动修改时的兼容策略；生产化建议使用版本化迁移。
- 支持 `/api/briefing/latest?type=post_market`。
- 支持 `/api/briefing/list?type=post_market&limit=30`。
- 支持 `POST /api/briefing/run` 接收 `brief_type`，默认 `post_market`。
- 支持按 `brief_type` 生成。
- 新增 `pre_market` profile 和 `overnight_module`。
- 新增 `intraday` profile 和 `intraday_anomaly_module`。
- 调度器分别跑盘前和盘后。


### Phase 5: 用户反馈循环

目标：收集用户对简报质量的评价，用于后续优化 LLM prompt 和模块逻辑。

新增功能：

- 新增 `BriefingFeedback` 表或字段，存储用户对简报质量的评价。
- 新增 `/api/briefing/feedback` 接口，支持用户提交反馈。
- 反馈类型：
  - 风险判断准确性："这条风险信号后来看准吗？"
  - 主线判断准确性："今天主线判断是否符合你的感受？"
  - 证据质量："引用的证据有帮助吗？"
  - 整体满意度：1-5 分。
- 反馈数据用于后续优化 module builder 逻辑和 LLM prompt。



## 13. 推荐第一步

优先做 Phase 1 和 Phase 2 的后端部分：

- 不大改 UI。
- 先建立 profile + module builder 架构。
- 保持现有接口兼容。
- 让每日简报先稳定回答四个问题：
  - 今天市场是什么状态？
  - 主线是什么？
  - 和我的自选池有什么关系？
  - 风险在哪里，证据够不够？

完成后再基于 V2 sections 重构 `/briefing` 页面，会比先改 UI 更稳。
