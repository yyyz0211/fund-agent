"""API 启动与 health 端点（不依赖任何业务）。"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app

client = TestClient(app)
pytestmark = pytest.mark.unit


def test_health(monkeypatch):
    from backend.services.knowledge import knowledge_pgvector

    monkeypatch.setattr(
        knowledge_pgvector,
        "database_health_snapshot",
        lambda _engine: {"status": "ok", "dialect": "postgresql"},
    )
    monkeypatch.setattr(
        knowledge_pgvector,
        "knowledge_vector_health_snapshot",
        lambda _engine, _settings: {"status": "structured_fallback"},
    )

    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"]["status"] == "ok"
    assert body["knowledge_vector"]["status"] in {"disabled", "structured_fallback"}
    assert body["scheduler"]["status"] in {"running", "stopped"}


def test_health_reads_live_scheduler_state(monkeypatch):
    """health 必须读取 scheduler 实现模块的当前状态，而非导入时快照。"""
    from backend.scheduler import scheduler as scheduler_impl
    from backend.services.knowledge import knowledge_pgvector

    monkeypatch.setattr(scheduler_impl, "_scheduler", SimpleNamespace(running=True))
    monkeypatch.setattr(
        knowledge_pgvector,
        "database_health_snapshot",
        lambda _engine: {"status": "ok", "dialect": "postgresql"},
    )
    monkeypatch.setattr(
        knowledge_pgvector,
        "knowledge_vector_health_snapshot",
        lambda _engine, _settings: {"status": "disabled", "backend": "structured"},
    )

    body = client.get("/api/health").json()

    assert body["scheduler"] == {"status": "running"}


def test_health_preserves_top_level_status_when_database_is_unavailable(monkeypatch):
    from backend.services.knowledge import knowledge_pgvector

    monkeypatch.setattr(
        knowledge_pgvector,
        "database_health_snapshot",
        lambda _engine: {"status": "degraded", "dialect": "unknown", "error": "Offline"},
    )

    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    assert body["database"]["error"] == "Offline"


def test_health_degrades_top_level_for_explicit_pgvector_failure(monkeypatch):
    from backend.services.knowledge import knowledge_pgvector

    monkeypatch.setattr(
        knowledge_pgvector,
        "database_health_snapshot",
        lambda _engine: {"status": "ok", "dialect": "postgresql"},
    )
    monkeypatch.setattr(
        knowledge_pgvector,
        "knowledge_vector_health_snapshot",
        lambda _engine, _settings: {
            "status": "degraded",
            "backend": "pgvector",
            "reason": "dimension_mismatch",
        },
    )

    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    assert body["knowledge_vector"]["reason"] == "dimension_mismatch"


def test_vector_health_is_local_and_reports_explicit_pgvector_failure():
    from types import SimpleNamespace

    from backend.services.knowledge.knowledge_pgvector import knowledge_vector_health_snapshot

    settings = SimpleNamespace(
        knowledge_rag_enabled=True,
        knowledge_vector_backend="pgvector",
        knowledge_embedding_base_url="https://unused.example/v1",
        knowledge_embedding_api_key="secret",
        knowledge_embedding_model="embed-model",
        knowledge_embedding_version="v1",
        knowledge_embedding_dimensions=16,
    )
    engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

    snapshot = knowledge_vector_health_snapshot(engine, settings)

    assert snapshot == {
        "status": "degraded",
        "backend": "pgvector",
        "dialect": "mysql",
        "reason": "postgresql_required",
    }


def test_vector_health_detects_configured_database_dimension_mismatch():
    from types import SimpleNamespace

    from backend.services.knowledge.knowledge_pgvector import knowledge_vector_health_snapshot

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            rows = [
                ("document_id", "bigint"),
                ("embedding", "vector(768)"),
                ("embedding_model", "character varying"),
                ("embedding_version", "character varying"),
                ("content_hash", "character varying(64)"),
                ("created_at", "timestamp with time zone"),
                ("updated_at", "timestamp with time zone"),
            ]
            return SimpleNamespace(all=lambda: rows)

    class Engine:
        dialect = SimpleNamespace(name="postgresql")

        @staticmethod
        def connect():
            return Connection()

    settings = SimpleNamespace(
        knowledge_rag_enabled=True,
        knowledge_vector_backend="pgvector",
        knowledge_embedding_base_url="https://unused.example/v1",
        knowledge_embedding_api_key="secret",
        knowledge_embedding_model="embed-model",
        knowledge_embedding_version="v1",
        knowledge_embedding_dimensions=1024,
    )

    snapshot = knowledge_vector_health_snapshot(Engine(), settings)

    assert snapshot == {
        "status": "degraded",
        "backend": "pgvector",
        "dialect": "postgresql",
        "reason": "dimension_mismatch",
        "configured_dimensions": 1024,
        "database_dimensions": 768,
    }


def test_vector_health_rejects_incomplete_pgvector_schema():
    from types import SimpleNamespace

    from backend.services.knowledge.knowledge_pgvector import knowledge_vector_health_snapshot

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            return SimpleNamespace(all=lambda: [
                ("document_id", "bigint"),
                ("embedding", "vector(16)"),
            ])

    class Engine:
        dialect = SimpleNamespace(name="postgresql")

        @staticmethod
        def connect():
            return Connection()

    settings = SimpleNamespace(
        knowledge_rag_enabled=True,
        knowledge_vector_backend="pgvector",
        knowledge_embedding_base_url="https://unused.example/v1",
        knowledge_embedding_api_key="secret",
        knowledge_embedding_model="embed-model",
        knowledge_embedding_version="v1",
        knowledge_embedding_dimensions=16,
    )

    snapshot = knowledge_vector_health_snapshot(Engine(), settings)

    assert snapshot["status"] == "degraded"
    assert snapshot["reason"] == "incomplete_schema"
    assert snapshot["missing_columns"] == [
        "content_hash",
        "created_at",
        "embedding_model",
        "embedding_version",
        "updated_at",
    ]


def test_openapi_has_four_routers():
    """四个 router 模块都设置好 prefix —— 通过 router 暴露的 prefix 字段验证。

    Task 2/3 填上 `@router.get(...)` 后，OpenAPI 自动会出现具体路径。
    """
    from backend.api.routes import funds, market, watchlist, announcements
    assert funds.router.prefix == "/api/funds"
    assert watchlist.router.prefix == "/api/watchlist"
    assert market.router.prefix == "/api/market"
    assert announcements.router.prefix == "/api/announcements"


def test_openapi_paths_match_spec():
    """/api/health 是 app.py 自身的端点，必须存在；Task 2/3 会填充更多 path。"""
    r = client.get("/openapi.json")
    paths = r.json()["paths"]
    assert "/api/health" in paths
