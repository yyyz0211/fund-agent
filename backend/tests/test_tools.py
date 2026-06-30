from backend.tools import fund_tools
from backend.services import fund_service as fs


def test_latest_nav_tool_invokes_service(monkeypatch):
    monkeypatch.setattr(fs, "get_latest_nav",
                        lambda code, session=None: {"fund_code": code,
                                                    "accumulated_nav": 1.23,
                                                    "source": "akshare"})
    out = fund_tools.get_latest_fund_nav.invoke({"fund_code": "110011"})
    assert out["accumulated_nav"] == 1.23
    assert out["source"] == "akshare"


def test_metrics_tool_invokes_service(monkeypatch):
    monkeypatch.setattr(fs, "get_metrics",
                        lambda code, period="1m", session=None: {
                            "fund_code": code, "period": period,
                            "max_drawdown": -0.08, "source": "akshare"})
    out = fund_tools.calculate_fund_metrics.invoke(
        {"fund_code": "110011", "period": "1m"})
    assert out["max_drawdown"] == -0.08


def test_tools_list_exposes_both():
    names = {t.name for t in fund_tools.TOOLS}
    assert names == {"get_latest_fund_nav", "calculate_fund_metrics"}
