"""What-If 历史回测 LangChain 工具。

为 LLM 提供一个"给定权重组合,在历史某窗口内回测"的入口。
**绝对不预测未来** —— 所有数字都来自本地 NAV 表,本质是确定性回测。

合规边界:
- 工具返回结果里**强制**带 `disclaimer` 字段,LLM 在回答时必须引用;
- 不接受 `weights` 暗示"应该这样配仓" — `weights` 只是"用户的假设场景";
- 数据缺失时返回 error dict,不编数字。
"""
from langchain_core.tools import tool

from backend.db.session import get_session
from backend.services.fund import what_if_service as wsvc


@tool
def what_if_analysis(
    start_date: str,
    end_date: str,
    holdings: dict[str, float],
) -> dict:
    """历史回测:在 [start_date, end_date] 窗口内对给定权重组合做回测。

    参数:
        start_date: 起始日 (YYYY-MM-DD)。
        end_date: 截止日 (YYYY-MM-DD)。可以等于 start_date(表示单点窗口)。
        holdings: 假设的持仓权重,例如 {"110011": 0.5, "008888": 0.5}。
            权重和不必为 1,内部按"窗口有数据的 fund"重新归一化。

    返回:见 `what_if_service.backtest` 文档字符串。

    使用场景:用户问"如果我之前在 X 价位减仓 / 加仓会怎样"时调用本工具。
    **不在用户只问"现在能不能买"时调用** —— 那种场景用 `diagnose_fund`。
    """
    s = get_session()
    try:
        return wsvc.backtest(
            s,
            start_date=start_date,
            end_date=end_date,
            holdings=holdings,
        )
    finally:
        s.close()


WHAT_IF_TOOLS = [what_if_analysis]