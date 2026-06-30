"""Model construction for the Phase-4 LangGraph QA flow."""
from langchain_openai import ChatOpenAI

from backend.config.settings import get_settings
from backend.tools.fund_tools import ALL_TOOLS


def build_chat_model() -> ChatOpenAI:
    """Build the DeepSeek chat model without binding tools."""
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 未配置。请在 backend/.env 中设置后重试。")
    return ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=0,
    )


def build_tool_model(tools=None):
    """Build a DeepSeek chat model bound to Phase-3 tools."""
    return build_chat_model().bind_tools(ALL_TOOLS if tools is None else tools)
