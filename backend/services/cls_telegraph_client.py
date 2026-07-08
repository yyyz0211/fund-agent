"""财联社电报客户端。

该模块负责 CLS 签名、文本清理、时间戳标准化，以及将原始 CLS 电报 JSON 转换为市场证据和 QA 工具所使用的标准化条目格式。
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


logger = logging.getLogger(__name__)
CLS_TIMEZONE = timezone(timedelta(hours=8))

BASE_URL = "https://www.cls.cn"
TELEGRAPH_REFERER = "https://www.cls.cn/telegraph"
DEFAULT_APP = "CailianpressWeb"
DEFAULT_OS = "web"
DEFAULT_APP_VERSION = "8.7.9"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Referer": TELEGRAPH_REFERER,
}


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def sign_params(params: dict) -> str:
    """Return CLS frontend-compatible sign: MD5(SHA1(canonical_query))."""
    ordered = sorted(params.items(), key=lambda item: str(item[0]).upper())
    query = "&".join(f"{key}={_stringify(value)}" for key, value in ordered)
    sha1 = hashlib.sha1(query.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1.encode("utf-8")).hexdigest()


def clean_html_text(value: Any) -> str:
    """Strip HTML tags/entities and normalize whitespace."""
    if value is None:
        return ""
    text = html.unescape(str(value))
    # Replace non-breaking spaces with regular spaces first.
    text = text.replace("\xa0", " ")
    # Strip <em> tags but keep their text content (no extra spaces for inline tags).
    text = re.sub(r"</?em[^>]*>", "", text, flags=re.IGNORECASE)
    # Remove all remaining HTML tags.
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse runs of whitespace into single spaces.
    return re.sub(r"\s+", " ", text).strip()


def parse_cls_time(value: Any, *, fallback: datetime | None = None) -> str:
    """Normalize CLS ctime or ISO strings to Asia/Shanghai local string."""
    dt: datetime
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            ts = float(value)
            if ts > 10_000_000_000:
                ts = ts / 1000
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            raw = str(value).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        dt = fallback or datetime.now(timezone.utc)
    return dt.astimezone(CLS_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _detail_url(item_id: Any) -> str | None:
    if item_id is None or str(item_id).strip() == "":
        return None
    return f"{BASE_URL}/detail/{item_id}"


def _extract_symbols(item: dict) -> list[str]:
    out: list[str] = []
    for stock in item.get("stock_list") or []:
        if not isinstance(stock, dict):
            continue
        for key in ("name", "StockID"):
            value = clean_html_text(stock.get(key))
            if value and value not in out:
                out.append(value)
    for subject in item.get("subjects") or []:
        if not isinstance(subject, dict):
            continue
        value = clean_html_text(subject.get("subject_name"))
        if value and value not in out:
            out.append(value)
    return out


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def normalize_telegraph_item(
    item: dict,
    category: str | None = None,
    *,
    now: datetime | None = None,
    summary_max_chars: int = 500,
) -> dict | None:
    """Normalize one raw CLS row into a stable item dict.

    Returns None when the row cannot produce a stable source URL.
    """
    item_id = item.get("id") or item.get("article_id")
    source_url = _detail_url(item_id)
    if not source_url:
        return None

    title = clean_html_text(item.get("title"))
    brief = clean_html_text(item.get("brief"))
    content = clean_html_text(item.get("content"))
    if not title:
        title = _truncate(brief or content, 80)
    if not title:
        return None

    summary = _truncate(brief or content or title, summary_max_chars)
    published_at = parse_cls_time(item.get("ctime"), fallback=now)
    images = item.get("images") or []
    audio_url = item.get("audio_url") or []

    return {
        "title": title,
        "summary": summary,
        "published_at": published_at,
        "source": "财联社",
        "source_url": source_url,
        "symbols": _extract_symbols(item),
        "metrics": {
            "cls_id": item_id,
            "cls_category": category or "",
            "level": item.get("level"),
            "reading_num": item.get("reading_num"),
            "comment_num": item.get("comment_num"),
            "share_num": item.get("share_num"),
            "images": images if isinstance(images, list) else [],
            "audio_url": audio_url if isinstance(audio_url, list) else [],
        },
    }


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


def _base_params(*, app_version: str = DEFAULT_APP_VERSION) -> dict[str, Any]:
    return {"app": DEFAULT_APP, "os": DEFAULT_OS, "sv": app_version}


def _signed_params(params: Mapping[str, Any], *, app_version: str) -> dict[str, Any]:
    out = {**params, **_base_params(app_version=app_version)}
    out["sign"] = sign_params(out)
    return out


def _elapsed(start: datetime) -> float:
    return (datetime.now(timezone.utc) - start).total_seconds()


def fetch_roll_list(
    *,
    client: Any,
    category: str = "",
    limit: int = 10,
    last_time: int | None = None,
    timeout_seconds: float = 5.0,
    app_version: str = DEFAULT_APP_VERSION,
) -> list[dict]:
    """Fetch one signed CLS roll-list page and return normalized rows."""
    started = datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "refresh_type": 1,
        "rn": max(1, int(limit)),
        "last_time": last_time or int(started.timestamp()),
    }
    if category:
        params["category"] = category
    signed = _signed_params(params, app_version=app_version)
    try:
        response = client.get(
            f"{BASE_URL}/v1/roll/get_roll_list",
            params=signed,
            headers=DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        status = getattr(response, "status_code", 0)
        response.raise_for_status()
        payload = response.json()
        if payload.get("errno") not in (0, "0", None):
            logger.warning(
                "[cls] GET /v1/roll/get_roll_list category=%s status=%s errno=%s elapsed=%.2fs",
                category, status, payload.get("errno"), _elapsed(started),
            )
            return []
        rows = ((payload.get("data") or {}).get("roll_data")) or []
        out = [normalize_telegraph_item(row, category=category, now=started) for row in rows]
        return [row for row in out if row is not None]
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[cls] GET /v1/roll/get_roll_list category=%s error=%s elapsed=%.2fs",
            category, type(exc).__name__, _elapsed(started),
        )
        return []


def search_telegraph(
    *,
    client: Any,
    keyword: str,
    category: str = "",
    limit: int = 10,
    timeout_seconds: float = 5.0,
    app_version: str = DEFAULT_APP_VERSION,
) -> list[dict]:
    """Search CLS telegraph with signed query params and JSON body."""
    started = datetime.now(timezone.utc)
    kw = clean_html_text(keyword)
    if not kw:
        return []
    signed = _signed_params({}, app_version=app_version)
    body = {
        "lastTime": int(started.timestamp()),
        "keyword": kw,
        "category": category or "",
        **_base_params(app_version=app_version),
    }
    try:
        response = client.post(
            f"{BASE_URL}/api/csw",
            params=signed,
            json=body,
            headers={**DEFAULT_HEADERS, "Content-Type": "application/json"},
            timeout=timeout_seconds,
        )
        status = getattr(response, "status_code", 0)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("list") or []
        out = [normalize_telegraph_item(row, category=category, now=started) for row in rows[:limit]]
        logger.info(
            "[cls] POST /api/csw category=%s status=%s count=%s elapsed=%.2fs",
            category, status, len([row for row in out if row is not None]), _elapsed(started),
        )
        return [row for row in out if row is not None]
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[cls] POST /api/csw category=%s error=%s elapsed=%.2fs",
            category, type(exc).__name__, _elapsed(started),
        )
        return []
