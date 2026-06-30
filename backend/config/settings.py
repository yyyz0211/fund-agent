"""应用配置(由 pydantic-settings 从环境变量加载)。

字段值优先来自环境变量,其次是项目根目录的 `.env`。
`get_settings()` 用 `lru_cache` 记忆化,保证每个进程只读一次环境 —
测试可以在改 env 后清掉缓存重新读取。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """后端运行时配置。

    所有字段都允许通过环境变量覆盖。`env_file=".env"` 让本地开发
    可以直接读 `.env`;生产环境应当由部署平台注入同名变量。
    `extra="ignore"` 让无关环境变量不会破坏模型,便于将来扩展。
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DeepSeek 兼容 OpenAI 接口,所以复用 langchain_openai.ChatOpenAI。
    # 这里允许 None,是为了让应用在没有 key 时也能正常启动(只读路径
    # 仍可用);`build_agent()` 是真正的关卡,缺 key 时拒绝构造 LLM。
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 默认指向 backend/data/ 下的本地 SQLite 文件。目录由
    # `db.init_db` / smoke 脚本按需创建。
    database_url: str = "sqlite:///backend/data/fund_agent.db"


@lru_cache
def get_settings() -> Settings:
    """返回进程内唯一的 Settings 实例。"""
    return Settings()