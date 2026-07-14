"""LangChain tool 定义。

每个 tool 都是一层极薄的包装:它接受 LLM 传来的参数,调用对应的
service,把返回字典直接交给 LangChain。LLM 不直接接触网络或数据库 —
它只能通过受控 tool 拿到数据,这与 system prompt 里
"数字必须来自工具"的要求一致。
"""
from langchain_core.tools import tool

from backend.services.shared import diagnosis_service as ds
from backend.services.fund import fund_service as fs
from backend.tools.watchlist_tools import WATCHLIST_TOOLS
from backend.tools.market_tools import MARKET_TOOLS
from backend.tools.pnl_tools import PNL_TOOLS
from backend.tools.what_if_tools import WHAT_IF_TOOLS


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


@tool
def diagnose_fund(fund_code: str, period: str = "1y") -> dict:
    """对基金做本地体检:风险灯、避坑提示、适配人群和同类候选。

    `period ∈ {"1w","1m","3m","6m","1y"}`。输出是确定性规则结果,
    不是交易建议,不得解释为买卖/加减仓指令。
    """
    return ds.diagnose_fund(fund_code, period=period)


@tool
def lookup_fund_auto(
    fund_code: str,
    period: str = "1y",
    refresh_policy: str = "if_missing_or_stale",
) -> dict:
    """自动读取基金数据;本地缺失或过期时先 refresh_fund 再返回。

    适合回答"最新净值/最近怎么样/阶段收益"类问题。输出包含
    `fund/latest_nav/metrics/nav_history/errors/refresh/source/as_of`。
    """
    return fs.lookup_fund_auto(
        fund_code,
        period=period,
        refresh_policy=refresh_policy,
    )


@tool
def diagnose_fund_auto(
    fund_code: str,
    period: str = "1y",
    refresh_policy: str = "if_missing_or_stale",
) -> dict:
    """自动补齐本地基金数据后做基金体检。

    适合回答"能买吗/要不要卖/是否加仓/风险如何/同类对比"类问题。
    输出仍是确定性规则结果,不是强制交易指令或收益预测。
    """
    return fs.diagnose_fund_auto(
        fund_code,
        period=period,
        refresh_policy=refresh_policy,
    )


# Phase-1 thin agent 兼容入口
TOOLS = [get_latest_fund_nav, calculate_fund_metrics]

FUND_TOOLS = [get_latest_fund_nav, calculate_fund_metrics,
              get_fund_basic_info, get_fund_nav_history, refresh_fund,
              diagnose_fund, lookup_fund_auto, diagnose_fund_auto]

ALL_TOOLS = FUND_TOOLS + WATCHLIST_TOOLS + MARKET_TOOLS + PNL_TOOLS + WHAT_IF_TOOLS
