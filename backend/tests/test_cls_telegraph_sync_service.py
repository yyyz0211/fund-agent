"""CLS telegraph sync service tests."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


def _raw_item(cls_id: int, *, title: str, ctime: int, category: str = "fund") -> dict:
    return {
        "id": cls_id,
        "title": title,
        "brief": f"{title} brief",
        "content": f"{title} content",
        "category": category,
        "ctime": ctime,
        "subjects": [{"subject_name": "盘面直播"}],
        "stock_list": [{"name": "沪深300", "StockID": "sh000300"}],
    }


def test_normalize_sync_record_preserves_raw_content_and_metadata():
    from backend.services.knowledge.cls_telegraph_sync_service import normalize_cls_telegraph_record

    row = normalize_cls_telegraph_record(
        _raw_item(2421001, title="财联社电报：基金市场回暖", ctime=1783564494),
        category="fund",
    )

    assert row is not None
    assert row["cls_id"] == "2421001"
    assert row["title"] == "财联社电报：基金市场回暖"
    assert row["brief"] == "财联社电报：基金市场回暖 brief"
    assert row["content"] == "财联社电报：基金市场回暖 content"
    assert row["category"] == "fund"
    assert row["subjects"] == ["盘面直播"]
    assert row["symbols"] == ["沪深300", "sh000300", "盘面直播"]
    assert row["source_url"] == "https://www.cls.cn/detail/2421001"
    assert row["ctime"] == 1783564494
    assert row["published_at"] == "2026-07-09 10:34:54"
    assert row["raw_json"]["id"] == 2421001


def test_cls_telegraph_repository_upserts_and_filters_items(db_session):
    from backend.db.repositories import knowledge as knowledge_repo
    session = db_session
    row = {
        "cls_id": "2421001",
        "title": "基金市场回暖",
        "brief": "基金市场回暖 brief",
        "content": "基金市场回暖 content",
        "category": "fund",
        "subjects": ["盘面直播"],
        "symbols": ["沪深300"],
        "source_url": "https://www.cls.cn/detail/2421001",
        "ctime": 1783564494,
        "published_at": "2026-07-09 10:34:54",
        "raw_json": {"id": 2421001, "title": "基金市场回暖"},
    }

    assert knowledge_repo.upsert_cls_telegraph_item(session, row) is True
    assert knowledge_repo.upsert_cls_telegraph_item(session, row) is False

    rows = knowledge_repo.search_cls_telegraph_items(
        session,
        limit=10,
        category="fund",
        keyword="回暖",
        since_id="2420000",
    )
    assert len(rows) == 1
    assert rows[0]["cls_id"] == "2421001"
    assert rows[0]["symbols"] == ["沪深300"]
    assert rows[0]["raw_json"]["title"] == "基金市场回暖"


def test_sync_once_writes_telegraph_items_and_derives_market_evidence(db_session):
    from backend.db.repositories import knowledge as knowledge_repo
    from backend.services.knowledge.cls_telegraph_sync_service import sync_cls_telegraph_once

    session = db_session
    pages = [
        [_raw_item(2421002, title="财联社电报：基金市场回暖", ctime=1783564494)],
        [_raw_item(2421001, title="财联社电报：半导体走强", ctime=1783564400)],
    ]

    def fetch_page(**kwargs):
        return pages.pop(0) if pages else []

    result = sync_cls_telegraph_once(
        session=session,
        fetch_page=fetch_page,
        page_size=1,
        max_pages=3,
        timeout_seconds=1.0,
        app_version="8.7.9",
    )

    assert result["status"] == "completed"
    assert result["fetched"] == 2
    assert result["inserted"] == 2
    # 已移除双写，evidence 由 ClsTelegraphAdapter 独立采集
    assert result["evidence_inserted"] == 0

    rows = knowledge_repo.search_cls_telegraph_items(session, limit=10)
    assert [row["cls_id"] for row in rows] == ["2421002", "2421001"]

    status = knowledge_repo.get_cls_telegraph_sync_state(session)
    assert status["last_seen_cls_id"] == "2421002"
    assert status["last_seen_ctime"] == 1783564494
    assert status["last_success_at"]
    assert status["last_error"] is None


def test_sync_once_records_error_without_clearing_existing_state(db_session):
    from backend.db.repositories import knowledge as knowledge_repo
    from backend.services.knowledge.cls_telegraph_sync_service import sync_cls_telegraph_once

    session = db_session
    knowledge_repo.update_cls_telegraph_sync_state(
        session,
        last_seen_ctime=1783564494,
        last_seen_cls_id="2421002",
        last_success_at="2026-07-09T10:35:00+08:00",
        last_error=None,
    )

    def fetch_page(**kwargs):
        raise RuntimeError("remote failed")

    result = sync_cls_telegraph_once(
        session=session,
        fetch_page=fetch_page,
        page_size=50,
        max_pages=3,
        timeout_seconds=1.0,
        app_version="8.7.9",
    )

    assert result["status"] == "failed"
    assert "remote failed" in result["last_error"]

    status = knowledge_repo.get_cls_telegraph_sync_state(session)
    assert status["last_seen_cls_id"] == "2421002"
    assert status["last_success_at"] == "2026-07-09T10:35:00+08:00"
    assert "remote failed" in status["last_error"]
