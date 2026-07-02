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
    assert s.deepseek_model == "deepseek-chat"
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
    assert busy_timeout == 5000
    assert foreign_keys == 1


def test_sqlite_memory_engine_accepts_pragmas_without_wal_requirement():
    engine = make_engine("sqlite:///:memory:")

    with engine.connect() as conn:
        busy_timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
        foreign_keys = conn.execute(text("PRAGMA foreign_keys")).scalar()

    assert busy_timeout == 5000
    assert foreign_keys == 1
