"""财联社电报准实时同步服务。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from backend.config.settings import get_settings
from backend.db import repository as repo
from backend.db.session_scope import session_scope
from backend.services.knowledge import cls_telegraph_client as cls_client

logger = logging.getLogger(__name__)

_MARKET_KEYWORDS = (
    "a股", "港股", "美股", "股市", "股票", "指数", "基金", "etf",
    "债券", "央行", "证监会", "上交所", "深交所", "北交所",
    "期货", "原油", "黄金", "人民币", "美元", "半导体", "新能源",
    "电池", "医药", "地产", "消费", "券商", "银行", "保险",
    "算力", "ai", "人工智能", "机器人", "低空经济", "板块",
)


def _now_iso() -> str:
    return datetime.now(cls_client.CLS_TIMEZONE).isoformat(timespec="seconds")


def _ctime_seconds(value: Any) -> int | None:
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return None
    if ts > 10_000_000_000:
        ts = ts // 1000
    return ts


def _extract_subjects(item: dict) -> list[str]:
    out: list[str] = []
    for subject in item.get("subjects") or []:
        if not isinstance(subject, dict):
            continue
        name = cls_client.clean_html_text(subject.get("subject_name"))
        if name and name not in out:
            out.append(name)
    return out


def normalize_cls_telegraph_record(item: dict, category: str | None = None) -> dict | None:
    """把 CLS roll-list 原始行标准化为 `cls_telegraph_items` 可写入结构。"""
    item_id = item.get("id") or item.get("article_id")
    if item_id is None or str(item_id).strip() == "":
        return None
    source_url = f"{cls_client.BASE_URL}/detail/{item_id}"
    title = cls_client.clean_html_text(item.get("title"))
    brief = cls_client.clean_html_text(item.get("brief"))
    content = cls_client.clean_html_text(item.get("content"))
    if not title:
        title = brief or content
    if not title:
        return None

    ctime = _ctime_seconds(item.get("ctime"))
    raw_category = cls_client.clean_html_text(item.get("category") or item.get("cat_name"))
    return {
        "cls_id": str(item_id),
        "title": title,
        "brief": brief or None,
        "content": content or None,
        "category": category or raw_category or None,
        "subjects": _extract_subjects(item),
        "symbols": cls_client._extract_symbols(item),  # 复用现有 CLS evidence 解析逻辑
        "source_url": source_url,
        "ctime": ctime,
        "published_at": cls_client.parse_cls_time(item.get("ctime")),
        "raw_json": item,
    }


def fetch_cls_roll_page_raw(
    *,
    client: Any,
    category: str = "",
    limit: int = 50,
    last_time: int | None = None,
    timeout_seconds: float = 15.0,
    app_version: str = cls_client.DEFAULT_APP_VERSION,
    max_attempts: int = 1,
    retry_base_seconds: float = 1.0,
) -> list[dict]:
    """抓取一页 CLS roll-list 原始行。"""
    started = datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "refresh_type": 1,
        "rn": max(1, int(limit)),
        "last_time": last_time or int(started.timestamp()),
    }
    if category:
        params["category"] = category
    signed = cls_client._signed_params(params, app_version=app_version)
    payload = cls_client._retry_get_with_curl(
        client=client,
        path="/v1/roll/get_roll_list",
        params=signed,
        headers=cls_client.DEFAULT_HEADERS,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        base_delay=retry_base_seconds,
        category=category,
    )
    if payload.get("errno") not in (0, "0", None):
        raise RuntimeError(f"CLS roll-list errno={payload.get('errno')}: {payload.get('msg') or ''}")
    rows = ((payload.get("data") or {}).get("roll_data")) or []
    return [row for row in rows if isinstance(row, dict)]


def sync_cls_telegraph_once(
    *,
    session=None,
    client: Any | None = None,
    fetch_page: Callable[..., list[dict]] | None = None,
    page_size: int | None = None,
    max_pages: int | None = None,
    timeout_seconds: float | None = None,
    app_version: str | None = None,
) -> dict:
    """执行一轮 CLS 电报同步。失败时保留旧状态并记录 `last_error`。

    事务边界:
    - 外部 `session` 注入时,调用方拥有事务;本函数只在每页/状态写入后 flush,
      由调用方决定 commit/rollback。
    - 外部不注入时,每页 fetch 在事务外,upsert/状态更新走 `session_scope()`
      short-tx;任何单页失败保留 `previous_state` 并仅写一条 `last_error`。
    """
    settings = get_settings()
    page_size = page_size or int(settings.cls_telegraph_sync_page_size)
    max_pages = max_pages or int(settings.cls_telegraph_sync_max_pages)
    timeout_seconds = timeout_seconds or float(settings.cls_timeout_seconds)
    app_version = app_version or settings.cls_app_version
    max_attempts = max(1, int(getattr(settings, "cls_max_attempts", 1)))
    retry_base_seconds = float(getattr(settings, "cls_retry_base_seconds", 1.0))
    fetch_page = fetch_page or fetch_cls_roll_page_raw

    owns_session = session is None
    owns_client = client is None
    if client is None:
        import httpx
        client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)

    try:
        if owns_session:
            return _sync_pages_with_own_session(
                fetch_page=fetch_page,
                client=client,
                page_size=page_size,
                max_pages=max_pages,
                timeout_seconds=timeout_seconds,
                app_version=app_version,
                max_attempts=max_attempts,
                retry_base_seconds=retry_base_seconds,
            )
        return _sync_pages_with_external_session(
            session=session,
            fetch_page=fetch_page,
            client=client,
            page_size=page_size,
            max_pages=max_pages,
            timeout_seconds=timeout_seconds,
            app_version=app_version,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
        )
    finally:
        if owns_client:
            try:
                client.close()
            except Exception:
                pass


def _sync_pages_with_own_session(
    *,
    fetch_page,
    client,
    page_size: int,
    max_pages: int,
    timeout_seconds: float,
    app_version: str,
    max_attempts: int,
    retry_base_seconds: float,
) -> dict:
    """顶层入口:每页 fetch 在事务外,upsert 走 short-tx。"""
    last_time, previous_state = _load_last_time_for_page()
    newest_ctime: int | None = None
    newest_cls_id: str | None = None
    fetched = 0
    inserted = 0

    try:
        for _page in range(max(1, int(max_pages))):
            # stage 1: fetch one page (no DB transaction)
            raw_rows = fetch_page(
                client=client,
                category="",
                limit=page_size,
                last_time=last_time,
                timeout_seconds=timeout_seconds,
                app_version=app_version,
                max_attempts=max_attempts,
                retry_base_seconds=retry_base_seconds,
            )
            if not raw_rows:
                break
            # stage 2: short-tx upsert of this page + local newest tracking
            page_inserted, newest_ctime, newest_cls_id, page_min_ctime = (
                _persist_page(
                    raw_rows=raw_rows,
                    newest_ctime=newest_ctime,
                    newest_cls_id=newest_cls_id,
                )
            )
            fetched += len(raw_rows)
            inserted += page_inserted
            if len(raw_rows) < int(page_size) or page_min_ctime is None:
                break
            last_time = max(0, page_min_ctime - 1)

        # stage 3: short-tx state update
        _record_success(newest_ctime=newest_ctime, newest_cls_id=newest_cls_id)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        _record_failure(error=error, previous_state=previous_state)
        logger.warning("[cls-sync] sync failed: %s", error)
        return {
            "status": "failed",
            "fetched": fetched,
            "inserted": inserted,
            "evidence_inserted": 0,
            "last_error": error,
        }

    return {
        "status": "completed",
        "fetched": fetched,
        "inserted": inserted,
        "evidence_inserted": 0,
        "latest_cls_id": newest_cls_id,
    }


def _sync_pages_with_external_session(
    *,
    session,
    fetch_page,
    client,
    page_size: int,
    max_pages: int,
    timeout_seconds: float,
    app_version: str,
    max_attempts: int,
    retry_base_seconds: float,
) -> dict:
    """调用方注入 session 时仍保留单事务流,但每页走完 flush()。

    调用方拥有 commit/rollback；service 仅 flush、不 commit/rollback/close。
    """
    previous_state = repo.get_cls_telegraph_sync_state(session) or {}
    last_time, _ = _load_last_time_for_page()
    newest_ctime: int | None = None
    newest_cls_id: str | None = None
    fetched = 0
    inserted = 0

    try:
        for _page in range(max(1, int(max_pages))):
            raw_rows = fetch_page(
                client=client,
                category="",
                limit=page_size,
                last_time=last_time,
                timeout_seconds=timeout_seconds,
                app_version=app_version,
                max_attempts=max_attempts,
                retry_base_seconds=retry_base_seconds,
            )
            if not raw_rows:
                break
            page_min_ctime: int | None = None
            for raw in raw_rows:
                row = normalize_cls_telegraph_record(raw)
                if row is None:
                    continue
                fetched += 1
                if repo.upsert_cls_telegraph_item(session, row):
                    inserted += 1
                ctime = row.get("ctime")
                if ctime is not None:
                    if newest_ctime is None or ctime > newest_ctime:
                        newest_ctime = int(ctime)
                        newest_cls_id = row["cls_id"]
                    if page_min_ctime is None or ctime < page_min_ctime:
                        page_min_ctime = int(ctime)
            session.flush()
            if len(raw_rows) < int(page_size) or page_min_ctime is None:
                break
            last_time = max(0, page_min_ctime - 1)

        repo.update_cls_telegraph_sync_state(
            session,
            last_seen_ctime=newest_ctime,
            last_seen_cls_id=newest_cls_id,
            last_success_at=_now_iso(),
            last_error=None,
        )
        session.flush()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        prev = previous_state or {}
        try:
            repo.update_cls_telegraph_sync_state(
                session,
                last_seen_ctime=prev.get("last_seen_ctime"),
                last_seen_cls_id=prev.get("last_seen_cls_id"),
                last_success_at=prev.get("last_success_at"),
                last_error=error,
            )
            session.flush()
        except Exception as state_exc:  # noqa: BLE001
            logger.warning(
                "[cls-sync] sync failed (%s) AND state update failed (%s)",
                error, state_exc,
            )
        else:
            logger.warning("[cls-sync] sync failed: %s", error)
        return {
            "status": "failed",
            "fetched": fetched,
            "inserted": inserted,
            "evidence_inserted": 0,
            "last_error": error,
        }

    return {
        "status": "completed",
        "fetched": fetched,
        "inserted": inserted,
        "evidence_inserted": 0,
        "latest_cls_id": newest_cls_id,
    }


def _load_last_time_for_page() -> tuple[int, dict | None]:
    """读 sync state,返回 (last_time_for_next_page, previous_state_snapshot)。"""
    with session_scope() as s:
        state = repo.get_cls_telegraph_sync_state(s) or {}
    last_seen = state.get("last_seen_ctime")
    if last_seen:
        try:
            return max(0, int(last_seen) - 1), state
        except (TypeError, ValueError):
            return int(datetime.now(timezone.utc).timestamp()), state
    return int(datetime.now(timezone.utc).timestamp()), state


def _persist_page(
    *,
    raw_rows: list[dict],
    newest_ctime: int | None,
    newest_cls_id: str | None,
) -> tuple[int, int | None, str | None, int | None]:
    """对一页 raw_rows 做归一化并写入 short-tx。

    Returns:
        (inserted, newest_ctime, newest_cls_id, page_min_ctime)
    """
    inserted = 0
    page_min_ctime: int | None = None
    with session_scope() as s:
        for raw in raw_rows:
            row = normalize_cls_telegraph_record(raw)
            if row is None:
                continue
            if repo.upsert_cls_telegraph_item(s, row):
                inserted += 1
            ctime = row.get("ctime")
            if ctime is not None:
                if newest_ctime is None or ctime > newest_ctime:
                    newest_ctime = int(ctime)
                    newest_cls_id = row["cls_id"]
                if page_min_ctime is None or ctime < page_min_ctime:
                    page_min_ctime = int(ctime)
    return inserted, newest_ctime, newest_cls_id, page_min_ctime


def _record_success(*, newest_ctime: int | None, newest_cls_id: str | None) -> None:
    with session_scope() as s:
        repo.update_cls_telegraph_sync_state(
            s,
            last_seen_ctime=newest_ctime,
            last_seen_cls_id=newest_cls_id,
            last_success_at=_now_iso(),
            last_error=None,
        )


def _record_failure(*, error: str, previous_state: dict | None) -> None:
    prev = previous_state or {}
    try:
        with session_scope() as s:
            repo.update_cls_telegraph_sync_state(
                s,
                last_seen_ctime=prev.get("last_seen_ctime"),
                last_seen_cls_id=prev.get("last_seen_cls_id"),
                last_success_at=prev.get("last_success_at"),
                last_error=error,
            )
    except Exception as state_exc:  # noqa: BLE001
        logger.warning(
            "[cls-sync] sync failed (%s) AND state update failed (%s)",
            error, state_exc,
        )


def list_cls_telegraph_items(
    *,
    session=None,
    limit: int = 50,
    category: str | None = None,
    since_id: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """只读视图。owning 时 short-tx；caller-provided 时沿用其 session。"""
    if session is not None:
        return repo.search_cls_telegraph_items(
            session,
            limit=limit,
            category=(category or "").strip() or None,
            since_id=(since_id or "").strip() or None,
            keyword=(keyword or "").strip() or None,
        )
    with session_scope() as s:
        return repo.search_cls_telegraph_items(
            s,
            limit=limit,
            category=(category or "").strip() or None,
            since_id=(since_id or "").strip() or None,
            keyword=(keyword or "").strip() or None,
        )


def get_cls_telegraph_sync_status(*, session=None) -> dict:
    """只读视图。owning 时 short-tx；caller-provided 时沿用其 session。"""
    if session is not None:
        state = repo.get_cls_telegraph_sync_state(session) or {}
    else:
        with session_scope() as s:
            state = repo.get_cls_telegraph_sync_state(s) or {}
    latest_ctime = state.get("last_seen_ctime")
    lag_seconds = None
    if latest_ctime is not None:
        try:
            lag_seconds = max(0, int(datetime.now(timezone.utc).timestamp()) - int(latest_ctime))
        except (TypeError, ValueError):
            lag_seconds = None
    if state.get("last_error"):
        status = "failed"
    elif state.get("last_success_at"):
        status = "ok"
    else:
        status = "idle"
    return {
        "status": status,
        "last_success_at": state.get("last_success_at"),
        "latest_cls_id": state.get("last_seen_cls_id"),
        "lag_seconds": lag_seconds,
        "last_error": state.get("last_error"),
    }


def run_scheduled_cls_telegraph_sync() -> dict:
    """Scheduler entrypoint."""
    settings = get_settings()
    if not bool(settings.cls_telegraph_sync_enabled):
        return {"status": "disabled"}
    return sync_cls_telegraph_once()
