from __future__ import annotations

from types import SimpleNamespace


def _settings(**overrides):
    values = {
        "knowledge_rag_enabled": True,
        "knowledge_vector_backend": "auto",
        "knowledge_embedding_base_url": None,
        "knowledge_embedding_api_key": None,
        "knowledge_embedding_model": None,
        "knowledge_embedding_version": None,
        "knowledge_embedding_dimensions": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_embedding_factory_returns_none_when_configuration_is_incomplete():
    from backend.services.knowledge_embedding import build_embedding_provider

    assert build_embedding_provider(_settings()) is None


def test_embedding_factory_never_reuses_chat_configuration(monkeypatch):
    from backend.services import knowledge_embedding

    settings = _settings(
        deepseek_api_key="chat-key",
        deepseek_base_url="https://chat.example/v1",
        knowledge_embedding_model="embed-model",
        knowledge_embedding_version="v1",
        knowledge_embedding_dimensions=16,
    )

    assert knowledge_embedding.build_embedding_provider(settings) is None


def test_embedding_factory_builds_provider_from_complete_configuration(monkeypatch):
    from backend.services import knowledge_embedding

    captured = {}
    sentinel = object()

    def fake_provider(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        knowledge_embedding,
        "OpenAICompatibleEmbeddingProvider",
        fake_provider,
    )
    settings = _settings(
        knowledge_embedding_base_url="https://embed.example/v1",
        knowledge_embedding_api_key="embed-key",
        knowledge_embedding_model="embed-model",
        knowledge_embedding_version="2026-07",
        knowledge_embedding_dimensions=16,
    )

    assert knowledge_embedding.build_embedding_provider(settings) is sentinel
    assert captured == {
        "base_url": "https://embed.example/v1",
        "api_key": "embed-key",
        "model": "embed-model",
        "version": "2026-07",
        "dimensions": 16,
    }
