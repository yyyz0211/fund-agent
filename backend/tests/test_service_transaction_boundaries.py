"""不依赖数据库方言的 service 事务边界回归测试。"""
from __future__ import annotations


def test_refresh_fund_accepts_injected_session_and_only_persists_there(monkeypatch):
    from backend.services.fund import fund_service as service

    injected = object()
    calls: list[tuple] = []
    monkeypatch.setattr(service, "_collect_refresh_data", lambda code: (
        [{"nav_date": "2026-07-15", "accumulated_nav": 1.23}],
        {"fund_code": code, "fund_name": "Test"},
    ))
    monkeypatch.setattr(
        service.repo, "upsert_navs",
        lambda session, code, navs: calls.append(("navs", session, code)) or 1,
    )
    monkeypatch.setattr(
        service.repo, "upsert_fund",
        lambda session, payload: calls.append(("fund", session, payload["fund_code"])),
    )

    result = service.refresh_fund("110011", session=injected)

    assert result["navs_inserted"] == 1
    assert calls == [
        ("navs", injected, "110011"),
        ("fund", injected, "110011"),
    ]


def test_refresh_profile_accepts_injected_session_and_only_persists_there(monkeypatch):
    from backend.services.fund import fund_profile_service as service

    injected = object()
    calls: list[tuple] = []
    monkeypatch.setattr(service.dc, "fetch_fund_profile", lambda code: {
        "fund_code": code,
        "peer_candidates": [],
        "errors": [],
        "missing_data": [],
        "source": "test",
        "as_of": "2026-07-15",
    })
    monkeypatch.setattr(
        service.repo, "upsert_fund_profile",
        lambda session, code, payload: calls.append((session, code)) or payload,
    )

    result = service.refresh_profile("110011", session=injected)

    assert result["fund_code"] == "110011"
    assert calls == [(injected, "110011")]


def test_ingest_candidates_classifies_entire_batch_before_writing_injected_session(monkeypatch):
    from backend.services.knowledge import knowledge_ingestion_service as service
    from contextlib import contextmanager

    events: list[str] = []
    @contextmanager
    def state_scope():
        yield object()

    monkeypatch.setattr(service, "session_scope", state_scope)
    monkeypatch.setattr(service, "_classification_state", lambda session, candidate: None)
    monkeypatch.setattr(
        service, "should_classify_candidate",
        lambda *args, **kwargs: (True, "classify"),
    )
    monkeypatch.setattr(service, "_next_attempt_no", lambda *args: 1)
    monkeypatch.setattr(
        service, "_classify",
        lambda classifier, candidate: events.append(f"classify:{candidate['source_id']}")
        or type("Outcome", (), {"status": "failed", "result": None, "error_message": "x"})(),
    )
    monkeypatch.setattr(
        service, "_write_classification",
        lambda session, candidate, outcome, **kwargs: events.append(
            f"write:{candidate['source_id']}"
        ),
    )

    service.ingest_candidates([
        {"source_id": "1", "source_type": "cls", "title": "one", "content": "a"},
        {"source_id": "2", "source_type": "cls", "title": "two", "content": "b"},
    ], session=type("Session", (), {"flush": lambda self: None})())

    assert events == ["classify:1", "classify:2", "write:1", "write:2"]


def test_search_knowledge_embeds_before_first_database_query(monkeypatch):
    from backend.services.knowledge import knowledge_search_service as service

    events: list[str] = []

    class Result:
        def all(self):
            return []

    class Session:
        def scalars(self, statement):
            events.append("sql")
            return Result()

        def add(self, value):
            pass

        def flush(self):
            pass

    class Provider:
        def embed(self, texts):
            events.append("embed")
            return [[0.1, 0.2]]

    class Store:
        def search(self, query_vector, filters, limit):
            return []

    service.search_knowledge(
        "query",
        session=Session(),
        embedding_provider=Provider(),
        vector_store=Store(),
    )

    assert events[0] == "embed"


def test_get_market_snapshot_cache_miss_does_not_reuse_query_session(monkeypatch):
    from backend.services.market import market_intel_service as service

    class Session:
        def scalar(self, statement):
            return None

    queried_session = Session()
    received_sessions: list[object | None] = []
    monkeypatch.setattr(
        service,
        "collect_market_intel",
        lambda trade_date, snapshot_type, session=None: received_sessions.append(session)
        or {"trade_date": trade_date, "snapshot_type": snapshot_type},
    )

    result = service.get_market_snapshot(
        "2026-07-15", "post_market", session=queried_session,
    )

    assert result["trade_date"] == "2026-07-15"
    assert received_sessions == [None]
