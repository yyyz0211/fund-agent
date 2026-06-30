"""LangChain tool 定义。

每个 tool 都是一层极薄的包装:它接受 LLM 传来的参数,调用对应的
service,把返回字典直接交给 LangChain。LLM 不接触网络或数据库 —
它只能通过这两个 tool 拿到数据,这与 system prompt 里
"数字必须来自工具"的要求一致。
"""
from langchain_core.tools import tool

from backend.services import fund_service as fs


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


TOOLS = [get_latest_fund_nav, calculate_fund_metrics]