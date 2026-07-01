"""LangGraph QA Graph — Phase 4 主链路模块。

Graph 流程:
  __root__ → pre_check → [LLM with tools] ↔ [ToolNode] → post_check → END

- pre_check: 前置合规拦截，命中禁区直接返回拒答消息并结束。
- LLM: DeepSeek tool-calling model，绑定 ALL_TOOLS。
- ToolNode: LangGraph 内置工具执行节点，自动处理 tool_calls → tool_results。
- post_check: 后置合规检查，回答若含建议性内容，替换为固定拒答。

多轮上下文:可选的 `MemorySaver` checkpointer 让同一个 `thread_id`
的多次 `ask()` / `stream()` 调用把消息累加到同一段对话历史。生产侧
(`langgraph dev` server) 在外部维护自己的 checkpointer,与本进程内
单例互不影响 — 本模块的多轮支持主要服务于:
  1. Phase-4 后端进程内调试入口(ask/stream);
  2. 用 pytest 验证多轮 tool_call 行为时不需要起外部 server。
"""
from __future__ import annotations

from typing import Iterator
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from backend.config.settings import get_settings
from backend.graph.policy import check_question, check_answer, REFUSAL_MESSAGE
from backend.graph.model import build_model
from backend.tools.fund_tools import ALL_TOOLS


# ─── Graph state ──────────────────────────────────────────────────────────────

from langgraph.graph import MessagesState
from langgraph.errors import GraphRecursionError
from langgraph.checkpoint.memory import MemorySaver

# Alias for test and external use
QAState = MessagesState


# ─── Nodes ────────────────────────────────────────────────────────────────────

def _pre_check(state: MessagesState) -> MessagesState:
    """前置合规:检查用户问题是否触及禁区。

    命中禁区 → 追加拒答消息，直接路由到 END。
    """
    last_msg = state["messages"][-1]
    if not isinstance(last_msg, HumanMessage):
        # 非首轮消息跳过 pre-check（只有用户输入才检查）
        return {}

    if not check_question(last_msg.content):
        return {"messages": [AIMessage(content=REFUSAL_MESSAGE)]}

    return {}


def _llm_node(state: MessagesState) -> dict:
    """LLM 节点:使用 DeepSeek + ALL_TOOLS 处理消息，返回 AI 响应。

    返回 dict 以便 LangGraph 用 add_messages 合并到 state["messages"]。
    """
    model = build_model()
    bound = model.bind_tools(ALL_TOOLS)
    response = bound.invoke(state["messages"])
    return {"messages": [response]}


def _post_check(state: MessagesState) -> MessagesState:
    """后置合规:检查 LLM 回答是否合规，不合规则替换为拒答。"""
    last_msg = state["messages"][-1]
    if not isinstance(last_msg, AIMessage):
        return {}

    if last_msg.content and not check_answer(last_msg.content):
        return {"messages": [AIMessage(content=REFUSAL_MESSAGE)]}

    return {}


# ─── Routing ─────────────────────────────────────────────────────────────────

def _route_pre_check(state: MessagesState) -> str:
    """pre_check 之后:拒答 → END，否则 → llm。"""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.content == REFUSAL_MESSAGE:
        return END
    return "llm"


def _route_llm(state: MessagesState) -> str:
    """llm 之后:有 tool_calls → tools，否则 → post_check。"""
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None)
    if tool_calls:
        return "tools"
    return "post_check"


# ─── Graph construction ───────────────────────────────────────────────────────

from langgraph.graph import StateGraph, MessagesState
from langgraph.constants import END
from langgraph.prebuilt import ToolNode


# ─── Tool node (lazy singleton, patchable via _get_tool_node) ──────────────────

_tool_node_singleton: ToolNode | None = None


def _get_tool_node() -> ToolNode:
    """返回 ToolNode 单例（延迟构造，供测试 patch）。"""
    global _tool_node_singleton
    if _tool_node_singleton is None:
        _tool_node_singleton = ToolNode(ALL_TOOLS)
    return _tool_node_singleton


def _build_graph(checkpointer=None):
    """构造并编译 QA Graph（供测试注入 fake model）。

    `checkpointer` 是 LangGraph `BaseCheckpointSaver` 实例;不传则编译出
    的 graph 不带多轮能力(每次 invoke/stream 互相独立)。Phase-4 后端
    默认传 `MemorySaver` 单例,生产端(langgraph dev server)用自己的持久
    checkpointer。
    """
    from langgraph.graph import StateGraph, MessagesState
    from langgraph.constants import END
    from langgraph.prebuilt import ToolNode

    builder = StateGraph(MessagesState)

    builder.add_node("pre_check", _pre_check)
    builder.add_node("llm", _llm_node)
    builder.add_node("tools", _get_tool_node())
    builder.add_node("post_check", _post_check)

    builder.add_edge("__start__", "pre_check")
    builder.add_conditional_edges(
        "pre_check",
        _route_pre_check,
        {
            "llm": "llm",
            END: END,
        },
    )
    # llm 之后直接判断是否有 tool_calls，避免无 tool_calls 时也经过 tools 节点
    builder.add_conditional_edges(
        "llm",
        _route_llm,
        {
            "tools": "tools",
            "post_check": "post_check",
        },
    )
    builder.add_edge("tools", "llm")  # tools 完成后直接回 llm
    builder.add_edge("post_check", END)

    return builder.compile(checkpointer=checkpointer)


# ─── Compiled graph (singleton per process) ───────────────────────────────────

# 进程级 MemorySaver 单例 —— 只要进程不重启,任何 thread_id 的检查点
# 都在此 saver 里;多线程时 saver 内部用锁。
_memory_saver: MemorySaver | None = None


def _get_memory_saver() -> MemorySaver:
    global _memory_saver
    if _memory_saver is None:
        _memory_saver = MemorySaver()
    return _memory_saver


_graph = None


def _get_graph():
    """取得带 checkpointer 的 QA Graph 单例。

    首次访问时用 `MemorySaver` 编译;测试可通过 `reset_graph()` 注入
    `checkpointer=None` 或别的 saver,实现 thread 隔离。
    """
    global _graph
    if _graph is None:
        _graph = _build_graph(checkpointer=_get_memory_saver())
    return _graph


def reset_graph():
    """清空进程级 graph 与 checkpointer 单例(给测试用)。"""
    global _graph, _memory_saver
    _graph = None
    _memory_saver = None


# ─── Public API ───────────────────────────────────────────────────────────────

graph = _get_graph()


# 每次提问允许的最大"tools → llm → tools"循环轮数。
# 一轮 = 一次工具调用 + 一次 LLM 总结。超过则抛 GraphRecursionError,
# 由上层 / 前端用兜底消息承接。默认值偏低是有意为之:正常问题
# 1-2 轮就结束,8 轮已经非常宽裕;>8 几乎肯定是 LLM 卡死重试。
DEFAULT_RECURSION_LIMIT = 8


def _with_recursion_limit(config: dict | None) -> dict:
    """把 `recursion_limit` 合入用户传入的 config,缺省用 `DEFAULT_RECURSION_LIMIT`。

    下限保护:如果调用方显式传了一个小于 `MIN_RECURSION_LIMIT` 的值,
    提高到下限 —— 防止误把上限设成 1 导致所有问题都立刻 GraphRecursionError。
    """
    base = dict(config) if config else {}
    base.setdefault("recursion_limit", DEFAULT_RECURSION_LIMIT)
    if base["recursion_limit"] < MIN_RECURSION_LIMIT:
        base["recursion_limit"] = MIN_RECURSION_LIMIT
    return base


# 最小有效 recursion_limit:低于 3 会破坏正常 tool_call 流程(至少
# tool → llm → tool 一次往返)。测试可用更大值放宽。
MIN_RECURSION_LIMIT = 3


def _make_run_config(thread_id: str | None, base_config: dict | None) -> dict:
    """拼装 invoke/stream 的 LangGraph config:thread_id + recursion_limit。

    `thread_id` 不传时用 `uuid4()` 兜底,这样默认调用与改造前行为一致
    (同进程同次 call,thread 唯一;但 ask() 完之后 thread 仍然留在
    MemorySaver 里,后续带同一 thread_id 再问会续上)。
    """
    cfg = _with_recursion_limit(base_config)
    configurable = dict(cfg.get("configurable", {}))
    configurable.setdefault("thread_id", thread_id or uuid4().hex)
    cfg["configurable"] = configurable
    return cfg


def ask(question: str, *, thread_id: str | None = None, config: dict | None = None) -> str:
    """本地一次性问答入口。

    参数:
        question: 用户提问（中文）。
        thread_id: 可选,LangGraph checkpointer 的会话 ID。同一 thread_id
                重复调用会把历史 messages 拼起来,LLM 看到完整对话。传
                `None` 时每次都生成新 thread(单次对话语义不变)。
        config: 可选,LangGraph ConfigurableField(如 thread_id)与
                `recursion_limit`(默认 `DEFAULT_RECURSION_LIMIT`)。
                如果同时传 `thread_id` 和 `config["configurable"]["thread_id"]`,
                以 `thread_id` 形参为准。

    返回:
        graph 最终输出的 AI 回答文本（不含 tool_calls）。
        触发合规边界时返回固定拒答文本。
        命中工具调用次数上限时,降级返回一条说明消息,不抛异常给调用方。
    """
    run_config = _make_run_config(thread_id, config)
    try:
        result = graph.invoke(
            {"messages": [HumanMessage(content=question)]},
            config=run_config,
        )
    except GraphRecursionError:
        return (
            "本轮触达最大工具调用轮数,可能是数据获取循环。"
            "请换一种问法,例如直接给出基金代码和指标。"
        )
    last = result["messages"][-1]
    return last.content if hasattr(last, "content") else str(last)


def stream(
    question: str,
    *,
    thread_id: str | None = None,
    config: dict | None = None,
) -> Iterator[dict]:
    """本地流式调试入口。

    参数:
        question / thread_id / config: 语义同 `ask()`。

    返回:
        Iterator[dict]，每个 chunk 为 LangGraph stream 输出的一层状态，
        结构为 {"messages": [...], ...}。
        chunks 按 LangGraph 内部节点顺序产出。
        命中工具调用次数上限时,产出最后一个 AIMessage 兜底 chunk,
        不让迭代器直接抛 GraphRecursionError 中断调用方。
    """
    run_config = _make_run_config(thread_id, config)
    try:
        for chunk in graph.stream(
            {"messages": [HumanMessage(content=question)]},
            config=run_config,
        ):
            yield chunk
    except GraphRecursionError:
        yield {"messages": [AIMessage(content=(
            "本轮触达最大工具调用轮数,可能是数据获取循环。"
            "请换一种问法,例如直接给出基金代码和指标。"
        ))]}
