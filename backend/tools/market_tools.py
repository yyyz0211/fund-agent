"""市场数据 LangChain 工具。薄包装 market_service。"""
from langchain_core.tools import tool

from backend.services import market_service as msvc


@tool
def get_market_indices() -> dict:
    """获取最新一个交易日的主要市场指数（来自本地库，需先 refresh_market）。"""
    return msvc.get_indices()


@tool
def refresh_market() -> dict:
    """联网拉取主要市场指数当日行情并入本地库。返回 {inserted, source, as_of}。"""
    return msvc.refresh_market()


MARKET_TOOLS = [get_market_indices, refresh_market]
