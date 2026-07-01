"""LangGraph QA graph 离线测试:使用 fake model / fake tool，不调真实 LLM、不联网。

测试策略:patch `backend.graph.qa_graph.build_model` 返回 fake model。
这样 `_llm_node` 仍使用真实签名，但底层 LLM 已被替换。
"""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from backend.graph.policy import REFUSAL_MESSAGE
from backend.graph.qa_graph import (
    _build_graph,
    DEFAULT_RECURSION_LIMIT,
    ask as qa_ask,
)


def _make_fake_model(responses: list[AIMessage]):
    """返回一个 fake ChatOpenAI，bind_tools() 返回的 runnable 依次返回预设 AIMessage。"""
    responses = list(responses)

    def _next_response(*a, **k):
        return responses.pop(0) if responses else AIMessage(content="?")

    fake_model = MagicMock()
    bound = MagicMock()
    bound.invoke = _next_response
    bound.ainvoke = _next_response
    fake_model.bind_tools = MagicMock(return_value=bound)
    fake_model.invoke = _next_response
    fake_model.ainvoke = _next_response
    return fake_model


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestAskFinalAnswer:
    """ask() 返回最终 AI 回答文本。"""

    def test_ask_returns_final_text(self):
        fake_model = _make_fake_model([
            AIMessage(content="根据工具返回，110011 最新净值为 1.25，数据来源 akshare。"),
        ])
        with patch("backend.graph.qa_graph.build_model", return_value=fake_model):
            compiled = _build_graph()
            result = compiled.invoke(
                {"messages": [HumanMessage(content="110011净值多少")]}
            )
        last = result["messages"][-1]
        assert isinstance(last, AIMessage)
        assert len(last.content) > 0

    def test_ask_refuses_blocked_question(self):
        """合规问题:拦截时直接返回拒答。"""
        fake_model = _make_fake_model([])
        with patch("backend.graph.qa_graph.build_model", return_value=fake_model):
            compiled = _build_graph()
            result = compiled.invoke(
                {"messages": [HumanMessage(content="现在应该买哪只基金")]}
            )
        last = result["messages"][-1]
        assert REFUSAL_MESSAGE in last.content


class TestStream:
    """stream() 产生流式 chunk。"""

    def test_stream_yields_chunks(self):
        fake_model = _make_fake_model([
            AIMessage(content="回答内容。"),
        ])
        with patch("backend.graph.qa_graph.build_model", return_value=fake_model):
            compiled = _build_graph()
            chunks = list(compiled.stream(
                {"messages": [HumanMessage(content="110011净值")]}
            ))
        assert len(chunks) > 0
        # LangGraph stream chunks keyed by node name
        assert all(isinstance(c, dict) and len(c) > 0 for c in chunks)


class TestPolicyPreCheck:
    """合规前置:拦截问题直接返回拒答，不调用 Tool。"""

    def test_blocked_question_skips_tool_call(self):
        """拦截问题 → pre_check 返回拒答 → 路由到 END，不经过 llm。"""
        tool_called = []

        class TrackerTool:
            def invoke(self, state):
                tool_called.append(True)
                return {"messages": []}
            __call__ = invoke

        with patch("backend.graph.qa_graph.build_model",
                   return_value=_make_fake_model([])), \
             patch("backend.graph.qa_graph._get_tool_node", return_value=TrackerTool()):
            compiled = _build_graph()
            result = compiled.invoke(
                {"messages": [HumanMessage(content="现在应该买哪只基金")]}
            )
        last = result["messages"][-1]
        assert REFUSAL_MESSAGE in last.content
        assert len(tool_called) == 0  # tool 从未被调用

    def test_allowed_question_uses_llm(self):
        fake_model = _make_fake_model([
            AIMessage(content="易方达蓝筹最新净值 1.25。"),
        ])
        with patch("backend.graph.qa_graph.build_model", return_value=fake_model):
            compiled = _build_graph()
            result = compiled.invoke(
                {"messages": [HumanMessage(content="易方达蓝筹最新净值是多少")]}
            )
        last = result["messages"][-1]
        assert REFUSAL_MESSAGE not in last.content
        assert "1.25" in last.content


class TestPolicyPostCheck:
    """合规后置:LLM 回答含建议性内容时被替换为拒答。"""

    def test_model_suggestive_answer_blocked_by_post_check(self):
        fake_model = _make_fake_model([
            AIMessage(content="建议您现在买入该基金，收益可期。"),
        ])
        with patch("backend.graph.qa_graph.build_model", return_value=fake_model):
            compiled = _build_graph()
            result = compiled.invoke(
                {"messages": [HumanMessage(content="这只基金怎么样")]}
            )
        last = result["messages"][-1]
        assert REFUSAL_MESSAGE in last.content


class TestToolErrorPropagation:
    """工具 error dict 被如实传递到回答中，不编造数据。"""

    def test_tool_error_preserved_in_answer(self):
        error_msg = ToolMessage(
            content='{"error": "no nav data for 110011; call refresh_fund first", "source": "akshare"}',
            name="get_latest_fund_nav",
            tool_call_id="call_abc",
        )
        fake_model = _make_fake_model([
            AIMessage(tool_calls=[{
                "name": "get_latest_fund_nav",
                "args": {"fund_code": "110011"},
                "id": "call_abc",
            }], content=""),
            AIMessage(content="该基金暂无净值数据，请先调用 refresh_fund。"),
        ])

        class ErrorToolNode:
            def invoke(self, state):
                return {"messages": [error_msg]}
            __call__ = invoke

        with patch("backend.graph.qa_graph.build_model", return_value=fake_model), \
             patch("backend.graph.qa_graph._get_tool_node", return_value=ErrorToolNode()):
            compiled = _build_graph()
            result = compiled.invoke(
                {"messages": [HumanMessage(content="110011净值")]}
            )
        last = result["messages"][-1]
        assert isinstance(last, AIMessage)
        # 回答应提及处理方式，不应有编造的具体净值数字
        assert "refresh" in last.content.lower()
        assert "1.25" not in last.content


class TestToolCallLoop:
    """多轮 tool-call 循环:LLM 发 tool_calls → ToolNode 返回 → LLM 汇总。"""

    def test_single_tool_call_then_summarize(self):
        nav_msg = ToolMessage(
            content='{"fund_code": "110011", "nav_date": "2026-06-30", '
                    '"accumulated_nav": 1.234, "source": "akshare", "as_of": "2026-06-30"}',
            name="get_latest_fund_nav",
            tool_call_id="call_xyz",
        )
        fake_model = _make_fake_model([
            AIMessage(tool_calls=[{
                "name": "get_latest_fund_nav",
                "args": {"fund_code": "110011"},
                "id": "call_xyz",
            }], content=""),
            AIMessage(content="根据工具返回的数据，110011 在 2026-06-30 的累计净值为 1.234，数据来自 akshare。"),
        ])

        class NavToolNode:
            def invoke(self, state):
                return {"messages": [nav_msg]}
            __call__ = invoke

        with patch("backend.graph.qa_graph.build_model", return_value=fake_model), \
             patch("backend.graph.qa_graph._get_tool_node", return_value=NavToolNode()):
            compiled = _build_graph()
            result = compiled.invoke(
                {"messages": [HumanMessage(content="110011 最新净值是多少")]}
            )
        messages = result["messages"]
        # HumanMessage → AIMessage(tool_calls) → ToolMessage → AIMessage(最终)
        assert len(messages) == 4
        assert isinstance(messages[-1], AIMessage)
        assert "1.234" in messages[-1].content
        assert "2026-06-30" in messages[-1].content


class TestRecursionLimit:
    """recursion_limit 兜底:防止 LLM 陷入"工具-重试"死循环。

    真实场景:LuLM 看到 `refresh_fund` 返回 `navs_inserted=0` 时,有
    概率把它当成"上次没真入库",从而反复刷同一只基金。我们加上限保证
    不会无止境烧 token / network,触发时降级返回说明而不是崩溃。
    """

    def test_default_recursion_limit_is_reasonable(self):
        """默认值设得过小(<3)会破坏正常 tool_call 流程,过大(>20)失意义。"""
        assert 3 <= DEFAULT_RECURSION_LIMIT <= 20

    def test_ask_handles_recursion_limit_with_fallback_text(self):
        """ask() 在触发 `recursion_limit` 时降级返回说明,而不是抛异常。"""
        # 模拟连续 20 次 tool_call 的 fake model(超过任何合理上限)。
        fake_model = _make_fake_model([
            AIMessage(tool_calls=[{
                "name": "refresh_fund",
                "args": {"fund_code": "110011"},
                "id": f"call_{i}",
            }], content="")
            for i in range(20)
        ])

        class StubToolNode:
            def __init__(self):
                self.calls = 0

            def invoke(self, state):
                self.calls += 1
                return {"messages": [ToolMessage(
                    content='{"fund_code":"110011","navs_inserted":0,"already_up_to_date":true,"source":"akshare","as_of":"2026-06-30"}',
                    name="refresh_fund",
                    tool_call_id=f"call_{self.calls - 1}",
                )]}

            __call__ = invoke

        stub = StubToolNode()
        with patch("backend.graph.qa_graph.build_model", return_value=fake_model), \
             patch("backend.graph.qa_graph._get_tool_node", return_value=stub):
            # 需要重置单例,因为 ask() 会复用已编译的 graph,
            # 而单例已经注入了真 ALL_TOOLS。
            qa_ask._graph = None  # type: ignore[attr-defined]
            output = qa_ask("110011 最新净值")

        assert isinstance(output, str)
        # 应是降级说明,而不是 LLM 的"?"。
        assert "最大工具调用轮数" in output or "数据获取循环" in output
        # 调用次数在允许范围内被截断,而不是跑满 20 次。
        assert stub.calls <= DEFAULT_RECURSION_LIMIT + 2  # tools+llm 各走一次,±容差
