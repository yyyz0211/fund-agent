"""Phase-4 LangGraph QA flow."""
from typing import Annotated, Iterator, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from backend.graph import policy
from backend.graph.model import build_tool_model
from backend.tools.fund_tools import ALL_TOOLS

SYSTEM_PROMPT = (
    "你是个人基金市场信息助手,不是投资顾问。"
    "你只能提供公开信息整理、历史数据分析和风险提示。"
    "你不能给出买入、卖出、持有、加仓、减仓、申购、赎回、基金推荐或收益预测。"
    "所有数字必须来自工具返回结果,不得自行编造或心算。"
    "回答基金或市场数据时必须附上工具返回的 source 与 as_of 或数据日期。"
    "若工具返回 error,请如实说明数据缺失或参数错误,不要编造数据。"
    "自选池工具只用于维护本地清单,不能被解释为交易或投资建议。"
)


class QAState(TypedDict):
    """LangGraph state for the fund QA graph."""

    messages: Annotated[list[AnyMessage], add_messages]
    blocked: bool


def _content(message) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))


def _last_user_text(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "type", "")
        if role in {"human", "user"}:
            return _content(message)
    return _content(messages[-1]) if messages else ""


def _last_message(state: QAState):
    return state["messages"][-1]


def build_graph(model=None, tools=None):
    """Compile a QA graph.

    `model` and `tools` are injectable so tests can run without real LLM or
    network access. When `model` is omitted, the real DeepSeek model is built
    lazily on first non-blocked model call, not at import time.
    """
    selected_tools = ALL_TOOLS if tools is None else tools
    holder = {"model": model}

    def get_model():
        if holder["model"] is None:
            holder["model"] = build_tool_model(selected_tools)
        return holder["model"]

    def policy_gate(state: QAState):
        result = policy.check_question(_last_user_text(state["messages"]))
        if not result.allowed:
            return {"messages": [AIMessage(content=policy.REFUSAL_MESSAGE)],
                    "blocked": True}
        return {"blocked": False}

    def after_policy(state: QAState) -> Literal["agent", "__end__"]:
        return END if state.get("blocked") else "agent"

    def call_model(state: QAState):
        response = get_model().invoke([SystemMessage(content=SYSTEM_PROMPT)] + state["messages"])
        return {"messages": [response]}

    def after_agent(state: QAState) -> Literal["tools", "final_policy"]:
        last = _last_message(state)
        return "tools" if getattr(last, "tool_calls", None) else "final_policy"

    def final_policy(state: QAState):
        checked = policy.check_answer(_content(_last_message(state)))
        if checked != _content(_last_message(state)):
            return {"messages": [AIMessage(content=checked)]}
        return {}

    builder = StateGraph(QAState)
    builder.add_node("policy", policy_gate)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(selected_tools))
    builder.add_node("final_policy", final_policy)
    builder.add_edge(START, "policy")
    builder.add_conditional_edges("policy", after_policy)
    builder.add_conditional_edges("agent", after_agent)
    builder.add_edge("tools", "agent")
    builder.add_edge("final_policy", END)
    return builder.compile()


def ask(question: str, compiled_graph=None) -> str:
    """Run one local QA turn and return the final answer text."""
    active_graph = compiled_graph or graph
    result = active_graph.invoke({
        "messages": [HumanMessage(content=question)],
        "blocked": False,
    })
    return _content(result["messages"][-1])


def stream(question: str, compiled_graph=None) -> Iterator[dict]:
    """Stream one local QA turn for debugging."""
    active_graph = compiled_graph or graph
    yield from active_graph.stream({
        "messages": [HumanMessage(content=question)],
        "blocked": False,
    }, stream_mode="updates")


graph = build_graph()
