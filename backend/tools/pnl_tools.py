"""持仓 PnL LangChain 工具。

为 LLM 提供一个"基于自选池 + 本地最新 NAV 计算盈亏"的入口。
不主动调用网络 —— 所有 NAV 都从本地库读,需要用户先 `refresh_fund`。
"""
from langchain_core.tools import tool

from backend.services.fund import pnl_service as psvc


@tool
def calculate_holding_pnl(fund_codes: list[str] | None = None) -> dict:
    """计算自选池里 `is_holding=true` 的基金的当前浮盈浮亏。

    参数:
        fund_codes: 可选;不传则计算全部持仓行,传则只算列表里的那些
            (未在自选池的 code 会被忽略,但不会报错)。

    返回:
        {
          "as_of": "...",
          "source": "akshare",
          "items": [{fund_code, fund_name, current_nav, pnl_abs, pnl_pct, ...}],
          "totals": {invested, market_value, pnl_abs, pnl_pct, count},
          "skipped": [{fund_code, reason}, ...],
        }

    注意:本工具不返回买入/卖出建议 —— 数字仅供信息整理。
    """
    return psvc.calculate_pnl(fund_codes=fund_codes)


PNL_TOOLS = [calculate_holding_pnl]
