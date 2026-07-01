"""LangChain tool 定义。

每个 tool 都是一层极薄的包装:它接受 LLM 传来的参数,调用对应的
service,把返回字典直接交给 LangChain。LLM 不接触网络或数据库 —
它只能通过这两个 tool 拿到数据,这与 system prompt 里
"数字必须来自工具"的要求一致。
"""
from langchain_core.tools import tool

from backend.services import fund_service as fs
from backend.tools.watchlist_tools import WATCHLIST_TOOLS
from backend.tools.market_tools import MARKET_TOOLS


@tool
def get_latest_fund_nav(fund_code: str) -> dict:
    """获取指定基金的最新净值(来自本地库,需先 refresh)。

    返回包含 `source` 与 `as_of` 的字典;若本地无数据则带 `error` 键。
    """
    return fs.get_latest_nav(fund_code)


@tool
def calculate_fund_metrics(fund_code: str, period: str = "1m") -> dict:
    """计算基金区间指标:阶段收益、最大回撤、波动率。

    `period ∈ {"1w","1m","3m","6m","1y"}`。
    """
    return fs.get_metrics(fund_code, period=period)


@tool
def get_fund_basic_info(fund_code: str) -> dict:
    """获取基金基础信息:名称、类型、经理、公司(来自本地库,需先 refresh_fund)。"""
    return fs.get_basic_info(fund_code)


@tool
def get_fund_nav_history(fund_code: str, start_date: str = "", end_date: str = "") -> dict:
    """获取基金带日期的历史净值序列,支持可选区间(YYYY-MM-DD,空=不限)。

    返回 {fund_code, navs:[{nav_date, accumulated_nav, daily_return}], count, source, as_of}。
    """
    return fs.get_nav_history(fund_code, start_date=start_date, end_date=end_date)


@tool
def refresh_fund(fund_code: str) -> dict:
    """联网拉取一只基金的最新基础信息与净值并入本地库。

    返回 `{fund_code, navs_inserted, already_up_to_date, source, as_of}`。
    当 `already_up_to_date=True` 时表示本地已是最新,不应再次调用本工具 —
    应切换到 `get_latest_fund_nav` / `get_fund_nav_history` 读取已有数据。
    """
    return fs.refresh_fund(fund_code)


# Phase-1 thin agent 兼容入口
TOOLS = [get_latest_fund_nav, calculate_fund_metrics]

FUND_TOOLS = [get_latest_fund_nav, calculate_fund_metrics,
              get_fund_basic_info, get_fund_nav_history, refresh_fund]

ALL_TOOLS = FUND_TOOLS + WATCHLIST_TOOLS + MARKET_TOOLS