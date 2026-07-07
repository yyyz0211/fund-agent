"""应用配置(由 pydantic-settings 从环境变量加载)。

字段值优先来自进程环境变量,其次是 `backend/.env`。`env_file`
路径基于本模块位置解析,不依赖 CWD —— 这样不管用户从哪个目录
运行(项目根、`backend/`、`tests/`),都能找到正确的 `.env`。

`get_settings()` 用 `lru_cache` 记忆化,保证每个进程只读一次环境 —
测试可以在改 env 后清掉缓存重新读取。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# `env_file` 用绝对路径,锚定到本模块所在目录的上一级(即 backend/),
# 保证 CWD 不会影响 `.env` 的查找。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """后端运行时配置。

    所有字段都允许通过环境变量覆盖。`extra="ignore"` 让无关环境变量
    不会破坏模型,便于将来扩展。
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore",
    )

    # DeepSeek 兼容 OpenAI 接口,所以复用 langchain_openai.ChatOpenAI。
    # 这里允许 None,是为了让应用在没有 key 时也能正常启动(只读路径
    # 仍可用);`build_agent()` 是真正的关卡,缺 key 时拒绝构造 LLM。
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 默认指向 backend/data/ 下的本地 SQLite 文件。目录由
    # `db.init_db` / smoke 脚本按需创建。
    database_url: str = "sqlite:///backend/data/fund_agent.db"

    # 定时刷新调度(APScheduler,进程内)。测试 / CI 里把 SCHEDULER_ENABLED
    # 设为 false 可避免起后台线程。cron 时间按 scheduler_timezone 解释。
    scheduler_enabled: bool = True
    scheduler_refresh_cron_hour: int = 20
    scheduler_refresh_cron_minute: int = 0
    scheduler_timezone: str = "Asia/Shanghai"

    # 每日简报调度(APScheduler,进程内)。与 daily_refresh 共存,可独立关闭。
    scheduler_briefing_enabled: bool = True
    scheduler_briefing_cron_hour: int = 17
    scheduler_briefing_cron_minute: int = 0

    # 简报采集限额 + LLM 选择
    briefing_max_watchlist_funds: int = 30
    briefing_llm_model: str = "deepseek-chat"


@lru_cache
def get_settings() -> Settings:
    """返回进程内唯一的 Settings 实例。"""
    return Settings()