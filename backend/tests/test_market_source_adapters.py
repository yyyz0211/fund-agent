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
    from backend.services.market_sources import PolicyPageAdapter

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
    from backend.services.market_sources import FredSeriesAdapter

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
    from backend.services.market_sources import PolicyPageAdapter

    client = MagicMock()
    client.get.side_effect = RuntimeError("timeout")
    adapter = PolicyPageAdapter(source="CSRC", url="https://www.csrc.gov.cn/")

    assert adapter.fetch(client=client, trade_date="2026-07-07") == []


def test_cls_telegraph_adapter_maps_client_rows_to_news_evidence(monkeypatch):
    from backend.services.market_sources.cls_telegraph import ClsTelegraphAdapter
    from backend.services import cls_telegraph_client as client_mod

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

    monkeypatch.setattr(client_mod, "fetch_roll_list", fake_fetch_roll_list)
    adapter = ClsTelegraphAdapter(categories=["fund"], per_category_limit=2)

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


def test_cls_telegraph_adapter_isolates_category_failure(monkeypatch):
    from backend.services.market_sources.cls_telegraph import ClsTelegraphAdapter
    from backend.services import cls_telegraph_client as client_mod

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

    monkeypatch.setattr(client_mod, "fetch_roll_list", fake_fetch_roll_list)
    adapter = ClsTelegraphAdapter(categories=["fund", "watch"], per_category_limit=2)

    rows = adapter.fetch(client=object(), trade_date="2026-07-08")

    assert len(rows) == 1
    assert rows[0]["title"] == "看盘快讯"
