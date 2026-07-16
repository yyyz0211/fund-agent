"""Briefing snapshot collector characterization tests."""
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Task 2: collect_watchlist_snapshot
# ---------------------------------------------------------------------------

class TestCollectWatchlistSnapshot:
    """数据收集:指数 + 自选池 metrics。"""

    def test_collect_returns_market_and_watchlist_metrics(self):
        """mock market + watchlist + fund_service,断言返回结构正确。"""
        from backend.services.briefing import collectors

        market_rows = [
            {"symbol": "000300", "name": "沪深300", "close": 3800.0, "change_pct": 0.5,
             "market_date": "2026-07-07", "source": "akshare"},
            {"symbol": "000001", "name": "上证指数", "close": 3200.0, "change_pct": 0.3,
             "market_date": "2026-07-07", "source": "akshare"},
        ]
        watchlist_rows = [
            {"fund_code": "110011", "fund_name": "易方达蓝筹精选"},
            {"fund_code": "000001", "fund_name": "平安领先"},
            {"fund_code": "001594", "fund_name": "东财券商指数"},
        ]
        fund_metrics_1d = {"period": "1d", "period_return": -0.02, "nav_date": "2026-07-07"}
        fund_metrics_1w = {"period": "1w", "period_return": 0.05}
        fund_metrics_1m = {"period": "1m", "period_return": 0.08}

        def mock_get_indices():
            return {"indices": market_rows, "source": "akshare", "as_of": "2026-07-07"}

        def mock_get_breadth():
            return {"up": 3200, "down": 1500, "limit_up": 71, "limit_down": 12,
                    "volume": 9800.0, "amount": 10200.0, "total": 4700,
                    "source": "akshare", "as_of": "2026-07-07"}

        def mock_get_sectors():
            return [
                {"name": "医疗服务", "change_pct": 3.2, "source": "akshare"},
                {"name": "煤炭开采", "change_pct": -1.5, "source": "akshare"},
            ]

        def mock_industry_flows():
            return [{"name": "银行", "net_flow": 50000.0}]

        def mock_concept_sectors():
            return [{"name": "AI概念", "change_pct": 4.5, "source": "akshare"}]

        def mock_concept_flows():
            return [{"name": "AI概念", "net_flow": 20000.0}]

        def mock_list_watchlist(**_kwargs):
            return watchlist_rows

        def mock_get_metrics(fund_code, period, **_kwargs):
            if period == "1d":
                return fund_metrics_1d
            elif period == "1w":
                return fund_metrics_1w
            else:
                return fund_metrics_1m

        with patch.object(collectors, "_collect_market_snapshot", mock_get_indices), \
             patch.object(collectors, "_collect_market_breadth", mock_get_breadth), \
             patch.object(collectors, "_collect_sector_snapshot", mock_get_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_industry_flows", mock_industry_flows), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_sectors", mock_concept_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_flows", mock_concept_flows), \
             patch("backend.services.briefing.collectors.watchlist_service.list_watchlist", mock_list_watchlist), \
             patch("backend.services.briefing.collectors.fund_service.get_metrics", mock_get_metrics):

            result = collectors.collect_watchlist_snapshot()

        assert "market_snapshot" in result
        assert "market_breadth" in result
        assert "sector_snapshot" in result
        assert "watchlist_changes" in result
        assert "errors" in result
        assert "collect_meta" in result
        assert len(result["market_snapshot"]) == 2
        assert len(result["watchlist_changes"]) == 3
        assert result["errors"] == []
        assert result["collect_meta"]["max_funds_applied"] is None  # 未超限额
        # Phase A++ 新字段
        assert result["market_breadth"]["up"] == 3200
        assert result["market_breadth"]["limit_up"] == 71
        assert len(result["sector_snapshot"]) == 2
        assert "industry_flows" in result
        assert "concept_sectors" in result
        assert "concept_flows" in result
        assert result["industry_flows"][0]["name"] == "银行"

    def test_collect_skips_failed_fund_continues_loop(self):
        """单只 fund 抛异常:记 errors,后续继续处理。"""
        from backend.services.briefing import collectors

        def mock_get_indices():
            return {"indices": [], "source": "akshare", "as_of": "2026-07-07"}

        def mock_get_breadth():
            return {"up": 0, "down": 0, "limit_up": 0, "limit_down": 0,
                    "volume": 0.0, "amount": 0.0, "total": 0,
                    "source": "akshare", "as_of": "2026-07-07"}

        def mock_get_sectors():
            return []

        def mock_industry_flows():
            return []

        def mock_concept_sectors():
            return []

        def mock_concept_flows():
            return []

        def mock_list_watchlist(**_kwargs):
            return [
                {"fund_code": "110011", "fund_name": "A"},
                {"fund_code": "000001", "fund_name": "B"},
                {"fund_code": "001594", "fund_name": "C"},
            ]

        call_count = 0

        def mock_get_metrics(fund_code, period, **_kwargs):
            nonlocal call_count
            call_count += 1
            if fund_code == "000001":
                raise ValueError("网络超时")
            return {"period": period, "period_return": 0.01}

        with patch.object(collectors, "_collect_market_snapshot", mock_get_indices), \
             patch.object(collectors, "_collect_market_breadth", mock_get_breadth), \
             patch.object(collectors, "_collect_sector_snapshot", mock_get_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_industry_flows", mock_industry_flows), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_sectors", mock_concept_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_flows", mock_concept_flows), \
             patch("backend.services.briefing.collectors.watchlist_service.list_watchlist", mock_list_watchlist), \
             patch("backend.services.briefing.collectors.fund_service.get_metrics", mock_get_metrics):

            result = collectors.collect_watchlist_snapshot()

        assert len(result["watchlist_changes"]) == 2
        assert result["watchlist_changes"][0]["fund_code"] == "110011"
        assert len(result["errors"]) == 1
        assert result["errors"][0]["fund_code"] == "000001"
        assert result["errors"][0]["stage"] == "collect"
        assert "网络超时" in result["errors"][0]["message"]
        # 每只基金先调 1d,失败则跳整只；2 只全成功=2*3=6,1 只 1d 失败=1 → 共 7
        assert call_count == 7

    def test_collect_caps_max_watchlist_funds(self):
        """自选池超出限额时只采集前 N 只,并在 meta 留 warning。"""
        from backend.services.briefing import collectors

        def mock_get_indices():
            return {"indices": [], "source": "akshare", "as_of": "2026-07-07"}

        def mock_get_breadth():
            return {"up": 0, "down": 0, "limit_up": 0, "limit_down": 0,
                    "volume": 0.0, "amount": 0.0, "total": 0,
                    "source": "akshare", "as_of": "2026-07-07"}

        def mock_get_sectors():
            return []

        def mock_industry_flows():
            return []

        def mock_concept_sectors():
            return []

        def mock_concept_flows():
            return []

        def mock_list_watchlist(**_kwargs):
            return [{"fund_code": f"00{i:04d}", "fund_name": f"基金{i}"}
                    for i in range(1, 11)]

        def mock_get_metrics(fund_code, period, **_kwargs):
            return {"period": period, "period_return": 0.01}

        cap = 3

        with patch.object(collectors, "_collect_market_snapshot", mock_get_indices), \
             patch.object(collectors, "_collect_market_breadth", mock_get_breadth), \
             patch.object(collectors, "_collect_sector_snapshot", mock_get_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_industry_flows", mock_industry_flows), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_sectors", mock_concept_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_flows", mock_concept_flows), \
             patch("backend.services.briefing.collectors.watchlist_service.list_watchlist", mock_list_watchlist), \
             patch("backend.services.briefing.collectors.fund_service.get_metrics", mock_get_metrics), \
             patch("backend.services.briefing.collectors.settings") as mock_settings:

            mock_settings.briefing_max_watchlist_funds = cap
            result = collectors.collect_watchlist_snapshot()

        assert len(result["watchlist_changes"]) == cap
        assert any("截断" in w or "cap" in w.lower()
                   for w in result["collect_meta"].get("warnings", []))

    def test_collect_market_breadth_graceful_fallback(self):
        """_collect_market_breadth 抛异常时 snapshot 仍有 market_breadth={}。"""
        from backend.services.briefing import collectors

        def mock_get_indices():
            return {"indices": [], "source": "akshare", "as_of": "2026-07-07"}

        def mock_get_breadth_fail():
            raise RuntimeError("akshare unavailable")

        def mock_get_sectors():
            return []

        def mock_industry_flows():
            return []

        def mock_concept_sectors():
            return []

        def mock_concept_flows():
            return []

        def mock_list_watchlist(**_kwargs):
            return [{"fund_code": "110011", "fund_name": "A"}]

        def mock_get_metrics(fund_code, period, **_kwargs):
            return {"period": period, "period_return": 0.01}

        with patch.object(collectors, "_collect_market_snapshot", mock_get_indices), \
             patch.object(collectors, "_collect_market_breadth", mock_get_breadth_fail), \
             patch.object(collectors, "_collect_sector_snapshot", mock_get_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_industry_flows", mock_industry_flows), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_sectors", mock_concept_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_flows", mock_concept_flows), \
             patch("backend.services.briefing.collectors.watchlist_service.list_watchlist", mock_list_watchlist), \
             patch("backend.services.briefing.collectors.fund_service.get_metrics", mock_get_metrics):

            result = collectors.collect_watchlist_snapshot()

        # breadth 因异常返回 {}，但 snapshot 仍然成功返回（graceful degradation）
        assert result["market_breadth"] == {}
        assert result["sector_snapshot"] == []
        assert result["watchlist_changes"][0]["fund_code"] == "110011"

    def test_collect_sector_snapshot_empty_is_valid(self):
        """sector_snapshot 为空时 snapshot 仍成功（当日可能无板块数据）。"""
        from backend.services.briefing import collectors

        def mock_get_indices():
            return {"indices": [{"symbol": "000001", "name": "上证指数",
                                  "close": 3200.0, "change_pct": 0.5,
                                  "market_date": "2026-07-07", "source": "akshare"}],
                    "source": "akshare", "as_of": "2026-07-07"}

        def mock_get_breadth():
            return {"up": 0, "down": 0, "limit_up": 0, "limit_down": 0,
                    "volume": 0.0, "amount": 0.0, "total": 0,
                    "source": "akshare", "as_of": "2026-07-07"}

        def mock_get_sectors():
            return []  # 空 = 非交易日

        def mock_industry_flows():
            return []

        def mock_concept_sectors():
            return []

        def mock_concept_flows():
            return []

        def mock_list_watchlist(**_kwargs):
            return []

        with patch.object(collectors, "_collect_market_snapshot", mock_get_indices), \
             patch.object(collectors, "_collect_market_breadth", mock_get_breadth), \
             patch.object(collectors, "_collect_sector_snapshot", mock_get_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_industry_flows", mock_industry_flows), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_sectors", mock_concept_sectors), \
             patch("backend.services.briefing.collectors.dc.fetch_concept_flows", mock_concept_flows), \
             patch("backend.services.briefing.collectors.watchlist_service.list_watchlist", mock_list_watchlist):

            result = collectors.collect_watchlist_snapshot()

        assert result["sector_snapshot"] == []
        assert len(result["market_snapshot"]) == 1
        assert result["watchlist_changes"] == []



def test_compute_data_quality_complete_when_core_data_and_evidence_exist():
    from backend.services.briefing.collectors import compute_data_quality

    result = compute_data_quality(
        {
            "market_snapshot": [{"symbol": "000300"}],
            "market_breadth": {"up": 1, "down": 1},
            "industry_sectors": [{"name": "银行"}],
            "errors": [],
            "collect_meta": {"data_sources_last_updated": {"market_snapshot": "now"}},
        },
        [
            {"category": "policy"},
            {"category": "announcement"},
            {"category": "macro"},
        ],
    )

    assert result["data_quality"] == "complete"
    assert result["confidence"] == "high"
    assert result["missing_data"] == []
