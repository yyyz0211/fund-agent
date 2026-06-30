from backend.config.settings import get_settings


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
