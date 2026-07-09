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


class _DiagnosticAdapter(_Adapter):
    source = "财联社"

    def __init__(self):
        super().__init__(rows=[])
        self.last_errors = [{
            "category": "fund",
            "error": "ConnectError: connect failed",
        }]


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


def test_ingest_market_evidence_surfaces_adapter_diagnostics(session):
    from backend.services import market_evidence_ingestion as ing

    result = ing.ingest_market_evidence(
        trade_date="2026-07-09",
        adapters=[_DiagnosticAdapter()],
        session=session,
    )

    assert result["inserted"] == 0
    assert result["fetched"] == 0
    assert result["errors"][0]["adapter"] == "财联社"
    assert "connect failed" in result["errors"][0]["error"]


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


def test_ingest_market_evidence_hourly_idempotent_across_runs(session):
    """模拟"hourly + 手动 + cron"三方都触发, 同一 (date, brief_type, url) 多次拉取:
    只有第一次 inserted=1, 后续全是 no-op (DB 唯一键 + select-then-insert)。
    这是 hourly cron 不会"写重复数据"的核心保证。
    """
    from backend.services import market_evidence_ingestion as ing

    cls_row = {
        "trade_date": "2026-07-08",
        "brief_type": "post_market",
        "category": "news",
        "title": "某财联社快讯",
        "summary": "财联社摘要",
        "symbols": [],
        "source": "财联社",
        "source_url": "https://www.cls.cn/telegraph/abc",
        "published_at": "2026-07-08 10:00:00",
        "reliability": "wire",
    }

    total_inserted = 0
    for run_idx in range(5):
        result = ing.ingest_market_evidence(
            trade_date="2026-07-08",
            brief_type="post_market",
            adapters=[_Adapter([cls_row])],
            session=session,
        )
        total_inserted += result["inserted"]

    # 5 次同 url 拉取, 总 inserted 必须 = 1
    assert total_inserted == 1, f"expected 1 insert across 5 runs, got {total_inserted}"

    # DB 里也只有一行
    rows = session.execute(
        __import__("sqlalchemy").text(
            "SELECT COUNT(*) FROM market_evidence "
            "WHERE trade_date='2026-07-08' AND brief_type='post_market' "
            "AND source_url=:u"
        ),
        {"u": cls_row["source_url"]},
    ).scalar()
    assert rows == 1


def test_ingest_market_evidence_skips_cross_date_duplicate_hash_and_continues(session):
    """真实 SQLite 文件历史 schema 对 raw_hash 有唯一约束。

    同一财联社文章可能在次日 roll list 中继续出现; 这时应跳过旧文章,
    继续写入同批次的新文章,不能让 session 因 IntegrityError 整批回滚。
    """
    from backend.services import market_evidence_ingestion as ing

    duplicate = {
        "category": "news",
        "title": "盘后A股上市公司重点业绩公告精选",
        "summary": "摘要",
        "symbols": [],
        "source": "财联社",
        "source_url": "https://www.cls.cn/detail/2420892",
        "published_at": "2026-07-08 22:32:36",
        "reliability": "wire",
    }
    fresh = {
        "category": "news",
        "title": "今日基金快讯",
        "summary": "摘要",
        "symbols": [],
        "source": "财联社",
        "source_url": "https://www.cls.cn/detail/2421217",
        "published_at": "2026-07-09 10:34:54",
        "reliability": "wire",
    }

    first = ing.ingest_market_evidence(
        trade_date="2026-07-08",
        brief_type="post_market",
        adapters=[_Adapter([duplicate])],
        session=session,
    )
    second = ing.ingest_market_evidence(
        trade_date="2026-07-09",
        brief_type="post_market",
        adapters=[_Adapter([duplicate, fresh])],
        session=session,
    )

    assert first["inserted"] == 1
    assert second["inserted"] == 1
    assert second["errors"] == []
