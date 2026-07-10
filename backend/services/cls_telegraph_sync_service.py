"""财联社电报准实时同步服务。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from backend.config.settings import get_settings
from backend.db import repository as repo
from backend.db.session import get_session
from backend.services import cls_telegraph_client as cls_client

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
    timeout_seconds: float = 5.0,
    app_version: str = cls_client.DEFAULT_APP_VERSION,
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
    try:
        response = client.get(
            f"{cls_client.BASE_URL}/v1/roll/get_roll_list",
            params=signed,
            headers=cls_client.DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        payload = cls_client._curl_get_json(
            url=f"{cls_client.BASE_URL}/v1/roll/get_roll_list",
            params=signed,
            headers=cls_client.DEFAULT_HEADERS,
            timeout_seconds=timeout_seconds,
        )
    if payload.get("errno") not in (0, "0", None):
        raise RuntimeError(f"CLS roll-list errno={payload.get('errno')}: {payload.get('msg') or ''}")
    rows = ((payload.get("data") or {}).get("roll_data")) or []
    return [row for row in rows if isinstance(row, dict)]


def _is_market_relevant(row: dict) -> bool:
    text = " ".join([
        str(row.get("title") or ""),
        str(row.get("brief") or ""),
        str(row.get("content") or ""),
        " ".join(row.get("subjects") or []),
        " ".join(row.get("symbols") or []),
    ]).lower()
    return any(keyword in text for keyword in _MARKET_KEYWORDS)


def _trade_date(row: dict) -> str:
    published_at = row.get("published_at") or ""
    if len(published_at) >= 10:
        return published_at[:10]
    return datetime.now(cls_client.CLS_TIMEZONE).strftime("%Y-%m-%d")


def _to_market_evidence(row: dict) -> dict | None:
    if not _is_market_relevant(row):
        return None
    summary = row.get("brief") or row.get("content") or row.get("title")
    return {
        "trade_date": _trade_date(row),
        "brief_type": "post_market",
        "category": "news",
        "title": row["title"],
        "summary": summary,
        "symbols": row.get("symbols") or [],
        "metrics": {
            "cls_id": row.get("cls_id"),
            "cls_category": row.get("category") or "",
            "ctime": row.get("ctime"),
        },
        "source": "财联社",
        "source_url": row["source_url"],
        "published_at": row.get("published_at"),
        "reliability": "wire",
    }


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
    """执行一轮 CLS 电报同步。失败时保留旧状态并记录 `last_error`。"""
    settings = get_settings()
    page_size = page_size or int(settings.cls_telegraph_sync_page_size)
    max_pages = max_pages or int(settings.cls_telegraph_sync_max_pages)
    timeout_seconds = timeout_seconds or float(settings.cls_timeout_seconds)
    app_version = app_version or settings.cls_app_version
    fetch_page = fetch_page or fetch_cls_roll_page_raw

    owns_session = session is None
    s = session or get_session()
    owns_client = client is None
    if client is None:
        import httpx
        client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)

    fetched = 0
    inserted = 0
    evidence_inserted = 0
    newest_ctime: int | None = None
    newest_cls_id: str | None = None
    last_time = int(datetime.now(timezone.utc).timestamp())
    previous_state = repo.get_cls_telegraph_sync_state(s)

    try:
        for _page in range(max(1, int(max_pages))):
            raw_rows = fetch_page(
                client=client,
                category="",
                limit=page_size,
                last_time=last_time,
                timeout_seconds=timeout_seconds,
                app_version=app_version,
            )
            if not raw_rows:
                break
            page_min_ctime: int | None = None
            for raw in raw_rows:
                row = normalize_cls_telegraph_record(raw)
                if row is None:
                    continue
                fetched += 1
                if repo.upsert_cls_telegraph_item(s, row):
                    inserted += 1
                evidence = _to_market_evidence(row)
                if evidence is not None and repo.upsert_market_evidence(s, evidence):
                    evidence_inserted += 1
                ctime = row.get("ctime")
                if ctime is not None:
                    if newest_ctime is None or ctime > newest_ctime:
                        newest_ctime = int(ctime)
                        newest_cls_id = row["cls_id"]
                    if page_min_ctime is None or ctime < page_min_ctime:
                        page_min_ctime = int(ctime)
            if len(raw_rows) < int(page_size) or page_min_ctime is None:
                break
            last_time = max(0, page_min_ctime - 1)

        repo.update_cls_telegraph_sync_state(
            s,
            last_seen_ctime=newest_ctime,
            last_seen_cls_id=newest_cls_id,
            last_success_at=_now_iso(),
            last_error=None,
        )
        s.commit()
        return {
            "status": "completed",
            "fetched": fetched,
            "inserted": inserted,
            "evidence_inserted": evidence_inserted,
            "latest_cls_id": newest_cls_id,
        }
    except Exception as exc:  # noqa: BLE001
        try:
            s.rollback()
        except Exception as rollback_exc:  # noqa: BLE001
            logger.warning("[cls-sync] rollback failed: %s", rollback_exc)
        error = f"{type(exc).__name__}: {exc}"
        # `previous_state` 可能为 None（首跑 / 行被外部删）；用 .get 兼容。
        prev = previous_state or {}
        try:
            repo.update_cls_telegraph_sync_state(
                s,
                last_seen_ctime=prev.get("last_seen_ctime"),
                last_seen_cls_id=prev.get("last_seen_cls_id"),
                last_success_at=prev.get("last_success_at"),
                last_error=error,
            )
            s.commit()
        except Exception as state_exc:  # noqa: BLE001
            # 写 `last_error` 又失败（典型场景：SQLite database is locked）。
            # 不能让"记错误"这一步把整个 scheduler 触发器搞崩；
            # 降级为 logger.warning，下一轮 tick 再试。
            try:
                s.rollback()
            except Exception:
                pass
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
            "evidence_inserted": evidence_inserted,
            "last_error": error,
        }
    finally:
        if owns_client:
            try:
                client.close()
            except Exception:
                pass
        if owns_session:
            s.close()


def list_cls_telegraph_items(
    *,
    session=None,
    limit: int = 50,
    category: str | None = None,
    since_id: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    owns = session is None
    s = session or get_session()
    try:
        return repo.search_cls_telegraph_items(
            s,
            limit=limit,
            category=(category or "").strip() or None,
            since_id=(since_id or "").strip() or None,
            keyword=(keyword or "").strip() or None,
        )
    finally:
        if owns:
            s.close()


def get_cls_telegraph_sync_status(*, session=None) -> dict:
    owns = session is None
    s = session or get_session()
    try:
        state = repo.get_cls_telegraph_sync_state(s)
    finally:
        if owns:
            s.close()
    latest_ctime = state.get("last_seen_ctime")
    lag_seconds = None
    if latest_ctime is not None:
        lag_seconds = max(0, int(datetime.now(timezone.utc).timestamp()) - int(latest_ctime))
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
