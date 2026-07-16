"""Market source adapter tests."""
from __future__ import annotations

from unittest.mock import MagicMock


def _response(text: str, status_code: int = 200):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.raise_for_status.side_effect = None if status_code < 400 else Exception("bad")
    return r


def test_policy_adapter_parses_links_to_evidence():
    from backend.integrations.policy import PolicyPageAdapter

    html = """
    <html><body>
      <a href="/news/a.html">国家药监局发布创新药审评政策</a>
      <a href="https://example.gov/b.html">央行发布货币政策报告</a>
    </body></html>
    """
    client = MagicMock()
    client.get.return_value = _response(html)

    adapter = PolicyPageAdapter(
        source="NMPA",
        url="https://www.nmpa.gov.cn/news/index.html",
        reliability="official",
    )
    rows = adapter.fetch(client=client, trade_date="2026-07-07", brief_type="post_market")

    assert rows[0]["category"] == "policy"
    assert rows[0]["source"] == "NMPA"
    assert rows[0]["source_url"] == "https://www.nmpa.gov.cn/news/a.html"
    assert rows[0]["reliability"] == "official"
    assert "创新药" in rows[0]["symbols"]


def test_fred_adapter_uses_observations_as_macro_evidence():
    from backend.integrations.fred import FredSeriesAdapter

    client = MagicMock()
    client.get.return_value = _response(
        '{"observations":[{"date":"2026-07-06","value":"4.25"}]}'
    )

    adapter = FredSeriesAdapter(series_id="DFF", title="美国联邦基金有效利率")
    rows = adapter.fetch(client=client, trade_date="2026-07-07", brief_type="pre_market")

    assert rows == [{
        "trade_date": "2026-07-07",
        "brief_type": "pre_market",
        "category": "macro",
        "title": "美国联邦基金有效利率",
        "summary": "DFF latest observation 2026-07-06 = 4.25",
        "symbols": ["DFF"],
        "metrics": {"value": 4.25, "date": "2026-07-06"},
        "source": "FRED",
        "source_url": "https://fred.stlouisfed.org/series/DFF",
        "published_at": "2026-07-06",
        "reliability": "official",
    }]


def test_adapter_network_failure_returns_empty_list():
    from backend.integrations.policy import PolicyPageAdapter

    client = MagicMock()
    client.get.side_effect = RuntimeError("timeout")
    adapter = PolicyPageAdapter(source="CSRC", url="https://www.csrc.gov.cn/")

    assert adapter.fetch(client=client, trade_date="2026-07-07") == []


def test_cls_telegraph_adapter_maps_client_rows_to_news_evidence():
    from backend.integrations.cls import ClsTelegraphAdapter

    def fake_fetch_roll_list(**kwargs):
        assert kwargs["category"] == "fund"
        assert kwargs["limit"] == 2
        return [{
            "title": "基金快讯",
            "summary": "基金摘要",
            "published_at": "2026-07-08 11:31:46",
            "source": "财联社",
            "source_url": "https://www.cls.cn/detail/1",
            "symbols": ["基金"],
            "metrics": {"cls_id": 1, "cls_category": "fund"},
        }]

    adapter = ClsTelegraphAdapter(
        fetch_roll_list=fake_fetch_roll_list,
        app_version="test",
        categories=["fund"],
        per_category_limit=2,
    )

    rows = adapter.fetch(client=object(), trade_date="2026-07-08", brief_type="post_market")

    assert rows == [{
        "trade_date": "2026-07-08",
        "brief_type": "post_market",
        "category": "news",
        "title": "基金快讯",
        "summary": "基金摘要",
        "symbols": ["基金"],
        "metrics": {"cls_id": 1, "cls_category": "fund"},
        "source": "财联社",
        "source_url": "https://www.cls.cn/detail/1",
        "published_at": "2026-07-08 11:31:46",
        "reliability": "wire",
    }]


def test_cls_telegraph_adapter_isolates_category_failure():
    from backend.integrations.cls import ClsTelegraphAdapter

    def fake_fetch_roll_list(**kwargs):
        if kwargs["category"] == "fund":
            raise RuntimeError("boom")
        return [{
            "title": "看盘快讯",
            "summary": "摘要",
            "published_at": "2026-07-08 11:31:46",
            "source": "财联社",
            "source_url": "https://www.cls.cn/detail/2",
            "symbols": [],
            "metrics": {"cls_id": 2, "cls_category": "watch"},
        }]

    adapter = ClsTelegraphAdapter(
        fetch_roll_list=fake_fetch_roll_list,
        app_version="test",
        categories=["fund", "watch"],
        per_category_limit=2,
    )

    rows = adapter.fetch(client=object(), trade_date="2026-07-08")

    assert len(rows) == 1
    assert rows[0]["title"] == "看盘快讯"
    assert adapter.last_errors == [{
        "category": "fund",
        "error": "RuntimeError: boom",
    }]


def test_cninfo_adapter_maps_injected_announcements_to_evidence():
    from backend.integrations.cninfo import CninfoAnnouncementAdapter

    calls = []

    def fake_fetch_announcements(*, limit):
        calls.append(limit)
        return [{
            "title": "基金分红公告",
            "ann_date": "2026-07-15",
            "fund_code": "000001",
            "fund_name": "测试基金",
        }]

    adapter = CninfoAnnouncementAdapter(
        fetch_announcements=fake_fetch_announcements,
        limit=2,
    )

    rows = adapter.fetch(trade_date="2026-07-16", brief_type="post_market")

    assert calls == [2]
    assert rows == [{
        "trade_date": "2026-07-16",
        "brief_type": "post_market",
        "category": "announcement",
        "source": "akshare/eastmoney",
        "source_url": "https://fundf10.eastmoney.com/jjgg_000001_2026-07-15.html",
        "title": "基金分红公告",
        "summary": "测试基金 - 2026-07-15",
        "symbols": ["测试基金", "000001"],
        "metrics": None,
        "published_at": "2026-07-15",
        "reliability": "wire",
    }]


def test_cninfo_adapter_isolates_collector_failure():
    from backend.integrations.cninfo import CninfoAnnouncementAdapter

    def failing_fetch_announcements(*, limit):
        raise RuntimeError(f"collector failed at {limit}")

    adapter = CninfoAnnouncementAdapter(
        fetch_announcements=failing_fetch_announcements,
    )

    assert adapter.fetch(trade_date="2026-07-16") == []


def test_cninfo_adapter_filters_missing_titles_and_enforces_limit():
    from backend.integrations.cninfo import CninfoAnnouncementAdapter

    def fake_fetch_announcements(*, limit):
        assert limit == 1
        return [
            {"title": "", "fund_code": "skip"},
            {"title": "公告 A", "fund_code": "000001"},
            {"title": "公告 B", "fund_code": "000002"},
        ]

    adapter = CninfoAnnouncementAdapter(
        fetch_announcements=fake_fetch_announcements,
        limit=1,
    )

    rows = adapter.fetch(trade_date="2026-07-16")

    assert [row["title"] for row in rows] == ["公告 A"]


def test_sector_adapter_maps_top_and_bottom_rows():
    from backend.integrations.sector import SectorHeatAdapter

    adapter = SectorHeatAdapter(
        sector_snapshot={"industry_sectors": [
            {"name": "弱板块", "change_pct": -2.0},
            {"name": "中板块", "change_pct": 0.5},
            {"name": "强板块", "change_pct": 3.0},
        ]},
        top_n=1,
    )

    rows = adapter.fetch(trade_date="2026-07-16")

    assert [row["title"] for row in rows] == [
        "行业板块 强势: 强板块 +3.00%",
        "行业板块 弱势: 弱板块 -2.00%",
    ]
    assert [row["metrics"] for row in rows] == [
        {"change_pct": 3.0},
        {"change_pct": -2.0},
    ]
