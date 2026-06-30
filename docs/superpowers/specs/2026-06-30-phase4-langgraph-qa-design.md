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

## 4. Graph State Schema

LangGraph 使用 `StateGraph` + `MessagesState`（`langgraph>=0.2`）。

### State 定义

```python
from langgraph.graph import MessagesState

class QAState(MessagesState):
    """QAState 继承 langgraph 的 MessagesState，messages 即完整会话历史。

    LangGraph MessagesState 自动维护 HumanMessage / AIMessage / ToolMessage
    的追加逻辑，无需手动管理。
    """
    pass
```

- `messages: list[BaseMessage]` — 完整消息链，按 `add_messages` 合并追加。
  输入时只需传入单条 `HumanMessage`，LangGraph 会自动追加后续 `AIMessage`（含 tool_calls）和 `ToolMessage`。
- 工具返回值通过 `ToolMessage` 追加进 `messages`，不设独立的 `tool_results` key。
- 拒绝回答时，向 `messages` 追加一条 `AIMessage(content=REFUSAL_MESSAGE)`。

### ask() / stream() 签名与返回类型

```python
def ask(question: str, *, config: dict | None = None) -> str:
    """
    本地一次性问答入口。

    参数:
        question: 用户提问（中文）。
        config: 可选，LangGraph ConfigurableField（如 thread_id）。

    返回:
        graph 最终输出的 AI 回答文本（不含 tool_calls）。
        触发合规边界时返回固定拒答文本。
    """

def stream(question: str, *, config: dict | None = None) -> Iterator[dict]:
    """
    本地流式调试入口。

    返回:
        Iterator[dict]，每个 chunk 为 LangGraph stream 输出的一个节点状态，
        结构为 `{"node_name": node_output}`（如 `{"pre_check": {...}}`）。
        chunks 按 LangGraph 内部节点执行顺序产出（pre_check → llm → tools → ...）。
    """
```

### tool-call 循环如何工作

```
HumanMessage → pre_check → _route_pre_check → llm → _route_llm → tools → llm → ... → post_check → END
                         ↓ (blocked)                              ↓ (no tool_calls)
                      AIMessage(REFUSAL)                              ↓
                           ↓                                    post_check
                         END                                          ↓
                                                              AIMessage
```

- `pre_check` 节点：调用 `policy.check_question`，命中禁区 → 追加 `AIMessage(REFUSAL_MESSAGE)` 并通过 `_route_pre_check` 路由到 END；放行 → 路由到 llm。
- `_route_llm` 节点：判断最后一条消息是否有 `tool_calls`：
  - 有 `tool_calls` → 路由到 tools（ToolNode 执行工具，返回 `ToolMessage` 追加进 messages）
  - 无 `tool_calls` → 路由到 post_check（最终合规检查）
- `llm` 收到 `ToolMessage` 后再次被调用，汇总工具返回为最终回答。
- LangGraph 自动管理循环：多轮 tool_calls 时重复 llm → tools → llm 路径。
- `post_check` 节点：调用 `policy.check_answer`，命中禁区 → 替换最后一条 `AIMessage.content` 为 `REFUSAL_MESSAGE`。

### langgraph.json

```json
{
  "dependencies": ["./backend/graph"],
  "graphs": {
    "fund_agent": "./backend/graph/qa_graph.py:graph"
  }
}
```

## 5. Public Interfaces

| 接口 | 说明 |
|------|------|
| `backend.graph.qa_graph.graph` | compiled LangGraph graph，LangGraph Server 加载入口 |
| `ask(question, *, config?) -> str` | 本地一次性问答；见 Section 4 类型签名 |
| `stream(question, *, config?) -> Iterator[dict]` | 本地流式调试；见 Section 4 类型签名 |
| `backend.graph.policy.REFUSAL_MESSAGE` | 固定拒答文本常量 |
| `backend.graph.policy.check_question(text) -> bool` | True=放行，False=拦截 |
| `backend.graph.policy.check_answer(text) -> bool` | True=放行，False=拦截 |

## 6. 文件结构

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

## 7. 测试策略

- policy 单测完全离线，覆盖拦截与放行问题。
- Graph 单测使用 fake model / fake tool，不调真实 LLM、不联网。
- service 单测扩充非法 `period`，确保工具层不会把裸异常泄漏进 Graph。
- 手动 smoke 在有 `DEEPSEEK_API_KEY` 时运行；无 key 时跳过真实 LLM 路径。

## 8. 验收标准

1. `graph` 可被导入并接受 LangGraph 消息状态输入。
2. `ask()` 能返回最终回答文本；`stream()` 能产生至少一个流式 chunk。
3. Graph 使用 `ALL_TOOLS`，并能执行工具调用循环。
4. 买卖建议、收益预测、基金推荐、交易类问题被确定性拦截，且不调用 Tool。
5. 工具 error 被如实传递到回答中，不编造替代数据。
6. 全量离线测试通过。

## 9. LangGraph 0.6 实现注意事项

- `StateGraph(state_schema)` 不接受 `messages_modifier` 参数；`MessagesState` 已内置 `add_messages` 作为 reducer，无需额外指定。
- 两个条件边需要各自独立的路由函数：`_route_pre_check` 处理 pre_check → llm|END，`_route_llm` 处理 llm → tools|post_check。LangGraph 0.6 在构建图时注册函数引用，同一函数不能为不同源节点返回不同目标名。
- `compiled.graph` 通过 `_get_graph()` 延迟构造单例，以便测试在首次导入前 patch `build_model`。
- `stream()` 输出的 chunk key 是节点名（如 `{"pre_check": {...}}`），不是 `"messages"`。

## 10. 新增依赖

- `langgraph`：Graph API、消息状态、ToolNode。
- `langgraph-sdk`：手动 smoke / 前端后续接入可复用。
- `langgraph-cli[inmem]`：本地 `langgraph dev` 调试时按需单独安装，不放入主测试依赖。
