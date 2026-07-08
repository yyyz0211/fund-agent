"""Market evidence ingestion tests."""
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


class _Adapter:
    def __init__(self, rows=None, exc=None):
        self.rows = rows or []
        self.exc = exc

    def fetch(self, *, client, trade_date, brief_type="post_market"):
        if self.exc:
            raise self.exc
        return self.rows


def test_ingest_market_evidence_writes_rows_and_dedupes(session):
    from backend.services import market_evidence_ingestion as ing

    row = {
        "trade_date": "2026-07-07",
        "brief_type": "post_market",
        "category": "policy",
        "title": "创新药政策",
        "summary": "审评提速。",
        "symbols": ["创新药"],
        "source": "NMPA",
        "source_url": "https://example.gov/a",
        "published_at": "2026-07-07",
        "reliability": "official",
    }

    result = ing.ingest_market_evidence(
        trade_date="2026-07-07",
        brief_type="post_market",
        adapters=[_Adapter([row]), _Adapter([row])],
        session=session,
    )

    assert result["inserted"] == 1
    assert result["fetched"] == 2
    assert result["errors"] == []
    assert result["categories"] == {"policy": 1}


def test_ingest_market_evidence_continues_on_adapter_failure(session):
    from backend.services import market_evidence_ingestion as ing

    result = ing.ingest_market_evidence(
        trade_date="2026-07-07",
        adapters=[_Adapter(exc=RuntimeError("boom")), _Adapter([])],
        session=session,
    )

    assert result["inserted"] == 0
    assert result["errors"][0]["error"] == "boom"


def test_ingest_market_evidence_accepts_cls_news_category(session):
    from backend.services import market_evidence_ingestion as ing

    row = {
        "trade_date": "2026-07-08",
        "brief_type": "post_market",
        "category": "news",
        "title": "基金快讯",
        "summary": "财联社摘要",
        "symbols": ["基金"],
        "metrics": {"cls_id": 1, "cls_category": "fund"},
        "source": "财联社",
        "source_url": "https://www.cls.cn/detail/1",
        "published_at": "2026-07-08 11:31:46",
        "reliability": "wire",
    }

    result = ing.ingest_market_evidence(
        trade_date="2026-07-08",
        brief_type="post_market",
        adapters=[_Adapter([row]), _Adapter([row])],
        session=session,
    )

    assert result["inserted"] == 1
    assert result["fetched"] == 2
    assert result["categories"] == {"news": 1}
