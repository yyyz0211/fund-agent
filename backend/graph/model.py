"""DeepSeek model 构造:绑定 ALL_TOOLS 的 tool-calling model。

复用了现有 DeepSeek 配置（来自 settings），与 Phase 1 thin_agent 一致。
无 DEEPSEEK_API_KEY 时抛出 `DependencyUnavailableError`，与 thin_agent 行为一致。
"""
from langchain_openai import ChatOpenAI

from backend.config.settings import get_settings
from backend.exceptions import DependencyUnavailableError
from backend.tools.fund_tools import ALL_TOOLS


def build_model() -> ChatOpenAI:
    """构造绑定 ALL_TOOLS 的 DeepSeek tool-calling model。

    temperature=0 保证输出确定性，便于合规检查和测试。

    Raises:
        DependencyUnavailableError: 当 `DEEPSEEK_API_KEY` 缺失时。
    """
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise DependencyUnavailableError(
            "DEEPSEEK_API_KEY 未配置。请在 backend/.env 中设置后重试。",
            dependency="deepseek_api_key",
            fallback="使用 mock_model 或在 .env 配置后重试",
        )
    llm = ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=0,
    )
    return llm
