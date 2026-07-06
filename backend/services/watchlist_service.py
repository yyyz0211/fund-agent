"""自选池领域服务。

对 repository 的自选池 CRUD 做一层 session 管理封装，使 watchlist 工具
保持薄包装。自选池是本地用户数据，返回不带 source/as_of。
"""
from sqlalchemy import func, select

from backend.db.session import get_session
from backend.db import repository as repo
from backend.db.models import FundTransaction, Watchlist


class InitialHoldingConflict(Exception):
    """基金已存在交易记录,不能再走 initial-holding 流程。

    路由层捕获后转 409,前端应提示用户改用 `/transactions` 端点加仓。
    """

    def __init__(self, fund_code: str, existing_tx_count: int):
        super().__init__(fund_code)
        self.fund_code = fund_code
        self.existing_tx_count = existing_tx_count


class TransactionNavMismatch(Exception):
    """交易 payload 的 nav 与本地同日累计净值不一致。"""

    def __init__(self, fund_code: str, tx_date: str, expected: float, got: float):
        super().__init__(fund_code, tx_date, expected, got)
        self.fund_code = fund_code
        self.tx_date = tx_date
        self.expected = expected
        self.got = got


class PendingBuyConflict(Exception):
    """待确认申购当前状态不允许继续确认。"""

    def __init__(self, fund_code: str, pending_id: int, status: str):
        super().__init__(fund_code, pending_id, status)
        self.fund_code = fund_code
        self.pending_id = pending_id
        self.status = status


class PendingBuyNavMissing(Exception):
    """确认申购时缺少确认日 NAV。"""

    def __init__(self, fund_code: str, tx_date: str):
        super().__init__(fund_code, tx_date)
        self.fund_code = fund_code
        self.tx_date = tx_date


def _with_session(session):
    return session or get_session()


def list_watchlist(session=None) -> list[dict]:
    """返回自选池全部行，空时返回 []。"""
    s = _with_session(session)
    owns = session is None
    try:
        return repo.get_watchlist(s)
    finally:
        if owns:
            s.close()


def add(fund_code: str, note: str = "", session=None) -> dict:
    """加入自选池（幂等），返回该行 dict。

    只接受 `note` —— 这是 LangChain `add_fund_to_watchlist` 工具的
    入参形状,不动它。
    """
    s = _with_session(session)
    owns = session is None
    try:
        return repo.add_to_watchlist(s, fund_code, note=note or None)
    finally:
        if owns:
            s.close()


def add_full(fund_code: str, attrs: dict, session=None) -> dict:
    """带完整字段集合加入自选池(幂等),给 HTTP POST 用。

    `attrs` 允许的 key:note / is_holding / is_focus / holding_amount /
    holding_share / cost_nav / buy_date。重复 fund_code 直接返回现有行,
    不会用 attrs 去覆盖已有数据 —— 想改请用 PATCH。
    """
    s = _with_session(session)
    owns = session is None
    try:
        return repo.add_to_watchlist_full(s, fund_code, attrs or {})
    finally:
        if owns:
            s.close()


def remove(fund_code: str, session=None) -> dict:
    """从自选池移除，返回 {fund_code, removed: bool}。"""
    s = _with_session(session)
    owns = session is None
    try:
        removed = repo.remove_from_watchlist(s, fund_code)
        return {"fund_code": fund_code, "removed": removed}
    finally:
        if owns:
            s.close()


def update_note(fund_code: str, note: str, session=None) -> dict:
    """更新备注，返回更新后的行；不在池中返回可读 error dict。"""
    s = _with_session(session)
    owns = session is None
    try:
        row = repo.update_watchlist_note(s, fund_code, note)
        if row is None:
            return {"error": f"{fund_code} 不在自选池中"}
        return row
    finally:
        if owns:
            s.close()


def get_one(fund_code: str, session=None) -> dict | None:
    """按 `fund_code` 查单条,不在池中返回 None。"""
    s = _with_session(session)
    owns = session is None
    try:
        return repo.get_watchlist_row(s, fund_code)
    finally:
        if owns:
            s.close()


def update(fund_code: str, patch: dict, session=None) -> dict | None:
    """按 `fund_code` 局部更新白名单字段,不在池中返回 None。

    入参 `patch` 是 dict,仅出现过的字段会被改;为区分"不动"和"显式
    清空",本服务不做 None 解释 —— 调用方需要清空某字段请用其它入口
    (或后续加 `clear_*` 工具)。返回更新后的行 dict,或 None。
    """
    s = _with_session(session)
    owns = session is None
    try:
        return repo.update_watchlist(s, fund_code, patch or {})
    finally:
        if owns:
            s.close()


def list_transactions(fund_code: str, session=None) -> list[dict]:
    """列出一只基金的全部买入/加仓记录(按日期+seq 升序)。"""
    s = _with_session(session)
    owns = session is None
    try:
        return repo.list_transactions(s, fund_code)
    finally:
        if owns:
            s.close()


def add_transaction(fund_code: str, attrs: dict, session=None) -> dict | None:
    """新增一笔买入记录,落库后自动重算并回写 Watchlist。

    返回 {"transaction": <新交易 dict>, "watchlist": <重算后的行>};
    基金不在自选池中返回 None —— 调用方发 404。
    """
    s = _with_session(session)
    owns = session is None
    try:
        if repo.get_watchlist_row(s, fund_code) is None:
            return None
        _validate_transaction_nav(s, fund_code, attrs or {})
        tx = repo.add_transaction(s, fund_code, attrs or {})
        wl = _recalc(s, fund_code)
        return {"transaction": tx, "watchlist": wl}
    finally:
        if owns:
            s.close()


def set_initial_holding(fund_code: str, attrs: dict, session=None) -> dict:
    """原子化创建/转持仓:自选行 + 首笔 buy 交易 + 持仓重算。

    返回 {"transaction": <新交易 dict>, "watchlist": <重算后的行>}。
    任何一步失败都会 rollback,不会留下 is_holding=true 但无交易/成本的
    半成品状态。

    Raises:
        InitialHoldingConflict: 目标基金已有交易历史(避免把首笔"initial"
            buy 静默合并到现有持仓,导致平均成本被错算)。
    """
    s = _with_session(session)
    owns = session is None
    data = attrs or {}
    try:
        _validate_transaction_nav(s, fund_code, data)
        w = s.scalar(select(Watchlist).where(Watchlist.fund_code == fund_code))
        if w is None:
            w = Watchlist(fund_code=fund_code)
            s.add(w)
            s.flush()
            existing_tx_count = 0
        else:
            existing_tx_count = s.scalar(
                select(func.count())
                .select_from(FundTransaction)
                .where(FundTransaction.fund_code == fund_code)
            ) or 0
            if existing_tx_count > 0:
                # 早期抛错,事务还没写任何东西,不需要回滚;
                # 但走 finally → close 一致性
                raise InitialHoldingConflict(fund_code, existing_tx_count)

        w.is_holding = True
        if data.get("is_focus") is not None:
            w.is_focus = bool(data["is_focus"])
        if data.get("watchlist_note") is not None:
            w.note = data["watchlist_note"]
        if data.get("amount") is not None:
            w.holding_amount = float(data["amount"])

        tx = repo.add_transaction(s, fund_code, {
            "tx_date": data["tx_date"],
            "amount": data["amount"],
            "nav": data["nav"],
            "fee": data.get("fee"),
            "note": data.get("note"),
            "kind": data.get("kind", "buy"),
        }, commit=False)
        wl = _recalc(s, fund_code, commit=False)
        s.commit()
        return {"transaction": tx, "watchlist": wl}
    except Exception:
        s.rollback()
        raise
    finally:
        if owns:
            s.close()


def remove_transaction(fund_code: str, tx_id: int, session=None) -> dict | None:
    """按 `tx_id` 删除一笔交易,删除后用剩余交易重算并回写 Watchlist。

    返回 {"removed": True, "transaction": <原交易摘要>, "watchlist": <新行>}
    或 None(交易不存在)。如果路径 fund_code 与交易所属基金不一致,
    返回带 error 的 dict,调用方应转 400,且不会删除任何数据。
    """
    s = _with_session(session)
    owns = session is None
    try:
        existing = repo.get_transaction(s, tx_id)
        if existing is None:
            return None
        if existing["fund_code"] != fund_code:
            return {"error": "fund_mismatch", "transaction": existing}
        snapshot = repo.delete_transaction(s, tx_id)
        wl = _recalc(s, fund_code)
        return {"removed": True, "transaction": snapshot, "watchlist": wl}
    finally:
        if owns:
            s.close()


def _recalc(s, fund_code: str, *, commit: bool = True) -> dict | None:
    """薄包装:在当前 session 上调 transaction_service.recalc_holding。"""
    from backend.services.transaction_service import recalc_holding
    return recalc_holding(fund_code, session=s, commit=commit)


def _validate_transaction_nav(s, fund_code: str, attrs: dict) -> None:
    """如果本地存在同日 NAV,要求交易 payload 使用同一个累计净值。

    没有同日 NAV 时不拦截,兼容历史 API 调用;前端新增的日期选择会
    在提交前强制精确读取 NAV。
    """
    tx_date = attrs.get("tx_date")
    if not tx_date or attrs.get("nav") is None:
        return
    nav = repo.get_nav_by_date(s, fund_code, tx_date)
    if nav is None or nav.get("accumulated_nav") is None:
        return
    expected = float(nav["accumulated_nav"])
    got = float(attrs["nav"])
    if abs(expected - got) > 1e-9:
        raise TransactionNavMismatch(fund_code, tx_date, expected, got)


def list_investment_plans(fund_code: str, session=None) -> list[dict] | None:
    """列出基金的定投计划;基金不在自选池中返回 None。"""
    s = _with_session(session)
    owns = session is None
    try:
        if repo.get_watchlist_row(s, fund_code) is None:
            return None
        return repo.list_investment_plans(s, fund_code)
    finally:
        if owns:
            s.close()


def add_investment_plan(fund_code: str, attrs: dict, session=None) -> dict | None:
    """新增定投计划;基金不在自选池中返回 None。"""
    s = _with_session(session)
    owns = session is None
    try:
        if repo.get_watchlist_row(s, fund_code) is None:
            return None
        return repo.add_investment_plan(s, fund_code, attrs or {})
    finally:
        if owns:
            s.close()


def update_investment_plan(fund_code: str, plan_id: int, patch: dict,
                           session=None) -> dict | None:
    """更新定投计划;不存在或 fund_code 不匹配返回 None。"""
    s = _with_session(session)
    owns = session is None
    try:
        if repo.get_watchlist_row(s, fund_code) is None:
            return None
        return repo.update_investment_plan(s, fund_code, plan_id, patch or {})
    finally:
        if owns:
            s.close()


def remove_investment_plan(fund_code: str, plan_id: int, session=None) -> dict | None:
    """删除定投计划;不存在或 fund_code 不匹配返回 None。"""
    s = _with_session(session)
    owns = session is None
    try:
        if repo.get_watchlist_row(s, fund_code) is None:
            return None
        plan = repo.delete_investment_plan(s, fund_code, plan_id)
        if plan is None:
            return None
        return {"removed": True, "plan": plan}
    finally:
        if owns:
            s.close()


def list_pending_buys(fund_code: str, session=None) -> list[dict] | None:
    """列出待确认申购记录;基金不在自选池中返回 None。"""
    s = _with_session(session)
    owns = session is None
    try:
        if repo.get_watchlist_row(s, fund_code) is None:
            return None
        return [_with_pending_buy_stage(s, row) for row in repo.list_pending_buys(s, fund_code)]
    finally:
        if owns:
            s.close()


def add_pending_buy(fund_code: str, attrs: dict, session=None) -> dict | None:
    """新增待确认申购;它不影响持仓份额和 PnL。"""
    s = _with_session(session)
    owns = session is None
    try:
        if repo.get_watchlist_row(s, fund_code) is None:
            return None
        row = repo.add_pending_buy(s, fund_code, attrs or {})
        return _with_pending_buy_stage(s, row)
    finally:
        if owns:
            s.close()


def cancel_pending_buy(fund_code: str, pending_id: int, session=None) -> dict | None:
    """把待确认申购标记为 cancelled。"""
    s = _with_session(session)
    owns = session is None
    try:
        if repo.get_watchlist_row(s, fund_code) is None:
            return None
        current = repo.get_pending_buy(s, fund_code, pending_id)
        if current is None:
            return None
        row = repo.update_pending_buy(s, fund_code, pending_id, {"status": "cancelled"})
        return _with_pending_buy_stage(s, row) if row else None
    finally:
        if owns:
            s.close()


def confirm_pending_buy(fund_code: str, pending_id: int, tx_date: str,
                        session=None) -> dict | None:
    """把待确认申购转换为正式 buy 交易并重算持仓。

    确认日 NAV 必须已经存在于本地库;确认后该笔才进入
    `FundTransaction` 和 PnL。
    """
    s = _with_session(session)
    owns = session is None
    try:
        if repo.get_watchlist_row(s, fund_code) is None:
            return None
        pending = repo.get_pending_buy(s, fund_code, pending_id)
        if pending is None:
            return None
        if pending["status"] != "pending":
            raise PendingBuyConflict(fund_code, pending_id, pending["status"])
        nav = repo.get_nav_by_date(s, fund_code, tx_date)
        if nav is None or nav.get("accumulated_nav") is None:
            raise PendingBuyNavMissing(fund_code, tx_date)
        nav_value = float(nav["accumulated_nav"])
        if nav_value <= 0:
            raise PendingBuyNavMissing(fund_code, tx_date)
        try:
            tx = repo.add_transaction(s, fund_code, {
                "tx_date": tx_date,
                "amount": pending["amount"],
                "nav": nav_value,
                "fee": pending.get("fee"),
                "note": pending.get("note"),
                "kind": "buy",
            }, commit=False)
            confirmed = repo.update_pending_buy(s, fund_code, pending_id, {
                "status": "confirmed",
                "nav_date": tx_date,
                "nav": nav_value,
                "share": tx.get("share"),
                "transaction_id": tx.get("id"),
            }, commit=False)
            wl = _recalc(s, fund_code, commit=False)
            s.commit()
            return {
                "pending_buy": _with_pending_buy_stage(s, confirmed),
                "transaction": tx,
                "watchlist": wl,
            }
        except Exception:
            s.rollback()
            raise
    finally:
        if owns:
            s.close()


def _with_pending_buy_stage(s, row: dict) -> dict:
    """给待确认申购补充 T 日展示字段。

    `stage` 是响应层计算字段,不入库:
    - submitted: 等待下一条本地 NAV
    - confirmable: 已有下一条本地 NAV,可按用户确认日落正式交易
    - confirmed/cancelled: 终态
    """
    if row is None:
        return row
    result = dict(row)
    status = result.get("status") or "pending"
    amount = float(result.get("amount") or 0.0)
    if status == "confirmed":
        result["stage"] = "confirmed"
        result["expected_confirm_date"] = result.get("nav_date")
        result["pending_amount"] = 0.0
        result["message"] = "已确认份额,已计入持仓盈亏。"
        return result
    if status == "cancelled":
        result["stage"] = "cancelled"
        result["expected_confirm_date"] = result.get("nav_date")
        result["pending_amount"] = 0.0
        result["message"] = "已取消,不计入持仓盈亏。"
        return result

    expected = repo.get_next_nav_date_after(
        s,
        str(result["fund_code"]),
        str(result["request_date"]),
    )
    result["expected_confirm_date"] = expected
    result["pending_amount"] = amount
    if expected:
        result["stage"] = "confirmable"
        result["message"] = f"预计确认日 {expected} 已有本地 NAV,可确认份额。"
    else:
        result["stage"] = "submitted"
        result["message"] = "已提交,等待下一交易日 NAV 后确认份额。"
    return result
