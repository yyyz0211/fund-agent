from langchain_core.tools import tool

from backend.services import fund_service as fs


@tool
def get_latest_fund_nav(fund_code: str) -> dict:
    """获取指定基金的最新净值（来自本地库，需先 refresh）。返回含 source 与 as_of。"""
    return fs.get_latest_nav(fund_code)


@tool
def calculate_fund_metrics(fund_code: str, period: str = "1m") -> dict:
    """计算基金区间指标：阶段收益、最大回撤、波动率。period ∈ {1w,1m,3m,6m,1y}。"""
    return fs.get_metrics(fund_code, period=period)


TOOLS = [get_latest_fund_nav, calculate_fund_metrics]
