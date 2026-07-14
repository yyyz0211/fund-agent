"""collect_market_intel payload 包含 stale_fields 标记的单测。"""
from contextlib import ExitStack
from unittest.mock import patch

from backend.services.market import market_intel_service as svc


def _patch_collect(return_values: dict):
    stack = ExitStack()
    for name, ret in return_values["dc"].items():
        stack.enter_context(patch.object(svc.dc, name, return_value=ret))
    stack.enter_context(patch.object(svc.market_service, "get_indices",
                                     return_value=return_values["get_indices"]))
    return stack


def _default_patches(industry=None, concept=None):
    return {
        "dc": {
            "fetch_market_breadth": {
                "up": 100, "down": 100, "limit_up": 0, "limit_down": 0,
                "volume": 0, "amount": 0, "total": 200, "source": "akshare", "as_of": "2026-07-08",
            },
            "fetch_sector_snapshot": industry if industry is not None else [
                {"name": "电子", "change_pct": 0.5, "source": "akshare"},
            ],
            "fetch_industry_flows": [{"name": "电子", "net_flow": 1000.0, "source": "akshare"}],
            "fetch_concept_sectors": concept if concept is not None else [
                {"name": "AI", "change_pct": 1.0, "source": "akshare"},
            ],
            "fetch_concept_flows": [{"name": "AI", "net_flow": 500.0, "source": "akshare"}],
            "fetch_theme_boards": [{"theme": "AI", "count": 5, "stocks": [], "source": "akshare"}],
            "fetch_breadth_indicators": {"board_height": [], "source": "akshare", "as_of": "2026-07-08"},
            "fetch_overseas_markets": [{"market": "US", "name": "SPX", "symbol": "SPX",
                                        "close": 5000.0, "change_pct": 0.5, "source": "akshare", "as_of": "2026-07-08"}],
            "fetch_announcements": [{"title": "公告 A", "ann_date": "2026-07-08",
                                     "fund_code": "000001", "fund_name": "测试", "source": "akshare"}],
            # Task 3 注入的 history 调用:避免测试命中真实 akshare 接口
            "fetch_index_history": [],
            "fetch_sector_history": [],
        },
        "get_indices": {
            "indices": [{"symbol": "000001", "name": "上证指数", "close": 3000.0,
                         "change_pct": 0.5, "market_date": "2026-07-08", "source": "akshare"}],
            "source": "akshare", "as_of": "2026-07-08",
        },
    }


def test_stale_fields_mark_empty_sectors():
    """industry/concept 都返回空时,stale_fields 应标记这两个字段。"""
    with _patch_collect(_default_patches(industry=[], concept=[])):
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    assert payload["stale_fields"]["industry_sectors"] is True
    assert payload["stale_fields"]["concept_sectors"] is True
    assert payload["industry_sectors"] == []
    assert payload["concept_sectors"] == []


def test_stale_fields_partial_failure():
    """industry 有数据, concept 无 — 只 concept 标记 stale。"""
    with _patch_collect(_default_patches(industry=[{"name": "电子", "change_pct": 0.5, "source": "akshare"}], concept=[])):
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    assert payload["stale_fields"]["industry_sectors"] is False
    assert payload["stale_fields"]["concept_sectors"] is True


def test_stale_fields_all_have_data():
    """全部有数据时,所有字段都是 false。"""
    with _patch_collect(_default_patches()):
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    stale = payload["stale_fields"]
    failing = [k for k, v in stale.items() if v is not False]
    assert not failing, f"expected all false, but these are True: {failing} (full: {stale})"


def test_stale_fields_keys_complete():
    """stale_fields 必须覆盖所有 list 字段(防漏)。"""
    with _patch_collect(_default_patches()):
        payload = svc.collect_market_intel(
            trade_date="2026-07-08", snapshot_type="post_market", session=None,
        )
    expected = {"industry_sectors", "concept_sectors", "industry_flows",
                "concept_flows", "themes", "overseas", "announcements"}
    assert expected.issubset(set(payload["stale_fields"].keys()))


def test_stale_fields_individual_fields():
    """每个 list 字段独立标 stale:即便其他字段都有数据,该字段空时仍要标 True。"""
    # 只让 overseas 为空,其他全部有数据
    with _patch_collect(_default_patches(industry=[{"name": "X", "change_pct": 0.5, "source": "akshare"}],
                                         concept=[{"name": "Y", "change_pct": 0.5, "source": "akshare"}])):
        # 覆盖 overseas 为空
        from unittest.mock import patch
        with patch.object(svc.dc, "fetch_overseas_markets", return_value=[]):
            payload = svc.collect_market_intel(
                trade_date="2026-07-08", snapshot_type="post_market", session=None,
            )
    assert payload["stale_fields"]["overseas"] is True
    assert payload["stale_fields"]["industry_sectors"] is False
    assert payload["stale_fields"]["concept_sectors"] is False
    # 其他默认 _default_patches 里都是非空 → False
    assert payload["stale_fields"]["announcements"] is False


def test_stale_fields_announcements_empty():
    """announcements 单独为空时,标 stale,其他字段不影响。"""
    from unittest.mock import patch
    with _patch_collect(_default_patches()):
        with patch.object(svc.dc, "fetch_announcements", return_value=[]):
            payload = svc.collect_market_intel(
                trade_date="2026-07-08", snapshot_type="post_market", session=None,
            )
    assert payload["stale_fields"]["announcements"] is True
    assert payload["stale_fields"]["overseas"] is False


def test_stale_fields_themes_empty():
    """themes 单独为空时标 stale。"""
    from unittest.mock import patch
    with _patch_collect(_default_patches()):
        with patch.object(svc.dc, "fetch_theme_boards", return_value=[]):
            payload = svc.collect_market_intel(
                trade_date="2026-07-08", snapshot_type="post_market", session=None,
            )
    assert payload["stale_fields"]["themes"] is True
