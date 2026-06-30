from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from backend.graph import qa_graph
from backend.tools.fund_tools import ALL_TOOLS


class _RecordingModel:
    def __init__(self, messages):
        self._messages = list(messages)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return self._messages.pop(0)


class _ExplodingModel:
    calls = 0

    def invoke(self, messages):
        self.calls += 1
        raise AssertionError("model should not be called")


@tool
def fake_lookup(fund_code: str) -> dict:
    """Return fake local fund data."""
    return {"error": f"no nav data for {fund_code}", "source": "akshare"}


def _invoke(compiled_graph, question: str):
    return compiled_graph.invoke({
        "messages": [HumanMessage(content=question)],
        "blocked": False,
    })


def test_build_graph_uses_all_tools_by_default(monkeypatch):
    recorded = {}

    def fake_build_tool_model(tools=None):
        recorded["names"] = [t.name for t in tools]
        return _RecordingModel([AIMessage(content="source=akshare as_of=2026-06-30")])

    monkeypatch.setattr(qa_graph, "build_tool_model", fake_build_tool_model)
    compiled = qa_graph.build_graph()
    _invoke(compiled, "110011 最新净值是多少?")

    assert set(recorded["names"]) == {t.name for t in ALL_TOOLS}


def test_graph_tool_error_is_reflected_without_fabrication():
    model = _RecordingModel([
        AIMessage(content="", tool_calls=[{
            "name": "fake_lookup",
            "args": {"fund_code": "110011"},
            "id": "call_1",
        }]),
        AIMessage(content="本地无 110011 净值数据；source=akshare。"),
    ])
    compiled = qa_graph.build_graph(model=model, tools=[fake_lookup])

    result = _invoke(compiled, "110011 最新净值是多少?")

    assert "本地无 110011 净值数据" in result["messages"][-1].content
    assert "source=akshare" in result["messages"][-1].content
    assert model.calls == 2


def test_graph_blocks_policy_questions_before_model_call():
    model = _ExplodingModel()
    compiled = qa_graph.build_graph(model=model, tools=[])

    result = _invoke(compiled, "110011 可以买入吗?")

    assert result["messages"][-1].content == qa_graph.policy.REFUSAL_MESSAGE
    assert model.calls == 0


def test_stream_yields_chunks():
    model = _RecordingModel([
        AIMessage(content="110011 数据来自 source=akshare, as_of=2026-06-30。")
    ])
    compiled = qa_graph.build_graph(model=model, tools=[])

    chunks = list(qa_graph.stream("110011 最新净值是多少?", compiled_graph=compiled))

    assert chunks
