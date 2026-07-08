# 财联社电报信息源 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 财联社电报 as a backend market information source by storing normalized wire items in `market_evidence` and exposing a real-time CLS search tool for QA.

**Architecture:** Keep CLS protocol concerns in `backend/services/cls_telegraph_client.py`, map normalized items to evidence rows in `backend/services/market_sources/cls_telegraph.py`, and expose real-time search through `backend/tools/market_tools.py`. Reuse the existing `market_evidence` ingestion pipeline, scheduler, repository, and LangGraph tool aggregation; do not add a new table or frontend surface.

**Tech Stack:** Python, httpx-style injected clients, pydantic-settings, SQLAlchemy-backed `market_evidence`, LangChain tools, pytest, selectolax for HTML tag cleanup.

## Global Constraints

- Do not add a frontend news center, filter panel, detail page, or manual refresh UI.
- Do not add a separate `cls_news` table.
- Do not perform large historical backfill.
- Do not batch-fetch CLS detail pages in v1.
- Do not bypass login, paywalls, or VIP-only content.
- Do not make CLS the only source for NAV, market quotes, or announcements.
- Fixed CLS params: `app=CailianpressWeb`, `os=web`, `sv=8.7.9`.
- Default categories: `fund,watch,announcement,hk_us,red,remind`.
- Default limits: `CLS_PER_CATEGORY_LIMIT=10`, `CLS_MAX_SEARCH_LIMIT=10`, `CLS_TIMEOUT_SECONDS=5`.
- Evidence category for CLS rows is `news`; original CLS category is stored in `metrics.cls_category`.
- Store only title, short summary, metadata, and source URL; do not persist full long-form content.
- All CLS failures must degrade to empty results or controlled error payloads; existing evidence collection must continue.
- Start implementation from a clean worktree or keep spec-only changes in a separate commit before code tasks.

---

## File Structure

Create or modify these files:

- Create `backend/services/cls_telegraph_client.py`
  - Owns signing, request construction, HTML/text cleanup, timestamp parsing, normalization, list fetch, and search fetch.
- Create `backend/services/market_sources/cls_telegraph.py`
  - Defines `ClsTelegraphAdapter`, converting normalized CLS items into `market_evidence` row dicts.
- Modify `backend/services/market_sources/__init__.py`
  - Exports `ClsTelegraphAdapter` and appends it in `build_default_adapters` for `post_market` when `CLS_ENABLED=true`.
- Modify `backend/config/settings.py`
  - Adds CLS runtime configuration.
- Modify `backend/.env.example` and `.env.example`
  - Documents CLS configuration.
- Modify `backend/tools/market_tools.py`
  - Adds `search_cls_telegraph` tool and updates existing evidence tool docs to include `news`.
- Modify `backend/tools/fund_tools.py`
  - No direct code change expected unless `ALL_TOOLS` tests reveal aggregation assumptions; `ALL_TOOLS` already includes `MARKET_TOOLS`.
- Modify `backend/graph/prompts.py`
  - Updates tool guidance for `category="news"` and real-time CLS search.
- Add `backend/tests/test_cls_telegraph_client.py`
  - Tests pure helpers and HTTP fetch/search behavior with fake clients.
- Modify `backend/tests/test_market_source_adapters.py`
  - Tests `ClsTelegraphAdapter` mapping and failure isolation.
- Modify `backend/tests/test_settings.py`
  - Tests CLS defaults and environment overrides.
- Modify `backend/tests/test_tools.py`
  - Tests `search_cls_telegraph` tool and updated tool lists.
- Add or modify `backend/tests/test_market_sources_cls_config.py`
  - Tests `build_default_adapters` includes CLS only for `post_market` when enabled.

---

### Task 1: CLS Signing And Normalization Helpers

**Files:**
- Create: `backend/services/cls_telegraph_client.py`
- Create: `backend/tests/test_cls_telegraph_client.py`

**Interfaces:**
- Produces:
  - `sign_params(params: Mapping[str, Any]) -> str`
  - `clean_html_text(value: Any) -> str`
  - `parse_cls_time(value: Any, *, fallback: datetime | None = None) -> str`
  - `normalize_telegraph_item(item: Mapping[str, Any], category: str | None = None, *, now: datetime | None = None, summary_max_chars: int = 500) -> dict | None`
- Consumes: only Python stdlib plus `selectolax`.

- [ ] **Step 1: Write failing tests for signing and text cleanup**

Add this to `backend/tests/test_cls_telegraph_client.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone


def test_sign_params_matches_observed_cls_signature():
    from backend.services.cls_telegraph_client import sign_params

    params = {
        "refresh_type": 1,
        "rn": 5,
        "last_time": 1783482113,
        "os": "web",
        "sv": "8.7.9",
        "app": "CailianpressWeb",
    }

    assert sign_params(params) == "237f3789813b4aeb4bf302c9300c4d69"


def test_clean_html_text_removes_em_tags_and_collapses_space():
    from backend.services.cls_telegraph_client import clean_html_text

    text = "【南方<em>基</em><em>金</em>】\\n\\n  光通信&nbsp;赛道"

    assert clean_html_text(text) == "【南方基金】 光通信 赛道"


def test_parse_cls_time_accepts_seconds_millis_and_iso():
    from backend.services.cls_telegraph_client import parse_cls_time

    assert parse_cls_time(1783481506) == "2026-07-08 11:31:46"
    assert parse_cls_time(1783481506000) == "2026-07-08 11:31:46"
    assert parse_cls_time("2026-07-08T11:31:46+08:00") == "2026-07-08 11:31:46"


def test_parse_cls_time_falls_back_to_now():
    from backend.services.cls_telegraph_client import parse_cls_time

    fallback = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)

    assert parse_cls_time("bad", fallback=fallback) == "2026-07-08 20:00:00"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_cls_telegraph_client.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.cls_telegraph_client'`.

- [ ] **Step 3: Implement pure helper functions**

Create `backend/services/cls_telegraph_client.py` with this initial content:

```python
"""财联社电报客户端 helpers.

This module owns CLS signing, text cleanup, timestamp normalization, and
conversion from raw CLS telegraph JSON to the normalized item shape used by
market evidence and QA tools.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

try:
    from selectolax.parser import HTMLParser
except Exception:  # pragma: no cover - dependency is declared in requirements.
    HTMLParser = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

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


def sign_params(params: Mapping[str, Any]) -> str:
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
    if HTMLParser is not None and ("<" in text and ">" in text):
        try:
            text = HTMLParser(text).text(separator=" ")
        except Exception:
            text = re.sub(r"<[^>]+>", " ", text)
    else:
        text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\\s+", " ", text).strip()


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
    return dt.astimezone(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _detail_url(item_id: Any) -> str | None:
    if item_id is None or str(item_id).strip() == "":
        return None
    return f"{BASE_URL}/detail/{item_id}"


def _extract_symbols(item: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for stock in item.get("stock_list") or []:
        if not isinstance(stock, Mapping):
            continue
        for key in ("name", "StockID"):
            value = clean_html_text(stock.get(key))
            if value and value not in out:
                out.append(value)
    for subject in item.get("subjects") or []:
        if not isinstance(subject, Mapping):
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
    item: Mapping[str, Any],
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
        "raw": dict(item),
    }
```

- [ ] **Step 4: Add normalization tests**

Append to `backend/tests/test_cls_telegraph_client.py`:

```python
def test_normalize_telegraph_item_maps_symbols_and_metrics():
    from backend.services.cls_telegraph_client import normalize_telegraph_item

    item = {
        "id": 2420082,
        "title": "",
        "brief": "【午评】财联社7月8日电，市场回升。",
        "content": "财联社7月8日电，市场回升。",
        "ctime": 1783481506,
        "level": "B",
        "reading_num": 49031,
        "comment_num": 47,
        "share_num": 243,
        "images": ["https://image.cls.cn/a.jpg"],
        "audio_url": ["https://image.cls.cn/a.mp3"],
        "stock_list": [{"name": "科创50", "StockID": "sh000688"}],
        "subjects": [{"subject_name": "盘面直播"}],
    }

    row = normalize_telegraph_item(item, category="watch")

    assert row is not None
    assert row["title"] == "【午评】财联社7月8日电，市场回升。"
    assert row["summary"] == "【午评】财联社7月8日电，市场回升。"
    assert row["published_at"] == "2026-07-08 11:31:46"
    assert row["source"] == "财联社"
    assert row["source_url"] == "https://www.cls.cn/detail/2420082"
    assert row["symbols"] == ["科创50", "sh000688", "盘面直播"]
    assert row["metrics"]["cls_category"] == "watch"
    assert row["metrics"]["level"] == "B"
    assert row["metrics"]["images"] == ["https://image.cls.cn/a.jpg"]
```

- [ ] **Step 5: Run helper tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_cls_telegraph_client.py -q
```

Expected: PASS for helper tests.

- [ ] **Step 6: Commit Task 1**

```bash
git add backend/services/cls_telegraph_client.py backend/tests/test_cls_telegraph_client.py
git commit -m "feat(cls): add telegraph signing and normalization"
```

---

### Task 2: CLS HTTP List And Search Client

**Files:**
- Modify: `backend/services/cls_telegraph_client.py`
- Modify: `backend/tests/test_cls_telegraph_client.py`

**Interfaces:**
- Consumes:
  - `sign_params(params: Mapping[str, Any]) -> str`
  - `normalize_telegraph_item(item: Mapping[str, Any], category: str | None = None, ...) -> dict | None`
- Produces:
  - `fetch_roll_list(*, client: Any, category: str = "", limit: int = 10, last_time: int | None = None, timeout_seconds: float = 5.0, app_version: str = DEFAULT_APP_VERSION) -> list[dict]`
  - `search_telegraph(*, client: Any, keyword: str, category: str = "", limit: int = 10, timeout_seconds: float = 5.0, app_version: str = DEFAULT_APP_VERSION) -> list[dict]`

- [ ] **Step 1: Write failing HTTP client tests**

Append to `backend/tests/test_cls_telegraph_client.py`:

```python
class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response


def test_fetch_roll_list_signs_and_normalizes_rows():
    from backend.services.cls_telegraph_client import fetch_roll_list

    client = _Client(_Response({
        "errno": 0,
        "data": {
            "roll_data": [{
                "id": 1,
                "title": "基金快讯",
                "brief": "内容",
                "ctime": 1783481506,
                "subjects": [],
                "stock_list": [],
            }]
        },
    }))

    rows = fetch_roll_list(client=client, category="fund", limit=5, last_time=1783482113)

    assert len(rows) == 1
    assert rows[0]["title"] == "基金快讯"
    method, url, kwargs = client.calls[0]
    assert method == "GET"
    assert url == "https://www.cls.cn/v1/roll/get_roll_list"
    params = kwargs["params"]
    assert params["app"] == "CailianpressWeb"
    assert params["os"] == "web"
    assert params["sv"] == "8.7.9"
    assert params["category"] == "fund"
    assert params["rn"] == 5
    assert params["last_time"] == 1783482113
    assert "sign" in params
    assert kwargs["headers"]["Referer"] == "https://www.cls.cn/telegraph"


def test_fetch_roll_list_returns_empty_on_bad_response():
    from backend.services.cls_telegraph_client import fetch_roll_list

    client = _Client(_Response({"errno": "10012", "msg": "签名错误"}))

    assert fetch_roll_list(client=client, category="fund", limit=5) == []


def test_search_telegraph_posts_body_and_normalizes_rows():
    from backend.services.cls_telegraph_client import search_telegraph

    client = _Client(_Response({
        "list": [{
            "id": 2,
            "title": "南方基金 ETF",
            "content": "基金内容",
            "ctime": 1783481989,
        }],
        "total": 1,
    }))

    rows = search_telegraph(client=client, keyword="基金", category="fund", limit=10)

    assert rows[0]["title"] == "南方基金 ETF"
    method, url, kwargs = client.calls[0]
    assert method == "POST"
    assert url == "https://www.cls.cn/api/csw"
    assert kwargs["json"]["keyword"] == "基金"
    assert kwargs["json"]["category"] == "fund"
    assert kwargs["params"]["sign"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_cls_telegraph_client.py -q
```

Expected: FAIL with `ImportError` for `fetch_roll_list` or `search_telegraph`.

- [ ] **Step 3: Implement HTTP functions**

Append these functions to `backend/services/cls_telegraph_client.py`:

```python
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
```

- [ ] **Step 4: Run client tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_cls_telegraph_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/services/cls_telegraph_client.py backend/tests/test_cls_telegraph_client.py
git commit -m "feat(cls): add telegraph HTTP client"
```

---

### Task 3: CLS Adapter, Settings, And Default Source Wiring

**Files:**
- Create: `backend/services/market_sources/cls_telegraph.py`
- Modify: `backend/services/market_sources/__init__.py`
- Modify: `backend/config/settings.py`
- Modify: `backend/tests/test_market_source_adapters.py`
- Modify: `backend/tests/test_settings.py`
- Add: `backend/tests/test_market_sources_cls_config.py`

**Interfaces:**
- Consumes:
  - `fetch_roll_list(*, client, category, limit, last_time, timeout_seconds, app_version) -> list[dict]`
- Produces:
  - `ClsTelegraphAdapter.fetch(*, client=None, trade_date: str, brief_type: str = "post_market") -> list[dict]`
  - Settings fields: `cls_enabled`, `cls_search_enabled`, `cls_timeout_seconds`, `cls_categories`, `cls_per_category_limit`, `cls_max_search_limit`, `cls_app_version`

- [ ] **Step 1: Write failing adapter tests**

Append to `backend/tests/test_market_source_adapters.py`:

```python
def test_cls_telegraph_adapter_maps_client_rows_to_news_evidence(monkeypatch):
    from backend.services.market_sources.cls_telegraph import ClsTelegraphAdapter
    from backend.services import cls_telegraph_client as client_mod

    def fake_fetch_roll_list(**kwargs):
        assert kwargs["category"] == "fund"
        assert kwargs["limit"] == 2
        return [{
            "title": "基金快讯",
            "summary": "基金摘要",
            "published_at": "2026-07-08 11:31:46",
            "source": "财联社",
            "source_url": "https://www.cls.cn/detail/1",
            "symbols": ["基金"],
            "metrics": {"cls_id": 1, "cls_category": "fund"},
        }]

    monkeypatch.setattr(client_mod, "fetch_roll_list", fake_fetch_roll_list)
    adapter = ClsTelegraphAdapter(categories=["fund"], per_category_limit=2)

    rows = adapter.fetch(client=object(), trade_date="2026-07-08", brief_type="post_market")

    assert rows == [{
        "trade_date": "2026-07-08",
        "brief_type": "post_market",
        "category": "news",
        "title": "基金快讯",
        "summary": "基金摘要",
        "symbols": ["基金"],
        "metrics": {"cls_id": 1, "cls_category": "fund"},
        "source": "财联社",
        "source_url": "https://www.cls.cn/detail/1",
        "published_at": "2026-07-08 11:31:46",
        "reliability": "wire",
    }]


def test_cls_telegraph_adapter_isolates_category_failure(monkeypatch):
    from backend.services.market_sources.cls_telegraph import ClsTelegraphAdapter
    from backend.services import cls_telegraph_client as client_mod

    def fake_fetch_roll_list(**kwargs):
        if kwargs["category"] == "fund":
            raise RuntimeError("boom")
        return [{
            "title": "看盘快讯",
            "summary": "摘要",
            "published_at": "2026-07-08 11:31:46",
            "source": "财联社",
            "source_url": "https://www.cls.cn/detail/2",
            "symbols": [],
            "metrics": {"cls_id": 2, "cls_category": "watch"},
        }]

    monkeypatch.setattr(client_mod, "fetch_roll_list", fake_fetch_roll_list)
    adapter = ClsTelegraphAdapter(categories=["fund", "watch"], per_category_limit=2)

    rows = adapter.fetch(client=object(), trade_date="2026-07-08")

    assert len(rows) == 1
    assert rows[0]["title"] == "看盘快讯"
```

- [ ] **Step 2: Write failing settings and adapter-builder tests**

Append to `backend/tests/test_settings.py`:

```python
def test_cls_settings_defaults(monkeypatch):
    for key in [
        "CLS_ENABLED",
        "CLS_SEARCH_ENABLED",
        "CLS_TIMEOUT_SECONDS",
        "CLS_CATEGORIES",
        "CLS_PER_CATEGORY_LIMIT",
        "CLS_MAX_SEARCH_LIMIT",
        "CLS_APP_VERSION",
    ]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.cls_enabled is True
    assert s.cls_search_enabled is True
    assert s.cls_timeout_seconds == 5.0
    assert s.cls_categories == "fund,watch,announcement,hk_us,red,remind"
    assert s.cls_per_category_limit == 10
    assert s.cls_max_search_limit == 10
    assert s.cls_app_version == "8.7.9"


def test_cls_settings_read_env(monkeypatch):
    monkeypatch.setenv("CLS_ENABLED", "false")
    monkeypatch.setenv("CLS_SEARCH_ENABLED", "false")
    monkeypatch.setenv("CLS_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("CLS_CATEGORIES", "fund,watch")
    monkeypatch.setenv("CLS_PER_CATEGORY_LIMIT", "2")
    monkeypatch.setenv("CLS_MAX_SEARCH_LIMIT", "4")
    monkeypatch.setenv("CLS_APP_VERSION", "9.0.0")
    get_settings.cache_clear()
    s = get_settings()
    assert s.cls_enabled is False
    assert s.cls_search_enabled is False
    assert s.cls_timeout_seconds == 3.5
    assert s.cls_categories == "fund,watch"
    assert s.cls_per_category_limit == 2
    assert s.cls_max_search_limit == 4
    assert s.cls_app_version == "9.0.0"
```

Create `backend/tests/test_market_sources_cls_config.py`:

```python
from __future__ import annotations


def test_build_default_adapters_includes_cls_only_for_post_market(monkeypatch):
    from backend.config.settings import get_settings
    from backend.services.market_sources import ClsTelegraphAdapter, build_default_adapters

    monkeypatch.setenv("CLS_ENABLED", "true")
    monkeypatch.setenv("CLS_CATEGORIES", "fund,watch")
    monkeypatch.setenv("CLS_PER_CATEGORY_LIMIT", "3")
    get_settings.cache_clear()

    pre = build_default_adapters(client=object(), brief_type="pre_market")
    post = build_default_adapters(client=object(), brief_type="post_market")

    assert not any(isinstance(adapter, ClsTelegraphAdapter) for adapter in pre)
    cls_adapters = [adapter for adapter in post if isinstance(adapter, ClsTelegraphAdapter)]
    assert len(cls_adapters) == 1
    assert cls_adapters[0].categories == ["fund", "watch"]
    assert cls_adapters[0].per_category_limit == 3


def test_build_default_adapters_excludes_cls_when_disabled(monkeypatch):
    from backend.config.settings import get_settings
    from backend.services.market_sources import ClsTelegraphAdapter, build_default_adapters

    monkeypatch.setenv("CLS_ENABLED", "false")
    get_settings.cache_clear()

    adapters = build_default_adapters(client=object(), brief_type="post_market")

    assert not any(isinstance(adapter, ClsTelegraphAdapter) for adapter in adapters)
```

- [ ] **Step 3: Run tests and verify failures**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_market_source_adapters.py \
  backend/tests/test_settings.py \
  backend/tests/test_market_sources_cls_config.py \
  -q
```

Expected: FAIL for missing `ClsTelegraphAdapter` and missing settings fields.

- [ ] **Step 4: Implement settings fields**

In `backend/config/settings.py`, add these fields under the briefing fields:

```python
    # 财联社电报信息源。v1 只用于 post_market evidence + 实时搜索 tool。
    cls_enabled: bool = True
    cls_search_enabled: bool = True
    cls_timeout_seconds: float = 5.0
    cls_categories: str = "fund,watch,announcement,hk_us,red,remind"
    cls_per_category_limit: int = 10
    cls_max_search_limit: int = 10
    cls_app_version: str = "8.7.9"
```

- [ ] **Step 5: Implement `ClsTelegraphAdapter`**

Create `backend/services/market_sources/cls_telegraph.py`:

```python
"""ClsTelegraphAdapter: 财联社电报 -> market_evidence news rows."""
from __future__ import annotations

from typing import Any

import httpx

from backend.services import cls_telegraph_client as cls_client


def _parse_categories(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return ["fund", "watch", "announcement", "hk_us", "red", "remind"]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


class ClsTelegraphAdapter:
    source = "财联社"
    reliability = "wire"
    category = "news"

    def __init__(
        self,
        *,
        client: Any | None = None,
        categories: str | list[str] | tuple[str, ...] | None = None,
        per_category_limit: int = 10,
        timeout_seconds: float = 5.0,
        app_version: str = cls_client.DEFAULT_APP_VERSION,
    ):
        self.client = client
        self.categories = _parse_categories(categories)
        self.per_category_limit = max(1, int(per_category_limit))
        self.timeout_seconds = float(timeout_seconds)
        self.app_version = app_version

    def _to_evidence(self, row: dict, *, trade_date: str, brief_type: str) -> dict | None:
        if not (row.get("source_url") and row.get("title")):
            return None
        return {
            "trade_date": trade_date,
            "brief_type": brief_type,
            "category": self.category,
            "title": row["title"],
            "summary": row.get("summary") or "",
            "symbols": row.get("symbols") or [],
            "metrics": row.get("metrics") or {},
            "source": self.source,
            "source_url": row["source_url"],
            "published_at": row.get("published_at"),
            "reliability": self.reliability,
        }

    def fetch(self, *, client=None, trade_date: str, brief_type: str = "post_market") -> list[dict]:
        """Fetch configured CLS categories and return market evidence rows.

        This method never raises. It isolates category failures and skips
        malformed rows.
        """
        active_client = client or self.client
        owns_client = active_client is None
        if active_client is None:
            active_client = httpx.Client(follow_redirects=True, timeout=self.timeout_seconds)
        out: list[dict] = []
        try:
            for category in self.categories:
                try:
                    rows = cls_client.fetch_roll_list(
                        client=active_client,
                        category=category,
                        limit=self.per_category_limit,
                        timeout_seconds=self.timeout_seconds,
                        app_version=self.app_version,
                    )
                except Exception:
                    continue
                for row in rows:
                    evidence = self._to_evidence(row, trade_date=trade_date, brief_type=brief_type)
                    if evidence is not None:
                        out.append(evidence)
            return out
        except Exception:
            return []
        finally:
            if owns_client:
                try:
                    active_client.close()
                except Exception:
                    pass
```

- [ ] **Step 6: Wire adapter into `market_sources.__init__`**

Modify `backend/services/market_sources/__init__.py`:

```python
from backend.services.market_sources.cls_telegraph import ClsTelegraphAdapter
```

Add this inside the `post_market` branch of `build_default_adapters`, after `SectorHeatAdapter` logic:

```python
        try:
            from backend.config.settings import get_settings
            settings = get_settings()
            if bool(getattr(settings, "cls_enabled", True)):
                adapters.append(ClsTelegraphAdapter(
                    client=client,
                    categories=getattr(settings, "cls_categories", "fund,watch,announcement,hk_us,red,remind"),
                    per_category_limit=int(getattr(settings, "cls_per_category_limit", 10)),
                    timeout_seconds=float(getattr(settings, "cls_timeout_seconds", 5.0)),
                    app_version=getattr(settings, "cls_app_version", "8.7.9"),
                ))
        except Exception:
            pass
```

Add `ClsTelegraphAdapter` to `__all__`.

- [ ] **Step 7: Run adapter/config tests**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_market_source_adapters.py \
  backend/tests/test_settings.py \
  backend/tests/test_market_sources_cls_config.py \
  -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add \
  backend/config/settings.py \
  backend/services/market_sources/__init__.py \
  backend/services/market_sources/cls_telegraph.py \
  backend/tests/test_market_source_adapters.py \
  backend/tests/test_settings.py \
  backend/tests/test_market_sources_cls_config.py
git commit -m "feat(cls): add telegraph evidence adapter"
```

---

### Task 4: Real-Time CLS Search Tool And QA Prompt Guidance

**Files:**
- Modify: `backend/tools/market_tools.py`
- Modify: `backend/graph/prompts.py`
- Modify: `backend/tests/test_tools.py`
- Add: `backend/tests/test_graph_prompts_cls.py`

**Interfaces:**
- Consumes:
  - `cls_telegraph_client.search_telegraph(*, client, keyword, category, limit, timeout_seconds, app_version) -> list[dict]`
  - `Settings.cls_search_enabled`
- Produces:
  - LangChain tool `search_cls_telegraph(keyword: str = "", category: str = "", limit: int = 10) -> dict`

- [ ] **Step 1: Write failing tool tests**

Append to `backend/tests/test_tools.py`:

```python
from backend.services import cls_telegraph_client as cls_client
from backend.config.settings import get_settings


def test_search_cls_telegraph_tool_forwards_to_client(monkeypatch):
    monkeypatch.setenv("CLS_SEARCH_ENABLED", "true")
    monkeypatch.setenv("CLS_MAX_SEARCH_LIMIT", "3")
    get_settings.cache_clear()

    def fake_search_telegraph(**kwargs):
        assert kwargs["keyword"] == "基金"
        assert kwargs["category"] == "fund"
        assert kwargs["limit"] == 3
        return [{
            "title": "基金快讯",
            "summary": "摘要",
            "published_at": "2026-07-08 11:31:46",
            "source": "财联社",
            "source_url": "https://www.cls.cn/detail/1",
            "symbols": ["基金"],
            "metrics": {"cls_id": 1},
        }]

    monkeypatch.setattr(cls_client, "search_telegraph", fake_search_telegraph)

    out = mt.search_cls_telegraph.invoke({"keyword": "基金", "category": "fund", "limit": 99})

    assert out["count"] == 1
    assert out["items"][0]["title"] == "基金快讯"
    assert out["error"] == ""


def test_search_cls_telegraph_tool_respects_disable(monkeypatch):
    monkeypatch.setenv("CLS_SEARCH_ENABLED", "false")
    get_settings.cache_clear()

    out = mt.search_cls_telegraph.invoke({"keyword": "基金"})

    assert out["count"] == 0
    assert out["items"] == []
    assert out["error"] == "CLS search disabled"
```

Update existing expectations in `backend/tests/test_tools.py`:

```python
    assert {t.name for t in mt.MARKET_TOOLS} == {
        "get_market_indices", "refresh_market",
        "get_market_snapshot_auto", "search_market_evidence",
        "search_cls_telegraph",
        "get_market_briefing",
    }
```

In `test_all_tools_aggregate_has_unique_set`, update the comment and set to include `search_cls_telegraph`.

- [ ] **Step 2: Write failing prompt test**

Create `backend/tests/test_graph_prompts_cls.py`:

```python
from __future__ import annotations


def test_system_prompt_mentions_news_category_and_cls_search():
    from backend.graph.prompts import get_system_prompt

    prompt = get_system_prompt()

    assert 'category="news"' in prompt
    assert "search_cls_telegraph" in prompt
    assert "财联社" in prompt
    assert "事实整理" in prompt
```

- [ ] **Step 3: Run tests and verify failures**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_tools.py backend/tests/test_graph_prompts_cls.py -q
```

Expected: FAIL because `search_cls_telegraph` is not defined and prompt lacks CLS guidance.

- [ ] **Step 4: Implement `search_cls_telegraph` tool**

Modify `backend/tools/market_tools.py`:

```python
import httpx
```

Add:

```python
from backend.config.settings import get_settings
from backend.services import cls_telegraph_client
```

Update `search_market_evidence` docstring category line to:

```python
        category: policy / announcement / overseas_disclosure / macro / sector / news。空=不限
```

Add this tool before `get_market_briefing`:

```python
@tool
def search_cls_telegraph(
    keyword: str = "",
    category: str = "",
    limit: int = 10,
) -> dict:
    """实时搜索财联社电报。

    Args:
        keyword: 搜索关键词。空字符串直接返回空结果。
        category: 财联社分类: fund / watch / announcement / hk_us / red / remind。空=不限
        limit: 最多返回条数,受 CLS_MAX_SEARCH_LIMIT 限制。

    Returns:
        {count, items, error}。每条 item 含 title / summary / published_at /
        source / source_url / symbols / metrics。回答时必须附 source_url。
    """
    settings = get_settings()
    if not bool(getattr(settings, "cls_search_enabled", True)):
        return {"count": 0, "items": [], "error": "CLS search disabled"}
    kw = (keyword or "").strip()
    if not kw:
        return {"count": 0, "items": [], "error": ""}
    max_limit = int(getattr(settings, "cls_max_search_limit", 10))
    effective_limit = max(1, min(int(limit or max_limit), max_limit))
    try:
        with httpx.Client(follow_redirects=True, timeout=float(settings.cls_timeout_seconds)) as client:
            rows = cls_telegraph_client.search_telegraph(
                client=client,
                keyword=kw,
                category=(category or "").strip(),
                limit=effective_limit,
                timeout_seconds=float(settings.cls_timeout_seconds),
                app_version=settings.cls_app_version,
            )
        return {"count": len(rows), "items": rows, "error": ""}
    except Exception as exc:  # noqa: BLE001
        return {"count": 0, "items": [], "error": str(exc)}
```

Add `search_cls_telegraph` to `MARKET_TOOLS` after `search_market_evidence`.

- [ ] **Step 5: Update prompt guidance**

Modify `backend/graph/prompts.py` inside tool-use rule 8:

```python
   - 涉及新闻、快讯、财联社、市场消息、基金资讯时,优先调 `search_market_evidence` 且可用 category="news";
   - 用户明确要求"最新/实时/财联社"时,调用 `search_cls_telegraph`;
   - 财联社结果只做事实整理和来源引用,不要把快讯扩写成交易建议。
```

Keep the existing requirements about `source` + `source_url` + `published_at`.

- [ ] **Step 6: Run tool and prompt tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_tools.py backend/tests/test_graph_prompts_cls.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add backend/tools/market_tools.py backend/graph/prompts.py backend/tests/test_tools.py backend/tests/test_graph_prompts_cls.py
git commit -m "feat(cls): expose telegraph search tool"
```

---

### Task 5: Environment Templates And Evidence Integration Tests

**Files:**
- Modify: `backend/.env.example`
- Modify: `.env.example`
- Modify: `backend/tests/test_market_evidence_ingestion.py`

**Interfaces:**
- Consumes:
  - `market_evidence_ingestion.ingest_market_evidence(...)`
  - `MarketEvidence.category` accepts arbitrary strings.
- Produces:
  - Documented env vars in both env templates.
  - Regression test proving `category="news"` upserts and dedupes.

- [ ] **Step 1: Write failing news ingestion test**

Append to `backend/tests/test_market_evidence_ingestion.py`:

```python
def test_ingest_market_evidence_accepts_cls_news_category(session):
    from backend.services import market_evidence_ingestion as ing

    row = {
        "trade_date": "2026-07-08",
        "brief_type": "post_market",
        "category": "news",
        "title": "基金快讯",
        "summary": "财联社摘要",
        "symbols": ["基金"],
        "metrics": {"cls_id": 1, "cls_category": "fund"},
        "source": "财联社",
        "source_url": "https://www.cls.cn/detail/1",
        "published_at": "2026-07-08 11:31:46",
        "reliability": "wire",
    }

    result = ing.ingest_market_evidence(
        trade_date="2026-07-08",
        brief_type="post_market",
        adapters=[_Adapter([row]), _Adapter([row])],
        session=session,
    )

    assert result["inserted"] == 1
    assert result["fetched"] == 2
    assert result["categories"] == {"news": 1}
```

- [ ] **Step 2: Run ingestion test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_market_evidence_ingestion.py::test_ingest_market_evidence_accepts_cls_news_category -q
```

Expected: PASS if Task 3 kept existing ingestion behavior. If it fails, inspect the failure and keep the repository schema unchanged unless the failure proves a real bug.

- [ ] **Step 3: Update `backend/.env.example`**

Append:

```dotenv

# ---- 财联社电报信息源 ----
CLS_ENABLED=true
CLS_SEARCH_ENABLED=true
CLS_TIMEOUT_SECONDS=5
CLS_CATEGORIES=fund,watch,announcement,hk_us,red,remind
CLS_PER_CATEGORY_LIMIT=10
CLS_MAX_SEARCH_LIMIT=10
CLS_APP_VERSION=8.7.9
```

- [ ] **Step 4: Update root `.env.example`**

Append after scheduler settings:

```dotenv

# ---- 财联社电报信息源 (后端) ----
# 用于 post_market evidence 自动采集和 QA 实时搜索。不保存完整长文。
CLS_ENABLED=true
CLS_SEARCH_ENABLED=true
CLS_TIMEOUT_SECONDS=5
CLS_CATEGORIES=fund,watch,announcement,hk_us,red,remind
CLS_PER_CATEGORY_LIMIT=10
CLS_MAX_SEARCH_LIMIT=10
CLS_APP_VERSION=8.7.9
```

- [ ] **Step 5: Verify env docs contain all keys**

Run:

```bash
rg -n "CLS_ENABLED|CLS_SEARCH_ENABLED|CLS_TIMEOUT_SECONDS|CLS_CATEGORIES|CLS_PER_CATEGORY_LIMIT|CLS_MAX_SEARCH_LIMIT|CLS_APP_VERSION" backend/.env.example .env.example
```

Expected: both files contain all seven keys.

- [ ] **Step 6: Run integration-adjacent tests**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_market_evidence_ingestion.py \
  backend/tests/test_settings.py \
  backend/tests/test_market_sources_cls_config.py \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add backend/.env.example .env.example backend/tests/test_market_evidence_ingestion.py
git commit -m "docs(cls): document telegraph environment settings"
```

---

### Task 6: Full Verification And Acceptance Checks

**Files:**
- No new files expected.
- Modify only files with failing tests caused by the CLS implementation.

**Interfaces:**
- Consumes all interfaces from Tasks 1-5.
- Produces a verified backend-only CLS integration.

- [ ] **Step 1: Run targeted CLS and evidence tests**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_cls_telegraph_client.py \
  backend/tests/test_market_source_adapters.py \
  backend/tests/test_market_sources_cls_config.py \
  backend/tests/test_market_evidence_ingestion.py \
  backend/tests/test_tools.py \
  backend/tests/test_graph_prompts_cls.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run broader backend tests that touch market evidence and graph prompts**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_market_evidence_service.py \
  backend/tests/test_market_evidence_ingestion.py \
  backend/tests/test_market_source_adapters.py \
  backend/tests/test_tools.py \
  backend/tests/test_graph_prompts.py \
  backend/tests/test_qa_graph.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Run static diff checks**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Optional manual network smoke for CLS list**

Only run this when network access is available and the user wants a live smoke check:

```bash
.venv/bin/python - <<'PY'
import httpx
from backend.services.cls_telegraph_client import fetch_roll_list

with httpx.Client(follow_redirects=True, timeout=5.0) as client:
    rows = fetch_roll_list(client=client, category="fund", limit=3)
print({"count": len(rows), "titles": [r["title"] for r in rows]})
PY
```

Expected: prints a dict with `count` between 0 and 3. `count=0` is acceptable if CLS blocks the request; code should not raise.

- [ ] **Step 5: Optional manual network smoke for CLS search**

Only run this when network access is available and the user wants a live smoke check:

```bash
.venv/bin/python - <<'PY'
import httpx
from backend.services.cls_telegraph_client import search_telegraph

with httpx.Client(follow_redirects=True, timeout=5.0) as client:
    rows = search_telegraph(client=client, keyword="基金", category="", limit=3)
print({"count": len(rows), "titles": [r["title"] for r in rows]})
PY
```

Expected: prints a dict with `count` between 0 and 3. `count=0` is acceptable if CLS blocks the request; code should not raise.

- [ ] **Step 6: Confirm acceptance criteria**

Run a short Python check against the adapter without requiring external network:

```bash
.venv/bin/python - <<'PY'
from backend.config.settings import get_settings
from backend.services.market_sources import build_default_adapters, ClsTelegraphAdapter

get_settings.cache_clear()
post = build_default_adapters(client=object(), brief_type="post_market")
print(any(isinstance(adapter, ClsTelegraphAdapter) for adapter in post))
PY
```

Expected: prints `True` unless the local environment explicitly sets `CLS_ENABLED=false`.

- [ ] **Step 7: Commit final verification fixes**

If Step 1-6 required code changes:

```bash
git add backend
git commit -m "test(cls): verify telegraph source integration"
```

If Step 1-6 required no code changes:

```bash
git status --short
```

Expected: no unstaged changes except intentionally uncommitted manual smoke output files, which should not be added.

---

## Self-Review

Spec coverage:

- Automatic evidence ingestion is covered by Tasks 3 and 5.
- Real-time QA search is covered by Task 4.
- CLS signing, request headers, fixed params, pagination, and search endpoints are covered by Tasks 1 and 2.
- `category="news"` mapping and original CLS category in metrics are covered by Tasks 1, 3, and 5.
- Failure isolation is covered by Tasks 2, 3, and 4.
- Config and `.env.example` sync are covered by Tasks 3 and 5.
- Prompt updates and non-recommendation framing are covered by Task 4.
- No frontend, no new table, no bulk detail fetch, and no historical backfill are maintained by the file structure and task list.

Placeholder scan:

- No step uses unresolved placeholder language or unspecified generic handling instructions.
- Every task has concrete files, interfaces, test snippets, commands, and expected outcomes.

Type consistency:

- Module name is consistently `cls_telegraph_client`.
- Adapter class is consistently `ClsTelegraphAdapter`.
- Tool name is consistently `search_cls_telegraph`.
- Evidence category is consistently `news`.
