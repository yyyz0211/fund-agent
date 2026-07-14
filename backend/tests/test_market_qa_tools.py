"""QA-facing market tools tests."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, Briefing
from backend.services.market import market_intel_service
from backend.tools import market_tools as mt


def test_market_snapshot_auto_tool_summarizes_snapshot(monkeypatch):
    monkeypatch.setattr(
        market_intel_service,
        "get_market_snapshot",
        lambda trade_date=None, snapshot_type="post_market", session=None: {
            "trade_date": trade_date,
            "snapshot_type": snapshot_type,
            "indices": [
                {"symbol": "000001", "name": "上证指数", "close": 4094.4, "change_pct": 0.5},
                {"symbol": "000300", "name": "沪深300", "close": 4979.4, "change_pct": 1.07},
            ],
            "breadth": {"up": 639, "down": 4535, "limit_up": 34, "limit_down": 50},
            "industry_sectors": [
                {"name": "游戏", "change_pct": 1.16},
                {"name": "半导体", "change_pct": 0.56},
                {"name": "贵金属", "change_pct": -4.78},
            ],
            "concept_sectors": [],
            "industry_flows": [{"name": "半导体", "net_flow": 966600.0}],
            "concept_flows": [],
            "overseas": [{"market": "US", "name": "纳指", "change_pct": 0.92}],
            "announcements": [{"title": "公告 A", "url": "https://example.com/a"}],
            "errors": [{"field": "themes", "error": "empty"}],
            "source": "akshare",
            "as_of": "2026-07-07",
        },
    )

    out = mt.get_market_snapshot_auto.invoke(
        {"date": "2026-07-07", "snapshot_type": "post_market", "limit": 2}
    )

    assert out["trade_date"] == "2026-07-07"
    assert out["source"] == "akshare"
    assert out["as_of"] == "2026-07-07"
    assert [row["name"] for row in out["top_industry_sectors"]] == ["贵金属", "游戏"]
    assert len(out["announcements"]) == 1
    assert out["errors"][0]["field"] == "themes"


def test_sector_heatmap_tool_merges_flow_data(monkeypatch):
    monkeypatch.setattr(
        market_intel_service,
        "get_market_snapshot",
        lambda trade_date=None, snapshot_type="post_market", session=None: {
            "trade_date": "2026-07-07",
            "snapshot_type": "post_market",
            "industry_sectors": [
                {"name": "医药", "change_pct": 2.1},
                {"name": "煤炭", "change_pct": -1.2},
            ],
            "industry_flows": [
                {"name": "医药", "net_flow": 120000.0},
                {"name": "煤炭", "net_flow": -50000.0},
            ],
            "source": "akshare",
            "as_of": "2026-07-07",
        },
    )

    out = mt.get_sector_heatmap.invoke({"kind": "industry", "sort": "flow", "limit": 2})

    assert out["kind"] == "industry"
    assert out["rows"][0]["name"] == "医药"
    assert out["rows"][0]["net_flow"] == 120000.0
    assert out["rows"][1]["net_flow"] == -50000.0
    assert out["source"] == "akshare"


def test_latest_market_brief_tool_returns_recent_briefing(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    session.add(
        Briefing(
            briefing_date="2026-07-07",
            title="每日基金简报 2026-07-07",
            markdown="# 简报\n\n沪深300 +1.07%",
            sections_json='{"market_snapshot":[]}',
            source="akshare + deepseek",
            as_of="2026-07-07",
        )
    )
    session.commit()

    monkeypatch.setattr(mt, "get_session", lambda: session)

    out = mt.get_latest_market_brief.invoke({})

    assert out["title"] == "每日基金简报 2026-07-07"
    assert "沪深300" in out["markdown"]
    assert out["source"] == "akshare + deepseek"
    assert out["as_of"] == "2026-07-07"
