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


from backend.tools import watchlist_tools as wt
from backend.tools import market_tools as mt
from backend.services import watchlist_service as wsvc
from backend.services import market_service as msvc


def test_watchlist_tools_forward(monkeypatch):
    monkeypatch.setattr(wsvc, "list_watchlist", lambda session=None: [{"fund_code": "1"}])
    monkeypatch.setattr(wsvc, "add", lambda code, note="", session=None: {"fund_code": code, "note": note})
    monkeypatch.setattr(wsvc, "remove", lambda code, session=None: {"fund_code": code, "removed": True})
    monkeypatch.setattr(wsvc, "update_note", lambda code, note, session=None: {"fund_code": code, "note": note})

    assert wt.get_watchlist.invoke({}) == [{"fund_code": "1"}]
    assert wt.add_fund_to_watchlist.invoke({"fund_code": "110011", "note": "x"})["note"] == "x"
    assert wt.remove_fund_from_watchlist.invoke({"fund_code": "110011"})["removed"] is True
    assert wt.update_fund_note.invoke({"fund_code": "110011", "note": "y"})["note"] == "y"


def test_market_tools_forward(monkeypatch):
    monkeypatch.setattr(msvc, "get_indices", lambda session=None: {"indices": [], "source": "akshare"})
    monkeypatch.setattr(msvc, "refresh_market", lambda session=None: {"inserted": 3, "source": "akshare"})
    assert mt.get_market_indices.invoke({})["source"] == "akshare"
    assert mt.refresh_market.invoke({})["inserted"] == 3


def test_tool_lists_exposed(monkeypatch):
    assert {t.name for t in wt.WATCHLIST_TOOLS} == {
        "get_watchlist", "add_fund_to_watchlist",
        "remove_fund_from_watchlist", "update_fund_note"}
    assert {t.name for t in mt.MARKET_TOOLS} == {"get_market_indices", "refresh_market"}


def test_fund_basic_info_tool(monkeypatch):
    monkeypatch.setattr(fs, "get_basic_info",
                        lambda code, session=None: {"fund_code": code, "fund_name": "FundA",
                                                    "source": "akshare"})
    out = fund_tools.get_fund_basic_info.invoke({"fund_code": "110011"})
    assert out["fund_name"] == "FundA"


def test_fund_nav_history_tool(monkeypatch):
    monkeypatch.setattr(fs, "get_nav_history",
                        lambda code, start_date="", end_date="", session=None: {
                            "fund_code": code, "navs": [], "count": 0,
                            "start": start_date, "end": end_date, "source": "akshare"})
    out = fund_tools.get_fund_nav_history.invoke(
        {"fund_code": "110011", "start_date": "2026-06-01", "end_date": "2026-06-30"})
    assert out["start"] == "2026-06-01" and out["end"] == "2026-06-30"


def test_refresh_fund_tool(monkeypatch):
    monkeypatch.setattr(fs, "refresh_fund",
                        lambda code, session=None: {"fund_code": code, "navs_inserted": 5,
                                                    "source": "akshare"})
    assert fund_tools.refresh_fund.invoke({"fund_code": "110011"})["navs_inserted"] == 5


def test_all_tools_aggregate_has_11_unique():
    names = [t.name for t in fund_tools.ALL_TOOLS]
    assert len(names) == 11
    assert len(set(names)) == 11  # no name collisions
    assert set(names) == {
        "get_latest_fund_nav", "calculate_fund_metrics", "get_fund_basic_info",
        "get_fund_nav_history", "refresh_fund", "get_watchlist",
        "add_fund_to_watchlist", "remove_fund_from_watchlist", "update_fund_note",
        "get_market_indices", "refresh_market"}
