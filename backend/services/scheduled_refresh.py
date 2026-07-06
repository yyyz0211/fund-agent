"""自选池基金 NAV + 体检画像的定时批量刷新。

进程内、单用户场景:由 APScheduler 每日 cron 任务(见 `backend.scheduler`)
调用 `refresh_all_watchlist`,admin API 也可手动触发。最近一次运行结果放在
一个 Lock 保护的内存快照里;进程重启会丢失,对本地单用户应用可接受。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from uuid import uuid4

from backend.services import fund_profile_service as profile_service
from backend.services import fund_service
from backend.services import watchlist_service


_lock = Lock()
_last_run: dict = {}

_active_lock = Lock()
_active_job_id: str | None = None
_async_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scheduled-refresh")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _empty_snapshot() -> dict:
    """从未跑过时返回的全零快照。"""
    return {
        "last_run_at": None,
        "trigger": None,
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "already_up_to_date": 0,
        "failures": [],
    }


def _refresh_one(fund_code: str) -> dict:
    """刷新一只基金的 NAV + 体检画像。

    绝不抛异常:上游错误都被捕获并作为返回值,让整批循环能继续跑。
    NAV 失败判定该行失败;画像失败是软失败(NAV 已成功),只记录不算失败。
    """
    try:
        nav_result = fund_service.refresh_fund(fund_code)
    except Exception as exc:  # noqa: BLE001
        return {"fund_code": fund_code, "ok": False, "error": str(exc)}

    if isinstance(nav_result, dict) and "error" in nav_result:
        return {"fund_code": fund_code, "ok": False, "error": nav_result["error"]}

    already = bool(isinstance(nav_result, dict) and nav_result.get("already_up_to_date"))

    try:
        profile_service.refresh_profile(fund_code)
    except Exception as exc:  # noqa: BLE001
        return {
            "fund_code": fund_code,
            "ok": True,
            "already_up_to_date": already,
            "profile_error": str(exc),
        }

    return {"fund_code": fund_code, "ok": True, "already_up_to_date": already}


def refresh_all_watchlist(*, trigger: str = "scheduled", session=None) -> dict:
    """遍历自选池全部行,逐只刷新 NAV + 画像,并写入内存快照。

    单只失败记入 `failures`,绝不中断整批。
    """
    rows = watchlist_service.list_watchlist(session=session)
    failures: list[dict] = []
    succeeded = 0
    failed = 0
    already = 0
    for row in rows:
        outcome = _refresh_one(row["fund_code"])
        if outcome["ok"]:
            succeeded += 1
            if outcome.get("already_up_to_date"):
                already += 1
        else:
            failed += 1
            failures.append({"fund_code": outcome["fund_code"], "error": outcome.get("error")})

    snapshot = {
        "last_run_at": _now(),
        "trigger": trigger,
        "total": len(rows),
        "succeeded": succeeded,
        "failed": failed,
        "already_up_to_date": already,
        "failures": failures,
    }
    with _lock:
        _last_run.clear()
        _last_run.update(snapshot)
    return snapshot


def get_last_run() -> dict:
    """返回最近一次批量刷新快照;从未跑过时返回全零快照。"""
    with _lock:
        if not _last_run or _last_run.get("last_run_at") is None:
            return _empty_snapshot()
        return dict(_last_run)


def start_refresh_all_async(*, trigger: str = "manual") -> dict:
    """在后台线程触发一次批量刷新,立即返回,不阻塞请求线程。

    单飞:已有批次在跑时直接返回 running 状态,不再起第二个。
    """
    global _active_job_id
    with _active_lock:
        if _active_job_id is not None:
            return {"status": "running", "job_id": _active_job_id}
        job_id = uuid4().hex[:8]
        _active_job_id = job_id

    total = len(watchlist_service.list_watchlist())

    def _task() -> None:
        global _active_job_id
        try:
            refresh_all_watchlist(trigger=trigger)
        finally:
            with _active_lock:
                _active_job_id = None

    _async_executor.submit(_task)
    return {"status": "started", "total": total}


def reset_for_tests() -> None:
    """仅测试用:清空内存快照和 active-job 标记。"""
    global _active_job_id
    with _lock:
        _last_run.clear()
    with _active_lock:
        _active_job_id = None
