"""Market evidence storage/search tests."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.init_db import init_db
from backend.db.session import make_engine


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    s = Local()
    yield s
    s.close()


def test_upsert_market_evidence_dedupes_by_hash(session):
    from backend.services import market_evidence_service as svc

    first = svc.upsert_evidence(
        {
            "trade_date": "2026-07-07",
            "brief_type": "post_market",
            "category": "policy",
            "title": "国家药监局发布 CGT 审评征求意见稿",
            "summary": "部分细胞基因治疗新药拟纳入快速审评通道。",
            "symbols": ["创新药", "细胞治疗"],
            "source": "NMPA",
            "source_url": "https://example.com/policy",
            "published_at": "2026-07-06T20:12:00+08:00",
            "reliability": "official",
            "raw_excerpt": "短摘录",
        },
        session=session,
    )
    second = svc.upsert_evidence(
        {
            "trade_date": "2026-07-07",
            "brief_type": "post_market",
            "category": "policy",
            "title": "国家药监局发布 CGT 审评征求意见稿",
            "summary": "更新后的摘要。",
            "symbols": ["创新药"],
            "source": "NMPA",
            "source_url": "https://example.com/policy",
            "published_at": "2026-07-06T20:12:00+08:00",
            "reliability": "official",
        },
        session=session,
    )

    assert second["id"] == first["id"]
    assert second["summary"] == "更新后的摘要。"
    assert second["symbols"] == ["创新药"]
    assert second["raw_hash"]


def test_search_market_evidence_filters_query_date_category(session):
    from backend.services import market_evidence_service as svc

    svc.upsert_evidence(
        {
            "trade_date": "2026-07-07",
            "category": "policy",
            "title": "创新药快速审评政策",
            "summary": "创新药政策催化。",
            "symbols": ["创新药"],
            "source": "NMPA",
            "source_url": "https://example.com/a",
        },
        session=session,
    )
    svc.upsert_evidence(
        {
            "trade_date": "2026-07-07",
            "category": "overseas",
            "title": "纳指收涨",
            "summary": "美股科技股上涨。",
            "symbols": ["纳指"],
            "source": "Yahoo",
            "source_url": "https://example.com/b",
        },
        session=session,
    )

    rows = svc.search_evidence(
        query="创新药",
        trade_date="2026-07-07",
        category="policy",
        limit=5,
        session=session,
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "创新药快速审评政策"
    assert rows[0]["source_url"] == "https://example.com/a"


def test_search_market_evidence_tool_returns_missing_note(monkeypatch):
    from backend.tools import market_tools as mt

    monkeypatch.setattr(
        "backend.tools.market_tools.mev.search_evidence",
        lambda query, trade_date="", category="", limit=5, session=None: [],
    )

    out = mt.search_market_evidence.invoke({"query": "医药为什么涨", "date": "2026-07-07"})

    assert out["evidence"] == []
    assert "不能确认催化原因" in out["missing_evidence_note"]
    assert out["source"] == "local_market_evidence"
