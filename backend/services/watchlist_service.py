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
    """加入自选池（幂等），返回该行 dict。"""
    s = _with_session(session)
    owns = session is None
    try:
        return repo.add_to_watchlist(s, fund_code, note=note or None)
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
