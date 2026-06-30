"""自选池 LangChain 工具。薄包装 watchlist_service。"""
from langchain_core.tools import tool

from backend.services import watchlist_service as wsvc


@tool
def get_watchlist() -> list:
    """获取用户自选基金池的全部条目（含备注、持仓标记）。"""
    return wsvc.list_watchlist()


@tool
def add_fund_to_watchlist(fund_code: str, note: str = "") -> dict:
    """把一只基金加入自选池（幂等）。note 为可选备注。"""
    return wsvc.add(fund_code, note=note)


@tool
def remove_fund_from_watchlist(fund_code: str) -> dict:
    """从自选池移除一只基金。返回 {fund_code, removed}。"""
    return wsvc.remove(fund_code)


@tool
def update_fund_note(fund_code: str, note: str) -> dict:
    """更新自选池中某只基金的备注。基金不在池中时返回 error。"""
    return wsvc.update_note(fund_code, note)


WATCHLIST_TOOLS = [get_watchlist, add_fund_to_watchlist,
                   remove_fund_from_watchlist, update_fund_note]
