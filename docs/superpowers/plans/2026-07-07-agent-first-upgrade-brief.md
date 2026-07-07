# Agent-First 升级 Implementation Plan (Brief)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is a **brief**; expand task-by-task once execution is approved.

**Goal:** Upgrade `fund-agent` from "LLM + tool-calling" to a real agent with planning, reflection, memory, and proactive capability — without changing architecture or adding heavy dependencies.

**Architecture:** Three waves of work on top of the existing `backend.graph.qa_graph`. Wave 1 hardens the tool-calling loop (粗粒度工具 + system prompt + reflect node + 前端上下文注入). Wave 2 adds knowledge and policy memo (`announcements` RAG + user preference). Wave 3 adds multi-agent routing and proactive briefing. Each wave is shippable independently.

**Tech Stack:** Python 3.11, LangGraph 0.6, LangChain Core, DeepSeek `deepseek-chat`, FastAPI, SQLite, AkShare, Next.js 14, TanStack Query, pytest, Node test runner.

---

## 现状 Diagnosis(为什么这版 plan)

| 维度 | 现状 | 目标 |
|---|---|---|
| 工具粒度 | 13 个细粒度工具(`get_latest_fund_nav` / `get_fund_basic_info` / `get_fund_nav_history` / `get_metrics` ...) | 6–8 个粗粒度工具(`lookup_fund` / `lookup_portfolio` / `lookup_market` / `diagnose_fund` / `refresh_fund` / `search_announcements` ...) |
| System prompt | 无,LLM 仅靠 `bind_tools` 推断行为 | 显式 SYSTEM_PROMPT:角色 + 工具调用约定 + 回答格式 + few-shot |
| 反思 | 工具失败 → 直接进 LLM | `_reflect` 节点:工具结果不完整时提示 LLM 补调,完整时直接进 post_check |
| 主动上下文 | 前端只发 `{messages: [human]}` | 进 `/qa` 时把 watchlist + 持仓 + 最近诊断 注入 first human message |
| 规划 | 无 | router node:小问题 fast path,大问题进 planner 子图 |
| 记忆 | LangGraph thread messages(只记对话) | `UserPreference` 表:风险偏好 / 关注板块 / 最近操作 |
| 知识/检索 | `announcements` API 是 stub,无 RAG | `search_announcements` 工具 + SQLite FTS5 |
| 主动能力 | 完全被动 | 每日 A股收盘后跑 `daily_briefing_graph`,写 `Briefing` 表,前端 `/briefing` 渲染 |
| 可观测 | 无 token / 失败率统计 | LangSmith env 接入 + 关键事件 callback |
| Eval | 无 | 50 条 golden query + 自动回归(`backend/tests/eval/`) |

---

## Global Constraints

- **Wave-1 之前**先确认依赖的现有模块已稳定:`backend/graph/qa_graph.py` / `backend/tools/fund_tools.py` / `frontend/app/qa/page.tsx`。
- **不改架构**:不引入新数据库、不替换 LangGraph 版本、不动 `thin_agent` 的兼容路径。
- **不改 policy 红线**:`policy.py:19-77` 的合规词表维持不变;`check_question` / `check_answer` 行为保留。
- **不引入外部 RAG 服务**:Wave-2 的 announcements 用本地 SQLite FTS5(未来可平滑迁 pgvector)。
- **不破坏现有 13 个测试**:每次提交前 `.venv/bin/python -m pytest backend/tests/ -x` 必须全绿。
- **TDD 优先**:每个新模块先写失败测试,再写实现。
- **可逆性**:粗粒度工具和细粒度工具可共存,旧工具通过 deprecation warning 保留 1 个版本。

---

## Wave 划分与依赖

```
Wave 1 (Agent Hardening)        Wave 2 (Knowledge + Memory)    Wave 3 (Proactive + Multi-agent)
├─ T1.1 合并 fund 工具          ├─ T2.1 announcements 表 +     ├─ T3.1 router node
├─ T1.2 合并 pnl/portfolio 工具  │   抓取脚本                   ├─ T3.2 planner 子图
├─ T1.3 合并 watchlist 工具      ├─ T2.2 search_announcements   ├─ T3.3 daily_briefing_graph
├─ T1.4 合并 market 工具         │   工具 + FTS5                ├─ T3.4 主动告警 cron
├─ T1.5 SYSTEM_PROMPT 模块       ├─ T2.3 UserPreference 表      └─ T3.5 /briefing 前端页
├─ T1.6 _reflect 节点            ├─ T2.4 load_user_context 工具
├─ T1.7 前端上下文注入           └─ T2.5 系统 prompt 增强
└─ T1.8 LangSmith env + 指标

依赖图:
T1.* 内部: T1.5 依赖 T1.1-1.4 工具收敛 → T1.6 依赖 T1.5 → T1.7 依赖 T1.1-1.4
T2.* 可以与 Wave-1 并行,但 T2.5 必须在 T1.5 完成后做
T3.* 依赖 Wave-1 全部完成
```

---

## File Map(全集,所有波次)

### Wave 1(本季度必做)

- Create `backend/graph/prompts.py`: SYSTEM_PROMPT 常量 + few-shot。
- Modify `backend/graph/qa_graph.py`:prepend SystemMessage + `_reflect` 节点 + 新路由。
- Modify `backend/tools/fund_tools.py`:新增 `lookup_fund` 粗粒度工具,标记老工具 deprecated。
- Create `backend/tools/portfolio_tools.py`:`lookup_portfolio` 把 `calculate_holding_pnl` + watchlist + nav 合并。
- Modify `backend/tools/watchlist_tools.py`:加 `set_user_preference` 工具,`add_fund_to_watchlist` 不变。
- Create `backend/tools/market_tools.py`:`lookup_market_snapshot` 合并指数 + 板块 + 宏观。
- Modify `backend/tools/fund_tools.py`:`ALL_TOOLS` 用新粗粒度列表。
- Modify `backend/tests/test_qa_graph.py`:新增「reflect 触发/未触发」两条用例。
- Create `backend/tests/test_graph_prompts.py`:`get_system_prompt()` 返回非空 + 含关键约束。
- Modify `frontend/app/qa/page.tsx`:进页时 GET `/api/context/initial`,把 summary 拼到 first message。
- Create `frontend/src/lib/context.ts`:读 `/api/context/initial` 返回结构化摘要。
- Create `backend/api/routes/context.py`:`/api/context/initial`,聚合 watchlist/持仓/最近诊断。
- Modify `frontend/src/lib/langgraph.ts`:支持 system-context payload(若 LangGraph SDK 已支持;否则继续拼 human message)。
- Modify `backend/config/settings.py`:`langsmith_*` 配置字段;不动行为。

### Wave 2(下一季度)

- Create `backend/db/models.py` 新增 `FundAnnouncement` / `UserPreference` / `UserQueryLog`。
- Modify `backend/db/repository.py`:新表的 CRUD helper。
- Create `backend/services/announcement_service.py`:抓取 + 落库 + FTS5 索引。
- Create `backend/services/user_preference_service.py`:读写 UserPreference。
- Modify `backend/services/scheduled_refresh.py`:在 wave job 里加 announcement 抓取步骤(可选,避免改主路径)。
- Create `backend/tools/announcement_tools.py`:`search_announcements(query, fund_codes, days)`。
- Modify `backend/tools/fund_tools.py`:把 `search_announcements` 加进 `ALL_TOOLS`。
- Create `backend/api/routes/announcements.py`:填充 stub,接 `search_announcements` service。
- Create `backend/tests/test_announcement_search.py`:FTS5 召回测试。

### Wave 3(后续季度)

- Create `backend/graph/router.py`:router node,根据 query 复杂度分到 fast path 或 planner。
- Create `backend/graph/planner_subgraph.py`:planner + research + critic 三节点。
- Create `backend/graph/daily_briefing_graph.py`:cron 驱动,合成每日自选简报。
- Create `backend/db/models.py` 新增 `Briefing` 表。
- Modify `backend/scheduler.py`:增 `daily_briefing` 任务。
- Create `frontend/app/briefing/page.tsx`:简报渲染。

---

## Wave 1 详细任务(TDD-ready)

### Task 1.1: 合并 fund 工具为 `lookup_fund`(粗粒度)

**Files:**
- Create `backend/tools/lookup_tools.py`(放 `lookup_fund`,与 fund_tools.py 平级)。
- Modify `backend/tools/fund_tools.py`:标注 deprecated,继续导出。
- Test `backend/tests/test_lookup_fund_tool.py`。

- [ ] 写失败测试:`test_lookup_fund_returns_basic_nav_metrics`(mock `fund_service.get_summary` + `diagnose_service.diagnose_fund`,断言一次返回里含 `fund_code / fund_name / latest_nav / metrics_period_1m / metrics_period_1y / diagnose.summary / diagnose.decision_label`)。
- [ ] 写失败测试:`test_lookup_fund_propagates_refresh_warn`(当本地无数据时返回 `{error, missing_fields: ["fund", "latest_nav"]}`,允许 LLM 判断后调 `refresh_fund`)。
- [ ] 实现 `lookup_fund(fund_code: str, include_diagnosis: bool = False) -> dict`,内部并发调 service。
- [ ] 在 `fund_tools.py` 顶加 `# DEPRECATED: use lookup_fund in backend.tools.lookup_tools` 注释。
- [ ] 跑 `pytest backend/tests/test_lookup_fund_tool.py -x` 全绿。

### Task 1.2: 合并 pnl/portfolio 工具为 `lookup_portfolio`

**Files:**
- Modify `backend/tools/portfolio_tools.py`(把 `pnl_tools.py` 改名)。
- Test `backend/tests/test_portfolio_tools.py`。

- [ ] 写失败测试:`test_lookup_portfolio_returns_pnl_watchlist_and_diagnosis_summary`(mock 三个 service)。
- [ ] 写失败测试:`test_lookup_portfolio_optional_fund_codes_subset`。
- [ ] 实施:模仿 `lookup_fund`,合 `calculate_holding_pnl` + `list_watchlist` + `get_watchlist_recent_diagnosis`(后者在 Wave-2 才会真有数据;此处允许 `None`)。
- [ ] 跑测试。

### Task 1.3: 合并 watchlist 工具为 `manage_watchlist`(单工具多动作)

**Files:**
- Modify `backend/tools/watchlist_tools.py`。
- Test `backend/tests/test_watchlist_tools.py`。

- [ ] 写失败测试:`test_manage_watchlist_action_add_remove_update_query`(单工具,通过 `action` enum 区分)。
- [ ] 实施:`@tool def manage_watchlist(action: Literal["list","add","remove","update_note","set_preference"], fund_code: str = "", note: str = "", preference: dict | None = None) -> dict`。
- [ ] 跑测试。

### Task 1.4: 合并 market 工具为 `lookup_market_snapshot`

**Files:**
- Modify `backend/tools/market_tools.py`(已存在)。
- Test `backend/tests/test_market_tools.py`。

- [ ] 写失败测试:`test_lookup_market_snapshot_returns_indices_sectors_macro`(mock `market_service`)。
- [ ] 实施:`@tool def lookup_market_snapshot(scope: Literal["indices","sectors","macro","all"] = "all") -> dict`。
- [ ] 跑测试。

### Task 1.5: 提取 `SYSTEM_PROMPT`

**Files:**
- Create `backend/graph/prompts.py`。
- Test `backend/tests/test_graph_prompts.py`。

- [ ] 写失败测试:`test_system_prompt_includes_compliance_and_tool_contract`。
- [ ] 写失败测试:`test_system_prompt_includes_few_shot_examples`。
- [ ] 实施:从对话记录手工写 prompt(参考上文诊断段第 ② 条)。
- [ ] 跑测试。

### Task 1.6: 加入 `_reflect` 节点

**Files:**
- Modify `backend/graph/qa_graph.py`。
- Test `backend/tests/test_qa_graph.py`(新增)。

- [ ] 写失败测试:`test_reflect_node_flags_incomplete_tool_result`(ToolMessage 含 `{error}` 或某些 required key 缺失 → ReflectNode 注入 HumanMessage 提示补调)。
- [ ] 写失败测试:`test_reflect_node_skips_when_complete`。
- [ ] 实施:`_reflect(state)`,内部判断 last message 是否 ToolMessage 且 payload 是否完整;不完整返回 `{messages:[HumanMessage("...")]}`,完整返回 `{}`。
- [ ] 接线:`tools → reflect → (llm | post_check)`(用 `_route_reflect`)。
- [ ] 跑测试 + 全量回归。

### Task 1.7: 前端上下文注入

**Files:**
- Create `backend/api/routes/context.py`。
- Modify `backend/api/app.py`:注册 router。
- Create `frontend/src/lib/context.ts`。
- Modify `frontend/app/qa/page.tsx`。

- [ ] 写失败测试:`test_initial_context_returns_watchlist_pnl_summary`(用 test client)。
- [ ] 实施:`GET /api/context/initial` 返回 `{watchlist_count, holding_count, top_holding_code, recent_diagnoses:[{fund_code, label}]}`。
- [ ] 实施 `frontend/src/lib/context.ts`:TanStack Query 包一层。
- [ ] 实施 `frontend/app/qa/page.tsx`:进页时 useQuery,组装 "【用户当前 ...】我的问题: <user_input>" 作为 first message;`streamMode: "messages"` 不变。
- [ ] 手测 + 跑前端测试。

### Task 1.8: LangSmith env 接入

**Files:**
- Modify `backend/config/settings.py`。
- Modify `backend/graph/model.py`:env var pass through。

- [ ] 写失败测试:`test_model_passes_langsmith_env_to_chat_openai`(monkeypatch `os.environ`,断言 `ChatOpenAI` 构造时 `langsmith_project` 被设)。
- [ ] 实施:`settings` 加 `langsmith_api_key` / `langsmith_project` / `langsmith_tracing_v2`;`build_model()` 在 deepseek 调用前 `os.environ.setdefault(...)`(或传 `extra_body`)。
- [ ] 跑测试。

### Wave-1 Verification

- [ ] `pytest backend/tests/ -x --ignore=backend/tests/test_announcement_search.py` 全绿。
- [ ] `cd frontend && npm test` 全绿。
- [ ] 手测 query 1:"查询 110011 的最新净值":`tool_calls` 数 ≤ 2(原 ≥ 3)。
- [ ] 手测 query 2:"我的持仓里哪只跌得最多":`tool_calls` 链路 `lookup_portfolio → post_check`(不再绕 `list_watchlist + calculate_holding_pnl` 两条)。
- [ ] `grep -rn "DEPRECATED" backend/tools/` 至少有 4 条注解。

---

## Wave 2 详细任务(简版,TDD-ready at execution time)

### Task 2.1: 公告存储 + FTS5 索引

- Create `FundAnnouncement` 表(fund_code, title, publish_date, content, url, source)。
- 抓取脚本接 `ak.fund_announcement_em`,定时跑。
- 在 `fund_announcements.content_fts` 建 FTS5 虚拟表。

### Task 2.2: `search_announcements` 工具

- `@tool def search_announcements(query: str, fund_codes: list[str] | None = None, days: int = 30, limit: int = 5) -> dict`
- 返回 `{query, results:[{fund_code, title, publish_date, snippet, url}], count}`。
- 加进 `ALL_TOOLS`。

### Task 2.3: `UserPreference` 表

- `key/value` JSON 表,key 枚举 `risk_tolerance` / `favorite_sectors` / `briefing_opt_in`。
- `set_user_preference(key, value)` / `get_user_preferences()` service。
- `manage_watchlist` 加 `action="set_preference"`。

### Task 2.4: `load_user_context` 工具

- `@tool def load_user_context() -> dict` 返回偏好+简报订阅状态。
- 在 `qa_graph.py` 加一个 `load_context` node,在 pre_check 之后立刻跑。
- 把 UserPreference 字段拼进 SYSTEM_PROMPT(动态构造)。

### Task 2.5: 政策提示词增强

- 在 `SYSTEM_PROMPT` 增加"如果你读到了用户偏好(高风险/关注白酒),回答时只作为客观背景使用,不据此给建议"。

### Wave-2 Verification

- [ ] `test_search_announcements_fts5_returns_correct_topk` 通过。
- [ ] `test_user_preference_round_trip` 通过。
- [ ] 完整 pytest 全绿。
- [ ] 手测 query 3:"110011 最近 30 天有什么公告":正确返回 ≥ 1 条。

---

## Wave 3 详细任务(简版)

### Task 3.1: Router node

- 在 `_llm_node` 之前加 `_route_complexity` node,用 cheaper prompt(甚至 LLM-router / rule)判断走 fast path 或 planner subgraph。
- 规则:query 含"比较/对比/分析一下/为什么/总结" → planner;否则 fast。

### Task 3.2: Planner 子图

- `planner → research → critic → END` 三节点。
- `planner` 产出 1–3 步 plan(ToolMessage / 内部 state)。
- `research` 执行 plan。
- `critic` 检查 plan 是否覆盖,如未覆盖回到 planner。

### Task 3.3: `daily_briefing_graph`

- 内部:并行拉自选每只最新 NAV + market snapshot + 最近 3 条公告;DeepSeek 合成简报;写 `Briefing` 表。

### Task 3.4: 主动告警

- 自选池每日NAV变化超阈值时写 `AlertEvent`,前端 push 通知。

### Task 3.5: `/briefing` 前端页

- 列表展示历史简报,支持定位到某日的具体引用。

### Wave-3 Verification

- [ ] 端到端测试:router 把 "110011 最新净值" 推到 fast path,工具调用次数 ≤ 2。
- [ ] 端到端测试:router 把 "对比 110011 和 008888 的收益和回撤" 推到 planner,plan 有 3 步且都被执行。
- [ ] `daily_briefing_graph` 跑一次产出非空 `Briefing` 记录。

---

## Specs & References

- Existing related plans:
  - `docs/superpowers/plans/2026-07-02-fund-diagnosis.md`(诊断能力已就绪)
  - `docs/superpowers/plans/2026-07-06-scheduled-refresh.md`(定时任务已就绪,Wave-2 接管)
  - `docs/superpowers/plans/2026-07-06-portfolio-pnl-series.md`(portfolio service 已就绪)
- Design spec 待补充:`docs/superpowers/specs/2026-07-07-agent-first-upgrade-design.md`(执行本 plan 时一并建立)。

---

## Open Questions(执行前需回答)

1. **工具合并策略**:粗粒度直接替换细粒度,还是并存(deprecated 标签)?
   - 推荐并存 1 个版本,然后下一轮删。理由:rollback 容易,旧测试好过渡。
2. **前端上下文注入方式**:拼 first human message,还是 LangGraph SDK 已有 system-context 字段?
   - 推荐先拼 human message(兼容性最好),之后等 SDK 升级。
3. **LangSmith 是否真的开**:开 tracing 有成本(每条 run 会打 token)。先开,但 `LANGCHAIN_TRACING_V2=false` 默认关闭,`true` 时再开。
4. **`/briefing` 是否 P0**:Wave-3 里最容易被推迟的一项,可以挪到独立 plan。
5. **Announcements 抓取节奏**:跟着 Wave-1 的 scheduler 跑,还是独立 cron?
   - 推荐复用现有 `scheduled_refresh`,加 step 而不是新建 scheduler。

回答上述 5 问 → 我把 brief 展开为每波 task 的详细清单(预计额外 600-1000 行 TDD-ready 步骤),放到 `docs/superpowers/plans/2026-07-07-agent-first-upgrade.md`。
