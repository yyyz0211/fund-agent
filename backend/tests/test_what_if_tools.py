"""what_if_analysis 工具薄包装测试。

策略:
- 测试工具对象的 LangChain 元数据(name / description / args schema)
  不被未来重构意外破坏。
- 测试工具转发参数正确(用一个 session test double 通过 monkeypatch
  替换 backend.db.session.get_session)。
- 不测试 what_if_service.backtest 的算法 —— 已在 test_what_if_service.py。
"""
import pytest

from backend.tools.what_if_tools import what_if_analysis, WHAT_IF_TOOLS

pytestmark = pytest.mark.unit


def test_tool_is_registered():
    """WHAT_IF_TOOLS 应只含一个工具:what_if_analysis。"""
    assert len(WHAT_IF_TOOLS) == 1
    assert WHAT_IF_TOOLS[0] is what_if_analysis


def test_tool_name_and_description_present():
    """LangChain 工具必须有 name + description,否则 LLM 不会调用。"""
    assert what_if_analysis.name == "what_if_analysis"
    desc = what_if_analysis.description
    assert desc is not None and len(desc) > 50
    # 必须明示"历史回测"语义
    assert "回测" in desc
    # 必须告知 LLM 不要在"现在能不能买"场景调用(防止误用)
    assert "diagnose_fund" in desc


def test_tool_forwards_args_to_service(monkeypatch):
    """工具调用应该把参数原样转给 what_if_service.backtest。"""
    captured = {}

    def fake_backtest(session, *, start_date, end_date, holdings):
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["holdings"] = holdings
        captured["session"] = session
        return {"echo": True, "start_date": start_date}

    # 服务已被 mock；session 只需验证透传和关闭语义。
    fake_session = type("FakeSession", (), {"close": lambda self: None})()

    monkeypatch.setattr("backend.tools.what_if_tools.get_session",
                        lambda: fake_session)
    monkeypatch.setattr("backend.tools.what_if_tools.wsvc.backtest",
                        fake_backtest)

    # 直接调 invoke 走 LangChain 工具协议
    result = what_if_analysis.invoke({
        "start_date": "2026-01-01",
        "end_date": "2026-06-01",
        "holdings": {"A": 0.6, "B": 0.4},
    })

    assert captured["start_date"] == "2026-01-01"
    assert captured["end_date"] == "2026-06-01"
    assert captured["holdings"] == {"A": 0.6, "B": 0.4}
    assert captured["session"] is fake_session
    assert result == {"echo": True, "start_date": "2026-01-01"}
    fake_session.close()


def test_tool_closes_session_even_on_error(monkeypatch):
    """服务抛错时,工具的 try/finally 必须关闭 session,避免连接泄漏。"""
    closed = {"flag": False}
    fake_session = type("FakeSession", (), {
        "close": lambda self: closed.__setitem__("flag", True),
    })()

    def fake_backtest(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("backend.tools.what_if_tools.get_session",
                        lambda: fake_session)
    monkeypatch.setattr("backend.tools.what_if_tools.wsvc.backtest",
                        fake_backtest)

    with pytest.raises(RuntimeError, match="boom"):
        what_if_analysis.invoke({
            "start_date": "2026-01-01",
            "end_date": "2026-06-01",
            "holdings": {"A": 1.0},
        })

    assert closed["flag"] is True, "session.close() must be called in finally"
