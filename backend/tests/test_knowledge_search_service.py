from __future__ import annotations

from types import SimpleNamespace

from backend.services import knowledge_search_service as service


def test_pipeline_uses_independent_classification_and_index_limits(monkeypatch):
    calls: dict[str, int] = {}
    settings = SimpleNamespace(
        knowledge_classification_batch_size=10,
        knowledge_index_batch_size=20,
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        service.knowledge_ingestion_service,
        "ingest_recent_knowledge",
        lambda **kwargs: calls.setdefault("classification_limit", kwargs["limit"]) or {},
    )
    monkeypatch.setattr(
        service.knowledge_vector,
        "index_pending_documents",
        lambda **kwargs: calls.setdefault("index_limit", kwargs["limit"]) or {},
    )
    monkeypatch.setattr(
        service.knowledge_fund_profile_service,
        "refresh_fund_watchlist_profiles",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        service.knowledge_match_service,
        "refresh_knowledge_fund_matches",
        lambda **_kwargs: {},
    )

    service.run_knowledge_pipeline_once(session=object())

    assert calls == {"classification_limit": 10, "index_limit": 20}
