# 第四阶段设计：LangGraph 问答流程

> 阶段 4 / 6。前置依赖：阶段三（LangChain Tools 全量封装，已完成）。详见 `../roadmap.md`。
> 本阶段把阶段三交付的 `ALL_TOOLS` 接入 LangGraph，形成可流式、可观测、带合规边界的基金问答主链路。
> 公告 RAG、风险扫描、日报、向量库、定时任务继续留到阶段五、六。

## 1. 目标

构建 QA Graph：用户问题进入后，先做确定性合规拦截；可回答的问题交给 DeepSeek
tool-calling 模型编排阶段三的 11 个 Tool；工具返回数据后由模型汇总成中文回答；最终回答再过一层边界检查。

本阶段的交付重点是“Agent 编排链路”，不是新增数据域。所有数字仍必须来自 Tool，LLM 只负责编排和解释。

## 2. 范围

**包含**：
- 新增 `backend/graph/` 作为 Phase 4 主链路模块
- `policy.py`：确定性识别并拒答买卖建议、持仓建议、收益预测、基金推荐、交易操作类请求
- `model.py`：复用现有 DeepSeek 配置，构造绑定 `ALL_TOOLS` 的 chat model
- `qa_graph.py`：导出 compiled LangGraph `graph`，并提供本地 `ask()` / `stream()` 调试入口
- 根目录 `langgraph.json`：供 `langgraph dev` / LangGraph Server 加载 `fund_agent`
- 工具错误契约修正：`fund_service.get_metrics` 遇到非法 `period` 返回 error dict
- README 与 smoke 脚本说明更新

**不包含**：
- 前端页面、FastAPI 自建问答路由
- RAG 公告检索、公告摘要、风险扫描、每日简报
- 交易、下单、支付宝或任何投资建议能力
- 新数据源（Tushare 继续延后）

## 3. 核心约定

- Graph 使用 `backend.tools.fund_tools.ALL_TOOLS`，不再只绑定 Phase 1 的两个薄工具。
- `backend.agent.thin_agent` 保留兼容，不在本阶段扩展；Phase 4 入口在 `backend.graph.qa_graph`。
- 合规策略前置：触发禁区的问题不进入 LLM 和 Tool 调用。
- 合规策略后置：最终回答若触及禁区，替换为固定拒答文本。
- 工具返回 `error` 时，回答必须如实说明数据缺失或参数错误，不编造数据。
- 回答基金/市场数据时必须引用工具返回的 `source` 和 `as_of`（或工具返回的具体日期字段）。
- 自选池写工具可用于维护本地自选池，但 prompt 明确禁止将其解释为买入、卖出、持仓或加减仓建议。

## 4. Public Interfaces

- `backend.graph.qa_graph.graph`：compiled LangGraph graph，LangGraph Server 加载入口。
- `backend.graph.qa_graph.ask(question: str) -> str`：本地一次性问答入口，返回最终 AI 文本。
- `backend.graph.qa_graph.stream(question: str) -> Iterator[dict]`：本地流式调试入口，返回 LangGraph stream chunk。
- LangGraph 输入状态：

```python
{"messages": [{"role": "user", "content": "..."}]}
```

- 触发合规边界时，Graph 返回单条 AI 拒答消息，不调用任何 Tool。

## 5. 文件结构

```
backend/
├── graph/
│   ├── __init__.py
│   ├── model.py       # DeepSeek + ALL_TOOLS 绑定
│   ├── policy.py      # 确定性合规边界
│   └── qa_graph.py    # compiled graph + ask/stream
├── services/
│   └── fund_service.py # 修正非法 period error dict
├── scripts/
│   └── smoke_fetch.py  # 增加 Phase 4 手动问答 smoke
└── tests/
    ├── test_graph_policy.py
    └── test_qa_graph.py
```

根目录新增 `langgraph.json`，`backend/requirements.txt` 增加 LangGraph 依赖。

## 6. 测试策略

- policy 单测完全离线，覆盖拦截与放行问题。
- Graph 单测使用 fake model / fake tool，不调真实 LLM、不联网。
- service 单测扩充非法 `period`，确保工具层不会把裸异常泄漏进 Graph。
- 手动 smoke 在有 `DEEPSEEK_API_KEY` 时运行；无 key 时跳过真实 LLM 路径。

## 7. 验收标准

1. `graph` 可被导入并接受 LangGraph 消息状态输入。
2. `ask()` 能返回最终回答文本；`stream()` 能产生至少一个流式 chunk。
3. Graph 使用 `ALL_TOOLS`，并能执行工具调用循环。
4. 买卖建议、收益预测、基金推荐、交易类问题被确定性拦截，且不调用 Tool。
5. 工具 error 被如实传递到回答中，不编造替代数据。
6. 全量离线测试通过。

## 8. 新增依赖

- `langgraph`：Graph API、消息状态、ToolNode。
- `langgraph-sdk`：手动 smoke / 前端后续接入可复用。
- `langgraph-cli[inmem]`：本地 `langgraph dev` 调试时按需单独安装，不放入主测试依赖。
