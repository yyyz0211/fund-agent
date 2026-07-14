from __future__ import annotations

from typing import Any

from langchain_openai import OpenAIEmbeddings

from backend.exceptions import DataSourceError


class OpenAICompatibleEmbeddingProvider:
    """使用独立 OpenAI-compatible endpoint 的真实 embedding provider。"""

    def __init__(
        self,
        *,
        model: str,
        version: str,
        dimensions: int,
        api_key: str,
        base_url: str,
    ) -> None:
        self.model = model
        self.version = version
        self.dimensions = int(dimensions)
        self._client = OpenAIEmbeddings(
            model=model,
            api_key=api_key,
            base_url=base_url,
            dimensions=self.dimensions,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._client.embed_documents(texts)
        if len(vectors) != len(texts):
            raise DataSourceError(
                "embedding response count mismatch: "
                f"expected={len(texts)}, actual={len(vectors)}",
                source="embedding",
                details={"expected": len(texts), "actual": len(vectors)},
            )
        if any(len(vector) != self.dimensions for vector in vectors):
            raise DataSourceError(
                "embedding response dimension mismatch: "
                f"expected={self.dimensions}",
                source="embedding",
                details={"expected": self.dimensions},
            )
        return [[float(value) for value in vector] for vector in vectors]


def build_embedding_provider(settings: Any):
    """配置不完整时返回 None，禁止隐式复用聊天模型 endpoint。"""
    if not bool(getattr(settings, "knowledge_rag_enabled", True)):
        return None
    if getattr(settings, "knowledge_vector_backend", "auto") == "structured":
        return None
    values = {
        "base_url": getattr(settings, "knowledge_embedding_base_url", None),
        "api_key": getattr(settings, "knowledge_embedding_api_key", None),
        "model": getattr(settings, "knowledge_embedding_model", None),
        "version": getattr(settings, "knowledge_embedding_version", None),
        "dimensions": getattr(settings, "knowledge_embedding_dimensions", None),
    }
    if any(value in (None, "") for value in values.values()):
        return None
    return OpenAICompatibleEmbeddingProvider(
        base_url=str(values["base_url"]),
        api_key=str(values["api_key"]),
        model=str(values["model"]),
        version=str(values["version"]),
        dimensions=int(values["dimensions"]),
    )
