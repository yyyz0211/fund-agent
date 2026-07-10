from backend.config.settings import get_settings
from sqlalchemy import text

from backend.db.session import make_engine


def test_settings_defaults(monkeypatch):
    """没有 process env override 时,字面量默认值应当生效。

    注:`deepseek_api_key` 默认 `None` 但 `.env` 可能写入真实值,所以
    这里只断言 `.env` 通常不会覆盖的字段(base_url / model / db)。
    """
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.deepseek_base_url == "https://api.deepseek.com"
    assert s.deepseek_model == "deepseek-v4-flash"
    assert s.database_url == "sqlite:///backend/data/fund_agent.db"


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    get_settings.cache_clear()
    assert get_settings().deepseek_api_key == "sk-test"


def test_env_file_path_is_cwd_independent(tmp_path, monkeypatch):
    """`.env` 路径应当锚定到 backend 包位置,不依赖 CWD。

    之前用 `env_file=".env"` 在项目根跑会找不到 `backend/.env`,
    导致所有字段退回到 `None` / process env,触发 `ValidationError`。
    """
    from backend.config.settings import _ENV_FILE
    assert _ENV_FILE.is_absolute()
    assert _ENV_FILE.name == ".env"
    assert _ENV_FILE.parent.name == "backend"
    # 即便把 CWD 改到完全无关的目录,模块仍能找到真实的 `.env`
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    s = get_settings()
    assert s.deepseek_base_url == "https://api.deepseek.com"


def test_sqlite_engine_applies_concurrency_pragmas(tmp_path):
    db_path = tmp_path / "fund_agent.db"
    engine = make_engine(f"sqlite:///{db_path}")

    with engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        busy_timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
        foreign_keys = conn.execute(text("PRAGMA foreign_keys")).scalar()

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 15000
    assert foreign_keys == 1


def test_sqlite_memory_engine_accepts_pragmas_without_wal_requirement():
    engine = make_engine("sqlite:///:memory:")

    with engine.connect() as conn:
        busy_timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
        foreign_keys = conn.execute(text("PRAGMA foreign_keys")).scalar()

    assert busy_timeout == 15000
    assert foreign_keys == 1


def test_cls_settings_defaults(monkeypatch):
    for key in [
        "CLS_ENABLED",
        "CLS_SEARCH_ENABLED",
        "CLS_TIMEOUT_SECONDS",
        "CLS_CATEGORIES",
        "CLS_PER_CATEGORY_LIMIT",
        "CLS_MAX_SEARCH_LIMIT",
        "CLS_APP_VERSION",
        "CLS_TELEGRAPH_SYNC_ENABLED",
        "CLS_TELEGRAPH_SYNC_INTERVAL_SECONDS",
        "CLS_TELEGRAPH_SYNC_PAGE_SIZE",
        "CLS_TELEGRAPH_SYNC_MAX_PAGES",
    ]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.cls_enabled is True
    assert s.cls_search_enabled is True
    assert s.cls_timeout_seconds == 5.0
    assert s.cls_categories == "fund,watch,announcement,hk_us,red,remind"
    assert s.cls_per_category_limit == 10
    assert s.cls_max_search_limit == 10
    assert s.cls_app_version == "8.7.9"
    assert s.cls_telegraph_sync_enabled is True
    assert s.cls_telegraph_sync_interval_seconds == 360
    assert s.cls_telegraph_sync_page_size == 50
    assert s.cls_telegraph_sync_max_pages == 3


def test_cls_settings_read_env(monkeypatch):
    monkeypatch.setenv("CLS_ENABLED", "false")
    monkeypatch.setenv("CLS_SEARCH_ENABLED", "false")
    monkeypatch.setenv("CLS_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("CLS_CATEGORIES", "fund,watch")
    monkeypatch.setenv("CLS_PER_CATEGORY_LIMIT", "2")
    monkeypatch.setenv("CLS_MAX_SEARCH_LIMIT", "4")
    monkeypatch.setenv("CLS_APP_VERSION", "9.0.0")
    monkeypatch.setenv("CLS_TELEGRAPH_SYNC_ENABLED", "false")
    monkeypatch.setenv("CLS_TELEGRAPH_SYNC_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("CLS_TELEGRAPH_SYNC_PAGE_SIZE", "25")
    monkeypatch.setenv("CLS_TELEGRAPH_SYNC_MAX_PAGES", "2")
    get_settings.cache_clear()
    s = get_settings()
    assert s.cls_enabled is False
    assert s.cls_search_enabled is False
    assert s.cls_timeout_seconds == 3.5
    assert s.cls_categories == "fund,watch"
    assert s.cls_per_category_limit == 2
    assert s.cls_max_search_limit == 4
    assert s.cls_app_version == "9.0.0"
    assert s.cls_telegraph_sync_enabled is False
    assert s.cls_telegraph_sync_interval_seconds == 30
    assert s.cls_telegraph_sync_page_size == 25
    assert s.cls_telegraph_sync_max_pages == 2


def test_knowledge_settings_defaults(monkeypatch):
    for key in [
        "KNOWLEDGE_RAG_ENABLED",
        "KNOWLEDGE_VECTOR_BACKEND",
        "KNOWLEDGE_EMBEDDING_MODEL",
        "KNOWLEDGE_EMBEDDING_VERSION",
        "KNOWLEDGE_CLASSIFICATION_MODEL",
        "KNOWLEDGE_CLASSIFICATION_PROMPT_VERSION",
        "KNOWLEDGE_CLASSIFICATION_BATCH_SIZE",
        "KNOWLEDGE_CLASSIFICATION_MAX_ATTEMPTS",
        "KNOWLEDGE_CLASSIFICATION_RETRY_SECONDS",
        "KNOWLEDGE_INDEX_BATCH_SIZE",
        "KNOWLEDGE_DEFAULT_TTL_DAYS",
        "KNOWLEDGE_INCLUDE_PENDING_FALLBACK",
        "KNOWLEDGE_MAX_SEARCH_LIMIT",
        "KNOWLEDGE_MAX_QUEUE_STATUS_LIMIT",
        "SCHEDULER_KNOWLEDGE_ENABLED",
        "SCHEDULER_KNOWLEDGE_INTERVAL_MINUTES",
    ]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.knowledge_rag_enabled is True
    assert s.knowledge_vector_backend == "qdrant"
    assert s.knowledge_embedding_model is None
    assert s.knowledge_embedding_version is None
    assert s.knowledge_classification_model is None
    assert s.knowledge_classification_prompt_version == "v1"
    assert s.knowledge_classification_batch_size == 10
    assert s.knowledge_classification_max_attempts == 3
    assert s.knowledge_classification_retry_seconds == 300
    assert s.knowledge_index_batch_size == 20
    assert s.knowledge_default_ttl_days == 14
    assert s.knowledge_include_pending_fallback is True
    assert s.knowledge_max_search_limit == 50
    assert s.knowledge_max_queue_status_limit == 200
    assert s.scheduler_knowledge_enabled is True
    assert s.scheduler_knowledge_interval_minutes == 6


def test_knowledge_settings_read_env(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_RAG_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_VECTOR_BACKEND", "memory")
    monkeypatch.setenv("KNOWLEDGE_EMBEDDING_MODEL", "embed-test")
    monkeypatch.setenv("KNOWLEDGE_EMBEDDING_VERSION", "v2")
    monkeypatch.setenv("KNOWLEDGE_CLASSIFICATION_MODEL", "classify-test")
    monkeypatch.setenv("KNOWLEDGE_CLASSIFICATION_PROMPT_VERSION", "v9")
    monkeypatch.setenv("KNOWLEDGE_CLASSIFICATION_BATCH_SIZE", "3")
    monkeypatch.setenv("KNOWLEDGE_CLASSIFICATION_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("KNOWLEDGE_CLASSIFICATION_RETRY_SECONDS", "45")
    monkeypatch.setenv("KNOWLEDGE_INDEX_BATCH_SIZE", "4")
    monkeypatch.setenv("KNOWLEDGE_DEFAULT_TTL_DAYS", "21")
    monkeypatch.setenv("KNOWLEDGE_INCLUDE_PENDING_FALLBACK", "false")
    monkeypatch.setenv("KNOWLEDGE_MAX_SEARCH_LIMIT", "25")
    monkeypatch.setenv("KNOWLEDGE_MAX_QUEUE_STATUS_LIMIT", "75")
    monkeypatch.setenv("SCHEDULER_KNOWLEDGE_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_KNOWLEDGE_INTERVAL_MINUTES", "12")
    get_settings.cache_clear()
    s = get_settings()
    assert s.knowledge_rag_enabled is False
    assert s.knowledge_vector_backend == "memory"
    assert s.knowledge_embedding_model == "embed-test"
    assert s.knowledge_embedding_version == "v2"
    assert s.knowledge_classification_model == "classify-test"
    assert s.knowledge_classification_prompt_version == "v9"
    assert s.knowledge_classification_batch_size == 3
    assert s.knowledge_classification_max_attempts == 5
    assert s.knowledge_classification_retry_seconds == 45
    assert s.knowledge_index_batch_size == 4
    assert s.knowledge_default_ttl_days == 21
    assert s.knowledge_include_pending_fallback is False
    assert s.knowledge_max_search_limit == 25
    assert s.knowledge_max_queue_status_limit == 75
    assert s.scheduler_knowledge_enabled is False
    assert s.scheduler_knowledge_interval_minutes == 12
