"""collect_market_intel 把 history 注入 payload 的单测。"""
from contextlib import ExitStack
from unittest.mock import patch, MagicMock

from backend.services.market import market_intel_service as svc
from backend.services.market import market_service as ms


def _patch_collect(return_values: dict):
    """一次性 patch 所有 fetch_* 函数 + market_service.get_indices,简化测试 setup。"""
    stack = ExitStack()
    for name, ret in return_values["dc"].items():
        stack.enter_context(patch.object(svc.dc, name, return_value=ret))
    stack.enter_context(patch.object(svc.market_service, "get_indices",
                                     return_value=return_values["get_indices"]))
    return stack


def _default_patches():
    return {
        "dc": {
            "fetch_market_breadth": {
                "up": 1, "down": 0, "limit_up": 0, "limit_down": 0,
                "volume": 0, "amount": 0, "total": 1, "source": "akshare", "as_of": "2026-07-08",
            },
            "fetch_sector_snapshot": [],
            "fetch_industry_flows": [],
            "fetch_concept_sectors": [],
            "fetch_concept_flows": [],
            "fetch_theme_boards": [],
            "fetch_breadth_indicators": {"board_height": [], "source": "akshare", "as_of": "2026-07-08"},
            "fetch_overseas_markets": [],
            "fetch_announcements": [],
        },
        "get_indices": {
            "indices": [
                {"symbol": "000001", "name": "上证指数", "close": 3000.0,
                 "change_pct": 0.5, "market_date": "2026-07-08", "source": "akshare"},
            ],
            "source": "akshare", "as_of": "2026-07-08",
        },
    }


def test_indices_have_history():
    with _patch_collect(_default_patches()), \
         patch.object(svc.dc, "fetch_index_history", return_value=[
             {"date": "2026-07-07", "close": 2990.0, "source": "akshare"},
             {"date": "2026-07-08", "close": 3000.0, "source": "akshare"},
         ]):
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    assert len(payload["indices"]) == 1
    assert payload["indices"][0]["history"] == [2990.0, 3000.0]


def test_industry_sectors_have_history():
    patches = _default_patches()
    patches["dc"]["fetch_sector_snapshot"] = [
        {"name": "电子", "change_pct": 0.5, "source": "akshare"},
    ]
    with _patch_collect(patches), \
         patch.object(svc.dc, "fetch_sector_history", return_value=[
             {"date": "2026-07-07", "change_pct": 0.3, "source": "akshare"},
             {"date": "2026-07-08", "change_pct": 0.5, "source": "akshare"},
         ]) as m_hist:
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    assert payload["industry_sectors"][0]["history"] == [0.3, 0.5]
    args, _ = m_hist.call_args
    assert args[0] == "电子"
    assert args[1] == "industry"


def test_concept_sectors_have_history():
    patches = _default_patches()
    patches["dc"]["fetch_concept_sectors"] = [
        {"name": "AI算力", "change_pct": 1.2, "source": "akshare"},
    ]
    with _patch_collect(patches), \
         patch.object(svc.dc, "fetch_sector_history", return_value=[
             {"date": "2026-07-08", "change_pct": 1.2, "source": "akshare"},
         ]) as m_hist:
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    assert payload["concept_sectors"][0]["history"] == [1.2]
    args, _ = m_hist.call_args
    assert args[0] == "AI算力"
    assert args[1] == "concept"


def test_history_failure_does_not_block_payload():
    with _patch_collect(_default_patches()), \
         patch.object(svc.dc, "fetch_index_history",
                      return_value={"error": "boom", "source": "akshare"}):
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    assert payload["indices"][0].get("history") is None
    assert any(e["field"].startswith("index_history:") for e in payload["errors"])


def test_history_partial_failure_some_success():
    """indices 数组中一个成功一个失败,成功的有 history,失败的为 None。"""
    patches = _default_patches()
    patches["get_indices"]["indices"] = [
        {"symbol": "000001", "name": "上证指数", "close": 3000.0,
         "change_pct": 0.5, "market_date": "2026-07-08", "source": "akshare"},
        {"symbol": "399001", "name": "深证成指", "close": 10000.0,
         "change_pct": 0.3, "market_date": "2026-07-08", "source": "akshare"},
    ]

    def fake_history(symbol, days=30):
        if symbol == "000001":
            return [{"date": "2026-07-08", "close": 3000.0, "source": "akshare"}]
        return {"error": f"fail for {symbol}", "source": "akshare"}

    with _patch_collect(patches), \
         patch.object(svc.dc, "fetch_index_history", side_effect=fake_history):
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    by_sym = {i["symbol"]: i for i in payload["indices"]}
    assert by_sym["000001"]["history"] == [3000.0]
    assert by_sym["399001"].get("history") is None


def test_payload_includes_stale_fields_key():
    """payload 始终包含 stale_fields(防漏,前端 SectorTabbedTable 依赖)。"""
    with _patch_collect(_default_patches()):
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    assert "stale_fields" in payload
    assert isinstance(payload["stale_fields"], dict)
    # _default_patches 下所有字段都是空 → 全部 True
    assert all(v is True for v in payload["stale_fields"].values())
