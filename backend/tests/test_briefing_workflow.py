"""Briefing workflow orchestration characterization tests."""
from contextlib import contextmanager
import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def in_memory_session(db_session):
    """Reuse the current worker's PostgreSQL transaction fixture."""
    return db_session


class TestRunDailyBriefing:
    """Main workflow: collect -> compose -> persist Briefing."""

    def test_run_writes_briefing_row(self, in_memory_session):
        from backend.db.models import Briefing
        from backend.services.briefing import _state, workflow

        snapshot = {
            "market_snapshot": [{"symbol": "000300", "name": "沪深300", "close": 3800.0, "change_pct": 0.5}],
            "market_breadth": {"up": 2000, "down": 2500, "limit_up": 50, "limit_down": 20,
                               "volume": 8000.0, "amount": 8500.0, "total": 4500,
                               "source": "akshare", "as_of": "2026-07-07"},
            "sector_snapshot": [{"name": "医疗服务", "change_pct": 2.1, "source": "akshare"}],
            "watchlist_changes": [],
            "errors": [],
            "collect_meta": {},
        }
        compose_result = {
            "markdown": "# 今日简报\n\n沪深300+0.5%",
            "sections": {"market_snapshot": [], "watchlist_changes": []},
            "warnings": [],
            "llm_model": "deepseek-chat",
        }

        def mock_collect(**_kwargs):
            return snapshot

        def mock_compose(snap, evidence=None, *, profile=None, model=None):
            assert snap == snapshot
            return compose_result

        with patch.object(workflow.collectors, "collect_watchlist_snapshot", mock_collect), \
             patch.object(workflow.composer, "compose_briefing", mock_compose):
            _state.reset_for_tests()
            result = workflow.run_daily_briefing(
                trigger="manual", session=in_memory_session, model=MagicMock()
            )

        rows = in_memory_session.query(Briefing).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.source == "akshare + deepseek"
        assert "沪深300" in row.markdown
        assert result["trigger"] == "manual"
        assert result["succeeded"] == 1

    def test_run_idempotent_same_day(self, in_memory_session):
        from backend.db.models import Briefing
        from backend.services.briefing import _state, workflow

        def make_snapshot(md_text):
            return {
                "market_snapshot": [{"symbol": "000300", "name": "沪深300", "close": 3800.0, "change_pct": 0.5}],
                "watchlist_changes": [{"fund_code": "110011", "fund_name": "A"}],
                "errors": [],
                "collect_meta": {},
            }, {"markdown": md_text, "sections": {}, "warnings": [], "llm_model": "test"}

        snap_v1, comp_v1 = make_snapshot("v1 content")
        _snap_v2, comp_v2 = make_snapshot("v2 content")

        def mock_collect(**_kwargs):
            return snap_v1

        def mock_compose(snap, evidence=None, *, profile=None, model=None):
            return comp_v1

        _state.reset_for_tests()
        with patch.object(workflow.collectors, "collect_watchlist_snapshot", mock_collect), \
             patch.object(workflow.composer, "compose_briefing", mock_compose):
            workflow.run_daily_briefing(
                trigger="manual", session=in_memory_session, model=MagicMock()
            )

        time.sleep(0.01)

        def mock_compose_v2(snap, evidence=None, *, profile=None, model=None):
            return comp_v2

        with patch.object(workflow.collectors, "collect_watchlist_snapshot", mock_collect), \
             patch.object(workflow.composer, "compose_briefing", mock_compose_v2):
            workflow.run_daily_briefing(
                trigger="manual", session=in_memory_session, model=MagicMock()
            )

        rows = in_memory_session.query(Briefing).all()
        assert len(rows) == 1
        assert "v2" in rows[0].markdown

    def test_run_passes_brief_type_profile_to_composer(self, in_memory_session):
        from backend.db.models import Briefing
        from backend.services.briefing import workflow

        snapshot = {
            "market_snapshot": [{"symbol": "000300", "market_date": "2026-07-07"}],
            "watchlist_changes": [{"fund_code": "110011"}],
            "errors": [],
            "collect_meta": {},
        }

        def mock_compose(snap, evidence=None, *, profile=None, model=None):
            assert snap == snapshot
            assert profile is not None
            assert profile.brief_type == "pre_market"
            return {
                "markdown": "pre-market markdown",
                "sections": {"brief_type": profile.brief_type, "module_order": [], "modules": {}},
                "warnings": [],
                "llm_model": "test",
            }

        with patch.object(workflow.collectors, "collect_watchlist_snapshot", lambda **_: snapshot), \
             patch.object(workflow.collectors, "collect_and_run_for_brief_type", return_value={"inserted": 0}), \
             patch.object(workflow.collectors, "search_evidence", return_value=[]), \
             patch.object(workflow.composer, "compose_briefing", mock_compose):
            workflow.run_daily_briefing(
                trigger="manual",
                session=in_memory_session,
                brief_type="pre_market",
                model=MagicMock(),
            )

        row = in_memory_session.query(Briefing).one()
        assert row.brief_type == "pre_market"
        assert '"brief_type": "pre_market"' in row.sections_json

    def test_run_records_last_run_snapshot(self, in_memory_session):
        from backend.services.briefing import _state, workflow

        def mock_collect(**_kwargs):
            return {
                "market_snapshot": [{"symbol": "000300"}],
                "watchlist_changes": [{"fund_code": "110011"}],
                "errors": [],
                "collect_meta": {},
            }

        def mock_compose(snap, evidence=None, *, profile=None, model=None):
            return {"markdown": "x", "sections": {}, "warnings": [], "llm_model": "test"}

        with patch.object(workflow.collectors, "collect_watchlist_snapshot", mock_collect), \
             patch.object(workflow.composer, "compose_briefing", mock_compose):
            _state.reset_for_tests()
            workflow.run_daily_briefing(
                trigger="test_run", session=in_memory_session, model=MagicMock()
            )
            last = _state.get_last_run()

        assert last["trigger"] == "test_run"
        assert "last_run_at" in last
        assert last["succeeded"] == 1
        assert last["failed"] == 0
        assert last["total_funds"] == 1

    def test_run_records_failures_when_collect_errors(self, in_memory_session):
        from backend.services.briefing import _state, workflow

        def mock_collect(**_kwargs):
            return {
                "market_snapshot": [],
                "watchlist_changes": [{"fund_code": "110011", "fund_name": "A"}],
                "errors": [{"fund_code": "000001", "stage": "collect", "message": "timeout"}],
                "collect_meta": {},
            }

        def mock_compose(snap, evidence=None, *, profile=None, model=None):
            return {"markdown": "ok", "sections": {}, "warnings": [], "llm_model": "test"}

        _state.reset_for_tests()
        with patch.object(workflow.collectors, "collect_watchlist_snapshot", mock_collect), \
             patch.object(workflow.composer, "compose_briefing", mock_compose):
            result = workflow.run_daily_briefing(
                trigger="manual", session=in_memory_session, model=MagicMock()
            )

        assert result["failed"] == 1
        assert any(f.get("fund_code") == "000001" for f in result["failures"])
        assert any(f.get("stage") == "collect" for f in result["failures"])

    def test_run_returns_empty_briefing_when_no_watchlist(self, in_memory_session):
        from backend.db.models import Briefing
        from backend.services.briefing import _state, workflow

        def mock_collect(**_kwargs):
            return {
                "market_snapshot": [],
                "watchlist_changes": [],
                "errors": [],
                "collect_meta": {},
            }

        _state.reset_for_tests()
        with patch.object(workflow.collectors, "collect_watchlist_snapshot", mock_collect):
            result = workflow.run_daily_briefing(trigger="manual", session=in_memory_session)

        assert result["succeeded"] == 0
        rows = in_memory_session.query(Briefing).all()
        assert len(rows) == 1
        assert "自选池为空" in rows[0].markdown
        assert result["last_run_at"] is not None

    def test_run_collects_evidence_before_reading(self, in_memory_session):
        from backend.db.models import Briefing, MarketEvidence
        from backend.services.briefing import _state, workflow

        def noop_adapter_factory(**kwargs):
            adapter = MagicMock()
            adapter.fetch.return_value = []
            return adapter

        _state.reset_for_tests()
        with patch(
            "backend.services.market.market_evidence_service.build_default_adapters",
            noop_adapter_factory,
        ), patch.object(
            workflow.collectors, "collect_watchlist_snapshot", lambda **_: {
                "market_snapshot": [],
                "watchlist_changes": [],
                "errors": [],
                "collect_meta": {},
            }
        ), patch.object(
            workflow.composer, "compose_briefing",
            lambda snap, evidence=None, *, profile=None, model=None: {
                "markdown": "# 测试简报",
                "sections": {},
                "warnings": [],
                "llm_model": "test",
            },
        ):
            workflow.run_daily_briefing(trigger="manual", session=in_memory_session)

        evidence_count = in_memory_session.query(MarketEvidence).count()
        assert evidence_count >= 0
        rows = in_memory_session.query(Briefing).all()
        assert len(rows) == 1


def test_owned_workflow_closes_each_short_scope_before_collect_and_compose(monkeypatch):
    from backend.services.briefing import workflow

    events = []
    scope_depth = 0

    @contextmanager
    def fake_scope():
        nonlocal scope_depth
        scope_depth += 1
        events.append("scope_enter")
        try:
            yield object()
        finally:
            events.append("scope_exit")
            scope_depth -= 1

    monkeypatch.setattr(workflow, "session_scope", fake_scope)
    monkeypatch.setattr(
        workflow.collectors,
        "collect_and_run_for_brief_type",
        lambda **_: events.append("ingest"),
    )
    monkeypatch.setattr(workflow.collectors, "search_evidence", lambda **_: [])

    def collect(**_):
        assert scope_depth == 0
        events.append("collect")
        return {
            "market_snapshot": [{"market_date": "2026-07-16"}],
            "watchlist_changes": [{"fund_code": "000001"}],
            "errors": [],
            "collect_meta": {},
        }

    def compose(*_args, **_kwargs):
        assert scope_depth == 0
        events.append("compose")
        return {"markdown": "ok", "sections": {}, "warnings": []}

    monkeypatch.setattr(workflow.collectors, "collect_watchlist_snapshot", collect)
    monkeypatch.setattr(workflow.composer, "compose_briefing", compose)
    monkeypatch.setattr(
        workflow.persistence,
        "persist_briefing",
        lambda session, **_: events.append("persist"),
    )

    workflow.run_daily_briefing(trigger="test", model=MagicMock())

    assert events == [
        "scope_enter", "ingest", "scope_exit",
        "scope_enter", "scope_exit",
        "collect", "compose",
        "scope_enter", "persist", "scope_exit",
    ]
