"""应用配置(由 pydantic-settings 从环境变量加载)。

字段值优先来自进程环境变量,其次是 `backend/.env`。`env_file`
路径基于本模块位置解析,不依赖 CWD —— 这样不管用户从哪个目录
运行(项目根、`backend/`、`tests/`),都能找到正确的 `.env`。

`get_settings()` 用 `lru_cache` 记忆化,保证每个进程只读一次环境 —
测试可以在改 env 后清掉缓存重新读取。
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
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
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # DeepSeek 兼容 OpenAI 接口,所以复用 langchain_openai.ChatOpenAI。
    # 这里允许 None,是为了让应用在没有 key 时也能正常启动(只读路径
    # 仍可用);`build_agent()` 是真正的关卡,缺 key 时拒绝构造 LLM。
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    # PostgreSQL 数据库连接 URL。必须以 postgresql 开头。
    # 缺失时应用快速失败，不使用 SQLite 作为回退。
    database_url: str

    # ---- 数据库连接池参数 ----
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # 单位：秒。连接等待超过此时长直接抛 TimeoutError，避免 30s 默认值
    # 把 uvicorn 请求线程卡死。
    db_pool_timeout_seconds: float = 10.0

    # CORS 白名单，JSON 格式数组的环境变量会自动解析为 list
    allowed_origins: Optional[list[str]] = None

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

    # market evidence 每小时增量采集。Wave 1:16:00 / 08:30 cron 仍然保留,
    # hourly 用来"发现盘中财联社电报"(CLS adapter 只在 post_market 启用,故
    # hourly 也只跑 post_market brief_type)。同 brief_type 单飞锁由
    # market_evidence_service._lock 保证, 不会和 16:00 cron 撞车。
    # 调高间隔或设 enabled=false 可关闭。
    scheduler_evidence_hourly_enabled: bool = True
    scheduler_evidence_hourly_minutes: int = 60

    # 简报采集限额 + LLM 选择
    briefing_max_watchlist_funds: int = 30
    briefing_llm_model: str = "deepseek-chat"

    # 财联社电报信息源。v1 只用于 post_market evidence + 实时搜索 tool。
    cls_enabled: bool = True
    cls_search_enabled: bool = True
    cls_timeout_seconds: float = 15.0
    # CLS API 在晚高峰会慢于 5s,1 次重试能盖住大部分偶发超时。
    # 设为 1 表示「失败不重试」(兼容旧行为),生产环境推荐 1。
    cls_max_attempts: int = 1
    # 单次重试的退避秒数 (指数退避: 1s, 2s, 4s, ...)。
    cls_retry_base_seconds: float = 1.0
    cls_categories: str = "fund,watch,announcement,hk_us,red,remind"
    cls_per_category_limit: int = 10
    cls_max_search_limit: int = 10
    cls_app_version: str = "8.7.9"
    cls_telegraph_sync_enabled: bool = True
    cls_telegraph_sync_interval_seconds: int = 360
    cls_telegraph_sync_page_size: int = 50
    cls_telegraph_sync_max_pages: int = 3

    # 基金自选池驱动的市场知识库 / RAG 检索。默认开启本地管线,
    # 具体 LLM / embedding 调用由 service 层按可用配置降级。
    knowledge_rag_enabled: bool = True
    knowledge_vector_backend: Literal["auto", "pgvector", "structured"] = "auto"
    knowledge_embedding_base_url: Optional[str] = None
    knowledge_embedding_api_key: Optional[str] = None
    knowledge_embedding_model: Optional[str] = None
    knowledge_embedding_version: Optional[str] = None
    knowledge_embedding_dimensions: Optional[int] = Field(default=None, ge=1)
    knowledge_classification_model: Optional[str] = None
    knowledge_classification_prompt_version: str = "v1"
    knowledge_classification_batch_size: int = 10
    knowledge_classification_max_attempts: int = 3
    knowledge_classification_retry_seconds: int = 300
    knowledge_index_batch_size: int = 20
    knowledge_index_max_attempts: int = 3
    knowledge_index_retry_seconds: int = 300
    knowledge_default_ttl_days: int = 14
    knowledge_include_pending_fallback: bool = True
    knowledge_max_search_limit: int = 50
    knowledge_max_queue_status_limit: int = 200
    scheduler_knowledge_enabled: bool = True
    scheduler_knowledge_interval_minutes: int = 6
    # 中断任务恢复阈值(秒)。pending/running 超过此时间未更新则标记为 interrupted。
    knowledge_job_stale_seconds: int = 3600


@lru_cache
def get_settings() -> Settings:
    """返回进程内唯一的 Settings 实例。"""
    settings = Settings()
    # CORS origins 为 None 时使用默认值
    if settings.allowed_origins is None:
        settings.allowed_origins = ["http://localhost:3000"]
    return settings
