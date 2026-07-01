"""自选池领域服务。

对 repository 的自选池 CRUD 做一层 session 管理封装，使 watchlist 工具
保持薄包装。自选池是本地用户数据，返回不带 source/as_of。
"""
from backend.db.session import get_session
from backend.db import repository as repo


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
        tx = repo.add_transaction(s, fund_code, attrs or {})
        wl = _recalc(s, fund_code)
        if wl is None:
            return None
        return {"transaction": tx, "watchlist": wl}
    finally:
        if owns:
            s.close()


def remove_transaction(tx_id: int, session=None) -> dict | None:
    """按 `tx_id` 删除一笔交易,删除后用剩余交易重算并回写 Watchlist。

    返回 {"removed": True, "transaction": <原交易摘要>, "watchlist": <新行>}
    或 None(交易不存在)。注意这里需要从被删交易拿到 fund_code,因
    为 delete 后 SQLAlchemy 实例已 expire。
    """
    s = _with_session(session)
    owns = session is None
    try:
        snapshot = repo.delete_transaction(s, tx_id)
        if snapshot is None:
            return None
        fund_code = snapshot["fund_code"]
        wl = _recalc(s, fund_code)
        return {"removed": True, "transaction": snapshot, "watchlist": wl}
    finally:
        if owns:
            s.close()


def _recalc(s, fund_code: str) -> dict | None:
    """薄包装:在当前 session 上调 transaction_service.recalc_holding。"""
    from backend.services.transaction_service import recalc_holding
    return recalc_holding(fund_code, session=s)
