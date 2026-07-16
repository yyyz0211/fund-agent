"""Briefing persistence service and ORM characterization tests."""
from contextlib import contextmanager
from datetime import datetime
import json

import pytest
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def in_memory_session(db_session):
    """复用当前 worker 的 PostgreSQL 事务 fixture。"""
    return db_session


class TestBriefingModel:
    """Briefing ORM 写入/读回/唯一约束验证。"""

    @pytest.mark.db
    def test_briefing_model_round_trip(self, in_memory_session):
        """写入一条 Briefing 再读回,所有字段正确。"""
        # import inside to allow the model to be added later
        from backend.db.models import Briefing

        today = "2026-07-07"
        now = datetime.now().isoformat()
        row = Briefing(
            briefing_date=today,
            title="今日基金简报 2026-07-07",
            markdown="# 今日行情\n\n沪深300上涨0.5%",
            sections_json='{"market_snapshot":[],"watchlist_changes":[]}',
            source="akshare + deepseek",
            as_of=today,
        )
        in_memory_session.add(row)
        in_memory_session.commit()

        found = in_memory_session.query(Briefing).filter_by(briefing_date=today).first()
        assert found is not None
        assert found.title == "今日基金简报 2026-07-07"
        assert "沪深300上涨0.5%" in found.markdown
        assert found.source == "akshare + deepseek"
        assert found.as_of == today

    @pytest.mark.db
    def test_briefing_unique_on_date_and_brief_type(self, in_memory_session):
        """同日不同 brief_type 可共存；同日同 type 仍保持唯一。"""
        from backend.db.models import Briefing

        today = "2026-07-07"
        in_memory_session.add(Briefing(
            briefing_date=today, brief_type="post_market", title="盘后",
            markdown="x", sections_json="{}", source=None, as_of=None,
        ))
        in_memory_session.commit()

        in_memory_session.add(Briefing(
            briefing_date=today, brief_type="pre_market", title="盘前",
            markdown="y", sections_json="{}", source=None, as_of=None,
        ))
        in_memory_session.commit()

        in_memory_session.add(Briefing(
            briefing_date=today, brief_type="post_market", title="第二篇盘后",
            markdown="z", sections_json="{}", source=None, as_of=None,
        ))
        with pytest.raises(IntegrityError):
            in_memory_session.commit()

    @pytest.mark.db
    def test_briefing_sections_json_round_trip(self, in_memory_session):
        """中文 key/value 在 sections_json 序列化/反序列化后正确。"""
        from backend.db.models import Briefing

        snapshot = {
            "market_snapshot": [
                {"symbol": "000300", "name": "沪深300", "close": 3800.5, "change_pct": 0.52}
            ],
            "watchlist_changes": [
                {"fund_code": "110011", "fund_name": "易方达蓝筹精选",
                 "period_returns": {"1d": -0.02, "1w": 0.05, "1m": 0.08}}
            ],
            "errors": [],
        }
        json_str = json.dumps(snapshot, ensure_ascii=False)

        row = Briefing(
            briefing_date="2026-07-07", title="Test",
            markdown="test", sections_json=json_str,
            source=None, as_of=None,
        )
        in_memory_session.add(row)
        in_memory_session.commit()

        found = in_memory_session.query(Briefing).first()
        loaded = json.loads(found.sections_json)
        assert loaded["market_snapshot"][0]["name"] == "沪深300"
        assert loaded["watchlist_changes"][0]["period_returns"]["1m"] == 0.08


def test_persist_briefing_delegates_to_flush_only_repository(monkeypatch, db_session):
    from backend.services.briefing import persistence

    captured = {}
    sentinel = object()

    def fake_upsert(session, briefing_date, payload, brief_type="post_market"):
        captured.update(
            session=session,
            briefing_date=briefing_date,
            payload=payload,
            brief_type=brief_type,
        )
        return sentinel

    monkeypatch.setattr(persistence.briefing_repository, "upsert_briefing", fake_upsert)

    result = persistence.persist_briefing(
        db_session,
        briefing_date="2026-07-16",
        payload={"title": "测试"},
        brief_type="pre_market",
    )

    assert result is sentinel
    assert captured == {
        "session": db_session,
        "briefing_date": "2026-07-16",
        "payload": {"title": "测试"},
        "brief_type": "pre_market",
    }


def test_read_briefing_decodes_sections_and_missing_data(monkeypatch, db_session):
    from backend.db.models import Briefing
    from backend.services.briefing import persistence

    row = Briefing(
        briefing_date="2026-07-16",
        brief_type="post_market",
        title="测试简报",
        markdown="# 测试",
        sections_json=json.dumps({
            "modules": {
                "data_statement": {
                    "content": {
                        "failed_modules": [{"module": "macro"}],
                        "data_sources_last_updated": {"market": "now"},
                    },
                },
            },
        }),
        missing_data_json='["macro_evidence"]',
        evidence_count=0,
    )
    db_session.add(row)
    db_session.flush()

    @contextmanager
    def fake_scope():
        yield db_session

    monkeypatch.setattr(persistence, "session_scope", fake_scope)

    result = persistence.read_briefing("2026-07-16")

    assert result["missing_data"] == ["macro_evidence"]
    assert result["failed_modules"] == [{"module": "macro"}]
    assert result["data_sources_last_updated"] == {"market": "now"}
