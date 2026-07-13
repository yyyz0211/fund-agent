from backend.tools import fund_tools
from backend.services import fund_service as fs
from backend.services import diagnosis_service as ds


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
from backend.services import cls_telegraph_client as cls_client
from backend.config.settings import get_settings


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
    assert {t.name for t in mt.MARKET_TOOLS} == {
        "get_market_indices", "refresh_market",
        "get_market_snapshot_auto", "get_sector_heatmap",
        "get_latest_market_brief", "search_market_evidence",
        "search_cls_telegraph",
        "get_market_briefing",
    }


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


def test_diagnose_fund_tool(monkeypatch):
    monkeypatch.setattr(ds, "diagnose_fund", lambda code, period="1y", session=None: {
        "fund_code": code,
        "period": period,
        "decision_label": "观察",
        "source": "akshare",
        "as_of": "2026-07-02",
    })

    out = fund_tools.diagnose_fund.invoke({"fund_code": "110011", "period": "1y"})

    assert out["decision_label"] == "观察"


def test_lookup_fund_auto_tool(monkeypatch):
    monkeypatch.setattr(fs, "lookup_fund_auto",
                        lambda code, period="1y", refresh_policy="if_missing_or_stale",
                        session=None: {
                            "fund_code": code,
                            "period": period,
                            "refresh": {"attempted": True, "reason": "missing_nav"},
                            "source": "akshare",
                        })

    out = fund_tools.lookup_fund_auto.invoke(
        {"fund_code": "110011", "period": "1y"})

    assert out["refresh"]["attempted"] is True
    assert out["source"] == "akshare"


def test_diagnose_fund_auto_tool(monkeypatch):
    monkeypatch.setattr(fs, "diagnose_fund_auto",
                        lambda code, period="1y", refresh_policy="if_missing_or_stale",
                        session=None: {
                            "fund_code": code,
                            "period": period,
                            "decision_label": "观察",
                            "refresh": {"attempted": False, "reason": None},
                            "source": "akshare",
                        })

    out = fund_tools.diagnose_fund_auto.invoke(
        {"fund_code": "110011", "period": "1y"})

    assert out["decision_label"] == "观察"
    assert out["refresh"]["attempted"] is False


def test_search_cls_telegraph_tool_forwards_to_client(monkeypatch):
    monkeypatch.setenv("CLS_SEARCH_ENABLED", "true")
    monkeypatch.setenv("CLS_MAX_SEARCH_LIMIT", "3")
    get_settings.cache_clear()

    def fake_search_telegraph(**kwargs):
        assert kwargs["keyword"] == "基金"
        assert kwargs["category"] == "fund"
        assert kwargs["limit"] == 3
        return [{
            "title": "基金快讯",
            "summary": "摘要",
            "published_at": "2026-07-08 11:31:46",
            "source": "财联社",
            "source_url": "https://www.cls.cn/detail/1",
            "symbols": ["基金"],
            "metrics": {"cls_id": 1},
        }]

    monkeypatch.setattr(cls_client, "search_telegraph", fake_search_telegraph)

    out = mt.search_cls_telegraph.invoke({"keyword": "基金", "category": "fund", "limit": 99})

    assert out["count"] == 1
    assert out["items"][0]["title"] == "基金快讯"
    assert out["error"] == ""


def test_search_cls_telegraph_tool_strips_raw_fields(monkeypatch):
    monkeypatch.setenv("CLS_SEARCH_ENABLED", "true")
    get_settings.cache_clear()

    def fake_search_telegraph(**kwargs):
        return [{
            "title": "基金快讯",
            "summary": "摘要",
            "published_at": "2026-07-08 11:31:46",
            "source": "财联社",
            "source_url": "https://www.cls.cn/detail/1",
            "symbols": ["基金"],
            "metrics": {"cls_id": 1},
            "raw": {"content": "不应进入工具返回"},
        }]

    monkeypatch.setattr(cls_client, "search_telegraph", fake_search_telegraph)

    out = mt.search_cls_telegraph.invoke({"keyword": "基金"})

    assert "raw" not in out["items"][0]
    assert set(out["items"][0]) == {
        "title", "summary", "published_at", "source",
        "source_url", "symbols", "metrics",
    }


def test_search_cls_telegraph_tool_respects_disable(monkeypatch):
    monkeypatch.setenv("CLS_SEARCH_ENABLED", "false")
    get_settings.cache_clear()

    out = mt.search_cls_telegraph.invoke({"keyword": "基金"})

    assert out["count"] == 0
    assert out["items"] == []
    assert out["error"] == "CLS search disabled"


def test_get_market_briefing_passes_brief_type(monkeypatch):
    from backend.services import briefing_service

    captured = {}

    def fake_read_briefing(brief_date=None, brief_type="post_market"):
        captured["brief_date"] = brief_date
        captured["brief_type"] = brief_type
        return {"briefing_date": brief_date, "brief_type": brief_type}

    monkeypatch.setattr(briefing_service, "read_briefing", fake_read_briefing)

    out = mt.get_market_briefing.invoke({
        "brief_date": "2026-07-09",
        "brief_type": "pre_market",
    })

    assert captured == {"brief_date": "2026-07-09", "brief_type": "pre_market"}
    assert out["briefing"]["brief_type"] == "pre_market"


def test_all_tools_aggregate_has_unique_set():
    # 8 fund + 4 watchlist + 8 market + 1 pnl + 1 what_if = 22
    names = [t.name for t in fund_tools.ALL_TOOLS]
    assert len(names) == len(set(names))  # no name collisions
    assert set(names) == {
        "get_latest_fund_nav", "calculate_fund_metrics", "get_fund_basic_info",
        "get_fund_nav_history", "refresh_fund", "diagnose_fund",
        "lookup_fund_auto", "diagnose_fund_auto", "get_watchlist",
        "add_fund_to_watchlist", "remove_fund_from_watchlist", "update_fund_note",
        "get_market_indices", "refresh_market",
        "get_market_snapshot_auto", "get_sector_heatmap",
        "get_latest_market_brief", "search_market_evidence",
        "search_cls_telegraph",
        "get_market_briefing",
        "calculate_holding_pnl",
        "what_if_analysis",
    }
