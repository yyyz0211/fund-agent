"""LangGraph QA graph 离线测试:使用 fake model / fake tool，不调真实 LLM、不联网。

测试策略:patch `backend.graph.qa_graph.build_model` 返回 fake model。
这样 `_llm_node` 仍使用真实签名，但底层 LLM 已被替换。
"""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from backend.graph.policy import REFUSAL_MESSAGE
from backend.graph.qa_graph import _build_graph


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
