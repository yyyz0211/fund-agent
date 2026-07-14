"""简报专属 prompt 模板。

历史: 这些模板原本在 `backend.graph.prompts`,但 `BRIEFING_PROMPT_TEMPLATE`
和 `BRIEFING_PROMPT_TEMPLATE_V2` 都是 briefing 域的私有数据 — graph /
agent 的 LangGraph QA 流不需要它们。把它们搬到 briefing 域能:

- 消除 `backend.services.briefing` 对 `backend.graph` 的反向依赖(spec 2.2)
- 让 prompt 模板紧贴消费它的 service,未来按 brief_type 做变体时不需要
  跨模块改动

graph/qa_graph 使用的 SYSTEM_PROMPT / FEW_SHOT_EXAMPLES 仍保留在
`backend.graph.prompts`,因为它们属于 graph / agent 的输入而非 briefing。
"""
from __future__ import annotations

from string import Template


BRIEFING_PROMPT_TEMPLATE = """你是数据编辑助理，根据下方 JSON 数据输出一份简洁的每日市场与基金简报。

## 数据说明

$snapshot_json 中包含:

- market_snapshot: 今日 A 股主要指数（上证/深成/创业板/科创50）的代码/名称/收盘价/涨跌幅
- market_breadth: 市场宽度 {"up": 上涨家数, "down": 下跌家数, "limit_up": 涨停数, "limit_down": 跌停数, "volume": 成交额(亿元), "amount": 成交量, "total": 总家数}
  - 当 market_breadth 全为 0 时，说明今日为非交易日或数据暂未更新，简报中 market_breadth 相关描述应标注"数据待更新"
- industry_sectors: 行业板块涨跌幅 [{"name": 板块名, "change_pct": 涨跌幅}, ...]，按涨跌幅降序排列
- industry_flows: 行业板块资金流向 [{"name": 板块名, "net_flow": 净流入(亿)}, ...]
- concept_sectors: 概念板块涨跌幅 [{"name": 板块名, "change_pct": 涨跌幅}, ...]
- concept_flows: 概念板块资金流向 [{"name": 板块名, "net_flow": 净流入(亿)}, ...]
- sector_snapshot: 行业板块涨跌（已有，简写版）
- watchlist_changes: 自选基金各周期收益率 [{"fund_code": 代码, "fund_name": 名称, "period_returns": {"1d": 近1日, "1w": 近1周, "1m": 近1月}}, ...]

## 证据数据（market_evidence，包含财联社电报、公告、政策、宏观等来源）

$evidence_json 中包含当日从各来源采集的市场证据，每条格式为:
{id, trade_date, category, title, summary, source, source_url, published_at, reliability}

categories 包括: policy（政策）、announcement（公告）、macro（宏观）、news（资讯）等。
证据是简报生成的重要参考——"操作观察"和"风险提示"段应直接引用证据内容，包括其 title / summary / source_url。

## 数据质量元数据（供参照，不得写入正文）

- data_quality: complete / partial / market_only / failed
- confidence: high / medium / low
- missing_data: 当前缺失的数据维度列表（与 evidence 维度对应）

简报中"操作观察"和"风险提示"段，如涉及政策/公告/宏观原因，**必须**只在证据数据中存在该证据时才能陈述；

简报中"操作观察"和"风险提示"段,如涉及政策/公告/宏观原因,**必须**只在 evidence 列表中存在该证据时才能陈述;
evidence 为空时使用"本地暂无政策/公告/宏观证据,以上仅为板块涨跌事实"的描述,
**不得**把未在 evidence 中出现的政策原因写成事实。

## 输出要求

1. **必须命中以下 sections（9 个）**:
   - 指数表现: 代码/名称/收盘价/涨跌幅，使用表格
   - 赚钱效应: 上涨/下跌家数、涨停/跌停，客观描述市场情绪（数据缺失时标注"数据待更新"）
   - 板块动向: 行业强势板块（top3）/ 弱势板块（bottom3），列出具体涨跌幅
   - 概念板块动向: 概念强势（top3）/ 弱势（bottom3），列出具体涨跌幅
   - 板块资金流向: 行业净流入 top3 / bottom3，概念净流入 top3 / bottom3
   - 自选池涨跌: 基金代码/名称/近1日/近1周/近1月收益率
   - 风险提示: 客观描述近期波动较大的基金或板块，**每条风险必须包含 level 字段**（high/medium/low）
   - 操作观察: 本日需关注的市场信号（≤3 条，基于已有数据）
   - 数据声明: 数据来源(akshare) + 证据来源(简要罗列 evidence.source) + as_of 日期 + data_quality + **data_sources_last_updated**

2. **输出 sections 必须包含以下 V2 字段**（供前端直接渲染 badge）:

   `quick_summary` section:
   ```json
   {
     "key": "quick_summary",
     "title": "30 秒摘要",
     "status": "ready",
     "market_state": "分化",
     "main_themes": ["AI 算力", "半导体"],
     "top_risks": ["市场宽度不足"],
     "watchlist_impact": "mixed",
     "confidence": "medium"
   }
   ```

   `risk_radar` section 中每条风险:
   ```json
   {
     "level": "high",
     "signal": "指数和宽度持续背离",
     "detail": "主要指数上涨但下跌家数持续高于上涨家数"
   }
   ```

   `themes_and_flows` section 中每条主题:
   ```json
   {
     "name": "AI 算力",
     "direction": "leading",
     "change_pct": 3.2,
     "net_flow": 12.5,
     "trend": "continuing"
   }
   ```
   trend 取值: continuing / emerging / fading / new

   `key_evidence` section 中每条证据:
   ```json
   {
     "evidence_id": 123,
     "category": "news",
     "title": "...",
     "source": "...",
     "source_url": "...",
     "published_at": "...",
     "freshness": "today",
     "weight": "medium"
   }
   ```
   freshness 取值: realtime / today / recent / older
   weight 取值: high / medium / low（政策原文和交易所公告为 high，转发资讯为 medium，无来源为 low）

   `data_statement` section:
   ```json
   {
     "data_quality": "partial",
     "confidence": "medium",
     "missing_data": ["macro_evidence"],
     "failed_modules": [],
     "data_sources_last_updated": {
       "market_snapshot": "2026-07-09T15:30:00+08:00",
       "cls_telegraph": "2026-07-09T17:00:00+08:00"
     }
   }
   ```

3. **禁止输出以下任何内容**:
   - 投资建议，如"建议加仓"、"建议减仓"、"不应追高"、"可以买入"、"应卖出"
   - 操作思路、操作计划、买卖时机预测
   - 对未来涨跌的预测，如"预计明日上涨"、"预期明天回调"
   - 任何强制性交易指令
   - 未在上述 JSON 数据中出现的内容（如龙虎榜、北向资金、政策解读等）
   - **未在 evidence 列表中出现的政策/公告/宏观原因**(本地证据不足时不编造)

3. **格式规范**:
   - 默认 ≤ 1000 字
   - 使用 markdown 渲染格式
   - 指数涨跌和基金收益可使用表格
   - 收益率显示为带正负号百分比，如 +1.23% / -0.45%
   - 数据缺失时用"暂无数据"或"数据待更新"标注，不要留空
   - 引用 evidence 时附 source / source_url / published_at 三元组

4. **固定 disclaimer（必须保留在末尾）**:
   本简报为本地数据自动生成，不构成投资建议。
   本地证据可能不完整；缺失维度以 `data_quality` 与 `missing_data` 为准。

## 输出格式

请返回以下 JSON（不要在 JSON 之外输出任何内容）:

{"markdown": "...", "sections": {"market_snapshot": [...], "watchlist_changes": [...], "errors": [], "disclaimer": "本简报为本地数据自动生成,不构成投资建议。"}}
"""


# V2 prompt: 使用 module builders 产出的结构化 sections，由 LLM 负责语言组织
BRIEFING_PROMPT_TEMPLATE_V2 = Template("""你是数据编辑助理，根据下方 JSON 数据输出一份简洁的市场与基金简报。

## 简报类型
brief_type: ${brief_type}

## Profile
${profile_json}

## 模块结构（由后端 module builders 生成，不得修改或删除）
module_sections 包含后端确定性判断产出的结构化数据，你只需将其转化为流畅的 markdown 正文。

${module_sections_json}

## 原始市场数据（供补充细节参考）
${snapshot_json}

## 证据数据（market_evidence）
${evidence_json}

## 你的职责
1. 按 module_order 顺序组织 markdown，每个模块用 ### 标题分隔。
2. 每个模块的 summary 是核心结论，正文在此基础上展开，不要重复 summary。
3. 引用 evidence 时附 source / source_url / published_at。
4. **绝对禁止**在正文中重复 evidence 内容，只引用标题和来源。
5. 禁止输出投资建议、未来预测。

## 格式要求
- ≤ ${max_markdown_words} 字。
- 使用 markdown 渲染格式。
- 数据缺失时用"暂无数据"或"数据待更新"标注。
- 末尾保留 disclaimer。

## 输出格式

请返回以下 JSON（不要在 JSON 之外输出任何内容）:

{"markdown": "...", "markdown_warnings": []}
""")


__all__ = [
    "BRIEFING_PROMPT_TEMPLATE",
    "BRIEFING_PROMPT_TEMPLATE_V2",
]