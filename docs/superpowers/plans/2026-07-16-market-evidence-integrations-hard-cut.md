# Market Evidence Integrations Hard Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all five market-evidence adapters into provider-focused `backend.integrations` packages, inject the two service-owned fetch callables at the composition root, fix the broken CNInfo wiring, and delete the legacy `backend.services.market_sources` path.

**Architecture:** `backend.integrations.market_evidence` builds the default adapter list, while provider subpackages own evidence normalization for CLS, CNInfo, FRED, policy pages, and sector heat. `backend.services.market.market_evidence_service` remains the composition root and injects the existing CLS client and AKShare announcement collector, preserving the dependency direction `services → integrations`. The migration is delivered as one atomic implementation commit with no compatibility facade or duplicate adapter implementation left behind.

**Tech Stack:** Python 3.11, httpx, AKShare-backed existing collector, pytest, AST contract tests, PostgreSQL 16 + pgvector test fixtures.

## Global Constraints

- Move only the five market-evidence adapters; do not move or refactor `backend/services/market/data_collector.py` or `backend/services/knowledge/cls_telegraph_client.py`.
- Do not change external URLs, HTTP timeouts, retries, default policy sources, default FRED series, or Settings fields.
- Preserve adapter ordering, evidence fields, filtering, limits, error isolation, CLS `last_errors`, ingestion behavior, transaction ownership, and business singleflight semantics.
- The only intentional behavior change is fixing CNInfo so its injected announcement collector can produce evidence instead of always returning `[]` after a swallowed `NameError`.
- `build_default_adapters` requires explicit `fetch_cls_roll_list` and `fetch_announcements` keyword arguments; it must never import service defaults.
- `ClsTelegraphAdapter` requires explicit `fetch_roll_list` and `app_version` constructor arguments; it must not copy or import the CLS client's default app-version constant.
- `backend/integrations/**/*.py` must not import `backend.services`.
- Leave `backend/integrations/protocols.py`, `backend/integrations/registry.py`, and `backend/integrations/__init__.py` unchanged; registration and protocol alignment are outside this hard cut.
- Delete `backend/services/market_sources/`; do not retain re-exports, deprecation shims, or dual implementations.
- PostgreSQL is the only database for the complete backend regression. `TEST_DATABASE_URL` must point to a disposable database whose name ends in `_test`.
- Because this is a hard cut, Tasks 1–4 are testable checkpoints but are not committed separately. Create one atomic implementation commit only after Task 5 passes.

---

## File Map

### New provider boundary

- `backend/integrations/_html.py`: private absolute-URL, title, and link-filter helpers moved from the legacy `_utils.py`.
- `backend/integrations/market_evidence.py`: default policy/FRED constants and `build_default_adapters` factory.
- `backend/integrations/cls/adapter.py`: CLS row-to-evidence adapter using an injected roll-list callable.
- `backend/integrations/cninfo/adapter.py`: announcement row-to-evidence adapter using an injected collector callable.
- `backend/integrations/fred/adapter.py`: FRED JSON/CSV parsing and evidence mapping.
- `backend/integrations/policy/adapter.py`: policy-page HTML parsing and evidence mapping.
- `backend/integrations/sector/adapter.py`: sector-snapshot evidence mapping.
- Each provider's `__init__.py`: exports only its adapter class.

### Composition and consumers

- `backend/services/market/market_evidence_service.py`: imports the new factory and injects the two service-owned callables.
- `backend/tests/test_market_source_adapters.py`: imports provider packages directly and characterizes all five adapters.
- `backend/tests/test_market_sources_cls_config.py`: imports the new factory, supplies fake callables, and verifies configuration/order.
- `backend/tests/test_market_evidence_service.py`: verifies composition-root injection and client cleanup.
- `backend/tests/test_briefing_service.py`: removes the legacy import and patches the new runtime lookup point.
- `backend/tests/test_market_integration_contract.py`: hard-cut path, import, and dependency-direction guard.

### Deleted legacy boundary

- Delete every file below `backend/services/market_sources/` after all consumers use the new paths.

---

### Task 1: Add RED hard-cut and behavior contracts

**Files:**
- Create: `backend/tests/test_market_integration_contract.py`
- Modify: `backend/tests/test_market_source_adapters.py`
- Modify: `backend/tests/test_market_sources_cls_config.py`

**Interfaces:**
- Consumes: the approved package paths and constructor/factory signatures.
- Produces: failing tests that define the hard-cut boundary, CNInfo correction, provider behavior, factory dependencies, and adapter order.

- [ ] **Step 1: Add the hard-cut AST/path contract**

Create `backend/tests/test_market_integration_contract.py` with these checks:

```python
"""Market evidence integrations hard-cut contracts."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

PROVIDER_MODULES = ("cls", "cninfo", "fred", "policy", "sector")


def _python_sources(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_legacy_market_sources_package_is_removed() -> None:
    assert not Path("backend/services/market_sources").exists()


@pytest.mark.parametrize("path", _python_sources(Path("backend")), ids=str)
def test_python_sources_do_not_import_legacy_market_sources(path: Path) -> None:
    assert all(
        not module.startswith("backend.services.market_sources")
        for module in _imported_modules(path)
    ), path


@pytest.mark.parametrize(
    "path",
    _python_sources(Path("backend/integrations")),
    ids=str,
)
def test_integrations_do_not_import_services(path: Path) -> None:
    assert all(
        not module.startswith("backend.services")
        for module in _imported_modules(path)
    ), path


@pytest.mark.parametrize("provider", PROVIDER_MODULES)
def test_provider_package_imports(provider: str) -> None:
    __import__(f"backend.integrations.{provider}")


def test_market_evidence_factory_imports() -> None:
    __import__("backend.integrations.market_evidence")
```

- [ ] **Step 2: Convert existing adapter tests to the approved imports and injection API**

Use these imports in `backend/tests/test_market_source_adapters.py`:

```python
from backend.integrations.cls import ClsTelegraphAdapter
from backend.integrations.cninfo import CninfoAnnouncementAdapter
from backend.integrations.fred import FredSeriesAdapter
from backend.integrations.policy import PolicyPageAdapter
from backend.integrations.sector import SectorHeatAdapter
```

Replace CLS module monkeypatching with constructor injection. Every CLS construction must provide both required arguments:

```python
adapter = ClsTelegraphAdapter(
    fetch_roll_list=fake_fetch_roll_list,
    app_version="test",
    categories=["fund"],
    per_category_limit=2,
)
```

Extend the category-failure test to assert diagnostics rather than only the surviving row:

```python
assert len(rows) == 1
assert rows[0]["title"] == "看盘快讯"
assert adapter.last_errors == [{
    "category": "fund",
    "error": "RuntimeError: boom",
}]
```

- [ ] **Step 3: Add CNInfo success, failure, and limit characterization tests**

Append tests using an injected callable:

```python
def test_cninfo_adapter_maps_injected_announcements_to_evidence():
    calls = []

    def fake_fetch_announcements(*, limit):
        calls.append(limit)
        return [{
            "title": "基金分红公告",
            "ann_date": "2026-07-15",
            "fund_code": "000001",
            "fund_name": "测试基金",
        }]

    adapter = CninfoAnnouncementAdapter(
        fetch_announcements=fake_fetch_announcements,
        limit=2,
    )

    rows = adapter.fetch(trade_date="2026-07-16", brief_type="post_market")

    assert calls == [2]
    assert rows == [{
        "trade_date": "2026-07-16",
        "brief_type": "post_market",
        "category": "announcement",
        "source": "akshare/eastmoney",
        "source_url": "https://fundf10.eastmoney.com/jjgg_000001_2026-07-15.html",
        "title": "基金分红公告",
        "summary": "测试基金 - 2026-07-15",
        "symbols": ["测试基金", "000001"],
        "metrics": None,
        "published_at": "2026-07-15",
        "reliability": "wire",
    }]


def test_cninfo_adapter_isolates_collector_failure():
    def failing_fetch_announcements(*, limit):
        raise RuntimeError(f"collector failed at {limit}")

    adapter = CninfoAnnouncementAdapter(
        fetch_announcements=failing_fetch_announcements,
    )

    assert adapter.fetch(trade_date="2026-07-16") == []


def test_cninfo_adapter_filters_missing_titles_and_enforces_limit():
    def fake_fetch_announcements(*, limit):
        assert limit == 1
        return [
            {"title": "", "fund_code": "skip"},
            {"title": "公告 A", "fund_code": "000001"},
            {"title": "公告 B", "fund_code": "000002"},
        ]

    adapter = CninfoAnnouncementAdapter(
        fetch_announcements=fake_fetch_announcements,
        limit=1,
    )

    rows = adapter.fetch(trade_date="2026-07-16")

    assert [row["title"] for row in rows] == ["公告 A"]
```

- [ ] **Step 4: Add a sector evidence shape test**

Append a regression that locks the strong/weak ordering and metrics:

```python
def test_sector_adapter_maps_top_and_bottom_rows():
    adapter = SectorHeatAdapter(
        sector_snapshot={"industry_sectors": [
            {"name": "弱板块", "change_pct": -2.0},
            {"name": "中板块", "change_pct": 0.5},
            {"name": "强板块", "change_pct": 3.0},
        ]},
        top_n=1,
    )

    rows = adapter.fetch(trade_date="2026-07-16")

    assert [row["title"] for row in rows] == [
        "行业板块 强势: 强板块 +3.00%",
        "行业板块 弱势: 弱板块 -2.00%",
    ]
    assert [row["metrics"] for row in rows] == [
        {"change_pct": 3.0},
        {"change_pct": -2.0},
    ]
```

- [ ] **Step 5: Rewrite factory tests around required fake dependencies**

In `backend/tests/test_market_sources_cls_config.py`, import:

```python
from backend.integrations.cls import ClsTelegraphAdapter
from backend.integrations.cninfo import CninfoAnnouncementAdapter
from backend.integrations.fred import FredSeriesAdapter
from backend.integrations.market_evidence import build_default_adapters
from backend.integrations.policy import PolicyPageAdapter
from backend.integrations.sector import SectorHeatAdapter
```

Use one helper in every successful factory call:

```python
def _factory_kwargs() -> dict:
    return {
        "client": object(),
        "fetch_cls_roll_list": lambda **_: [],
        "fetch_announcements": lambda **_: [],
    }
```

Keep the three existing CLS configuration assertions, but pass `**_factory_kwargs()` and patch `backend.integrations.market_evidence`. Add order and required-dependency tests:

```python
def test_build_default_adapters_preserves_type_order(monkeypatch):
    monkeypatch.setenv("CLS_ENABLED", "false")
    from backend.config.settings import get_settings
    get_settings.cache_clear()

    pre = build_default_adapters(brief_type="pre_market", **_factory_kwargs())
    post = build_default_adapters(
        brief_type="post_market",
        sector_snapshot={"industry_sectors": []},
        **_factory_kwargs(),
    )

    assert [type(adapter) for adapter in pre] == (
        [FredSeriesAdapter] * 3 + [PolicyPageAdapter] * 5
    )
    assert [type(adapter) for adapter in post] == (
        [PolicyPageAdapter] * 5
        + [CninfoAnnouncementAdapter]
        + [FredSeriesAdapter] * 3
        + [SectorHeatAdapter]
    )


def test_build_default_adapters_requires_both_fetch_callables():
    with pytest.raises(TypeError):
        build_default_adapters(client=object())
```

- [ ] **Step 6: Run the new and migrated tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q \
  backend/tests/test_market_integration_contract.py \
  backend/tests/test_market_source_adapters.py \
  backend/tests/test_market_sources_cls_config.py
```

Expected: FAIL because the provider packages do not exist and the legacy directory still exists. Do not weaken the assertions.

---

### Task 2: Create provider packages and the injected default factory

**Files:**
- Create: `backend/integrations/_html.py`
- Create: `backend/integrations/market_evidence.py`
- Create: `backend/integrations/cls/__init__.py`
- Create: `backend/integrations/cls/adapter.py`
- Create: `backend/integrations/cninfo/__init__.py`
- Create: `backend/integrations/cninfo/adapter.py`
- Create: `backend/integrations/fred/__init__.py`
- Create: `backend/integrations/fred/adapter.py`
- Create: `backend/integrations/policy/__init__.py`
- Create: `backend/integrations/policy/adapter.py`
- Create: `backend/integrations/sector/__init__.py`
- Create: `backend/integrations/sector/adapter.py`

**Interfaces:**
- Produces: `PolicyPageAdapter`, `FredSeriesAdapter`, `CninfoAnnouncementAdapter`, `SectorHeatAdapter`, `ClsTelegraphAdapter` from narrow provider packages.
- Produces: `build_default_adapters(*, client, fetch_cls_roll_list, fetch_announcements, brief_type="post_market", sector_snapshot=None) -> list`.

- [ ] **Step 1: Move the private HTML helpers without behavior changes**

Create `backend/integrations/_html.py` with the legacy helper behavior:

```python
"""Private HTML and URL helpers for market-evidence integrations."""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin


def absolute_url(base: str, href: str) -> str | None:
    if not href:
        return None
    if href.startswith(("http://", "https://")):
        return href
    return urljoin(base, href)


def is_plausible_title(
    text: str,
    *,
    min_len: int = 4,
    max_len: int = 80,
) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if not (min_len <= len(stripped) <= max_len):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", stripped))


def looks_like_news_link(href: str, keywords: Iterable[str]) -> bool:
    if not href:
        return False
    lower = href.lower()
    return any(keyword.lower() in lower for keyword in keywords)
```

Do not add exports to `backend/integrations/__init__.py`.

- [ ] **Step 2: Create the Policy, FRED, and Sector provider packages**

Move each legacy class body unchanged into its provider's `adapter.py`. The only internal import change is in policy:

```python
from backend.integrations._html import (
    absolute_url,
    is_plausible_title,
    looks_like_news_link,
)
```

Each `__init__.py` exposes only its class:

```python
# backend/integrations/policy/__init__.py
from backend.integrations.policy.adapter import PolicyPageAdapter

__all__ = ["PolicyPageAdapter"]

# backend/integrations/fred/__init__.py
from backend.integrations.fred.adapter import FredSeriesAdapter

__all__ = ["FredSeriesAdapter"]

# backend/integrations/sector/__init__.py
from backend.integrations.sector.adapter import SectorHeatAdapter

__all__ = ["SectorHeatAdapter"]
```

Preserve `_FRED_CSV_URL`, parsing helpers, `_DEFAULT_KEYWORDS`, HTML parser fallback, `_extract_symbols`, sector sorting, and evidence dictionaries exactly.

- [ ] **Step 3: Implement the injected CNInfo adapter**

Create `backend/integrations/cninfo/adapter.py` without any service import. The constructor and fetch dependency must be:

```python
from collections.abc import Callable
from typing import Any

FetchAnnouncements = Callable[..., list[dict[str, Any]]]


class CninfoAnnouncementAdapter:
    source_name = "akshare/eastmoney"
    reliability = "wire"
    category = "announcement"
    base_url = "https://fundf10.eastmoney.com/jjgg.html"

    def __init__(
        self,
        *,
        fetch_announcements: FetchAnnouncements,
        limit: int = 20,
    ):
        self._fetch_announcements = fetch_announcements
        self.limit = max(1, int(limit))

    def fetch(
        self,
        *,
        client=None,
        trade_date: str,
        brief_type: str = "post_market",
    ) -> list[dict]:
        try:
            rows = self._fetch_announcements(limit=self.limit)
        except Exception:
            return []
        out: list[dict] = []
        for row in rows or []:
            title = row.get("title")
            if not title:
                continue
            ann_date = row.get("ann_date") or trade_date
            fund_code = row.get("fund_code") or ""
            source_url = (
                f"https://fundf10.eastmoney.com/jjgg_{fund_code}_{ann_date}.html"
                if fund_code and ann_date
                else self.base_url
            )
            symbols = [
                symbol
                for symbol in (row.get("fund_name"), fund_code)
                if symbol
            ]
            out.append({
                "trade_date": trade_date,
                "brief_type": brief_type,
                "category": self.category,
                "source": self.source_name,
                "source_url": source_url,
                "title": title,
                "summary": (
                    f"{row.get('fund_name') or fund_code or '基金'} - {ann_date}"
                ),
                "symbols": symbols,
                "metrics": None,
                "published_at": ann_date,
                "reliability": self.reliability,
            })
            if len(out) >= self.limit:
                break
        return out
```

This preserves the legacy mapping and changes only the previously unbound collector call to `self._fetch_announcements(...)`.

Export only the class:

```python
from backend.integrations.cninfo.adapter import CninfoAnnouncementAdapter

__all__ = ["CninfoAnnouncementAdapter"]
```

- [ ] **Step 4: Implement the injected CLS adapter**

Create `backend/integrations/cls/adapter.py` without importing `cls_telegraph_client`. Use this constructor contract:

```python
from collections.abc import Callable
from typing import Any

import httpx

FetchClsRollList = Callable[..., list[dict[str, Any]]]


class ClsTelegraphAdapter:
    source = "财联社"
    reliability = "wire"
    category = "news"

    def __init__(
        self,
        *,
        fetch_roll_list: FetchClsRollList,
        app_version: str,
        client: Any | None = None,
        categories: str | list[str] | tuple[str, ...] | None = None,
        per_category_limit: int = 10,
        timeout_seconds: float = 15.0,
        max_attempts: int = 1,
        retry_base_seconds: float = 1.0,
    ):
        self._fetch_roll_list = fetch_roll_list
        self.client = client
        self.categories = _parse_categories(categories)
        self.per_category_limit = max(1, int(per_category_limit))
        self.timeout_seconds = float(timeout_seconds)
        self.app_version = app_version
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_seconds = float(retry_base_seconds)
        self.last_errors: list[dict] = []
```

Keep `_parse_categories`, `_to_evidence`, client ownership, close handling, outer failure isolation, and category loop unchanged. Replace only the client call:

```python
rows = self._fetch_roll_list(
    client=active_client,
    category=category,
    limit=self.per_category_limit,
    timeout_seconds=self.timeout_seconds,
    app_version=self.app_version,
    diagnostics=self.last_errors,
    max_attempts=self.max_attempts,
    retry_base_seconds=self.retry_base_seconds,
)
```

Export only `ClsTelegraphAdapter` from the provider `__init__.py`.

- [ ] **Step 5: Implement the default factory**

Create `backend/integrations/market_evidence.py` with the existing policy/FRED constant values and this signature:

```python
DEFAULT_POLICY_ADAPTERS: list[tuple[str, str, str]] = [
    ("NMPA", "https://www.nmpa.gov.cn/yaopin/", "official"),
    ("CSRC", "https://www.csrc.gov.cn/csrc/c100028/common_list.shtml", "official"),
    ("PBOC", "http://www.pbc.gov.cn/zhengwugongkai/4081330/index.html", "official"),
    ("NDRC", "https://www.ndrc.gov.cn/xxgk/zcfb/", "official"),
    ("MOF", "http://www.mof.gov.cn/zhengwuxinxi/zhengcefabu/", "official"),
]

DEFAULT_FRED_SERIES: list[tuple[str, str]] = [
    ("DFF", "美国联邦基金有效利率"),
    ("CPIAUCSL", "美国 CPI 月环比"),
    ("UNRATE", "美国失业率"),
]


def build_default_adapters(
    *,
    client,
    fetch_cls_roll_list,
    fetch_announcements,
    brief_type: str = "post_market",
    sector_snapshot: dict | None = None,
) -> list:
```

Import adapter classes only from provider packages. Construct the existing order exactly:

```python
if brief_type == "pre_market":
    adapters.extend(
        FredSeriesAdapter(series_id=sid, title=title)
        for sid, title in DEFAULT_FRED_SERIES
    )
    adapters.extend(
        PolicyPageAdapter(source=name, url=url, reliability=reliability)
        for name, url, reliability in DEFAULT_POLICY_ADAPTERS
    )
else:
    adapters.extend(
        PolicyPageAdapter(source=name, url=url, reliability=reliability)
        for name, url, reliability in DEFAULT_POLICY_ADAPTERS
    )
    adapters.append(CninfoAnnouncementAdapter(
        fetch_announcements=fetch_announcements,
    ))
    adapters.extend(
        FredSeriesAdapter(series_id=sid, title=title)
        for sid, title in DEFAULT_FRED_SERIES
    )
    if sector_snapshot is not None:
        adapters.append(SectorHeatAdapter(sector_snapshot=sector_snapshot))
```

Inside the existing CLS configuration `try`, inject the required values:

```python
adapters.append(ClsTelegraphAdapter(
    fetch_roll_list=fetch_cls_roll_list,
    client=client,
    categories=settings.cls_categories,
    per_category_limit=settings.cls_per_category_limit,
    timeout_seconds=settings.cls_timeout_seconds,
    app_version=settings.cls_app_version,
    max_attempts=int(getattr(settings, "cls_max_attempts", 1)),
    retry_base_seconds=float(
        getattr(settings, "cls_retry_base_seconds", 1.0)
    ),
))
```

Preserve the warning call exactly:

```python
logger.warning(
    "CLS adapter disabled due to configuration error: %s",
    exc,
    exc_info=True,
)
```

Set the public surface explicitly; consumers import adapter classes from provider packages:

```python
__all__ = [
    "build_default_adapters",
    "DEFAULT_POLICY_ADAPTERS",
    "DEFAULT_FRED_SERIES",
]
```

- [ ] **Step 6: Run provider behavior tests**

Run:

```bash
.venv/bin/pytest -q \
  backend/tests/test_market_source_adapters.py \
  backend/tests/test_market_sources_cls_config.py
```

Expected: PASS. The hard-cut contract still fails only because the legacy package has not yet been deleted.

- [ ] **Step 7: Compile and check the new dependency boundary**

Run:

```bash
.venv/bin/python -m compileall -q backend/integrations
.venv/bin/pytest -q \
  backend/tests/test_market_integration_contract.py::test_integrations_do_not_import_services \
  backend/tests/test_market_integration_contract.py::test_provider_package_imports \
  backend/tests/test_market_integration_contract.py::test_market_evidence_factory_imports
```

Expected: compile exits 0 and the selected contract tests PASS.

---

### Task 3: Wire the service composition root and update consumers

**Files:**
- Modify: `backend/services/market/market_evidence_service.py`
- Modify: `backend/tests/test_market_evidence_service.py`
- Modify: `backend/tests/test_briefing_service.py`

**Interfaces:**
- Consumes: `build_default_adapters` and its two required callable parameters from Task 2.
- Produces: runtime injection of `cls_telegraph_client.fetch_roll_list` and `data_collector.fetch_announcements` without reversing the integrations dependency.

- [ ] **Step 1: Add the failing composition-root test**

Append this test to `backend/tests/test_market_evidence_service.py`:

```python
def test_collect_injects_service_owned_fetchers_and_closes_client():
    from unittest.mock import MagicMock, patch

    import httpx

    from backend.services.knowledge import cls_telegraph_client
    from backend.services.market import data_collector
    from backend.services.market import market_evidence_service as mes

    client = MagicMock()
    factory = MagicMock(return_value=[])
    ingest = MagicMock(return_value={"inserted": 0, "fetched": 0, "errors": []})

    with patch.object(httpx, "Client", return_value=client), \
         patch.object(mes, "build_default_adapters", factory), \
         patch.object(mes.ing, "ingest_market_evidence", ingest):
        result = mes.collect_and_run_for_brief_type(
            "post_market",
            trade_date="2026-07-16",
        )

    assert result == {"inserted": 0, "fetched": 0, "errors": []}
    assert factory.call_args.kwargs["fetch_cls_roll_list"] is (
        cls_telegraph_client.fetch_roll_list
    )
    assert factory.call_args.kwargs["fetch_announcements"] is (
        data_collector.fetch_announcements
    )
    client.close.assert_called_once_with()
```

- [ ] **Step 2: Run the composition test and confirm RED**

Run:

```bash
.venv/bin/pytest -q \
  backend/tests/test_market_evidence_service.py::test_collect_injects_service_owned_fetchers_and_closes_client
```

Expected: FAIL because the service still imports the old factory and does not pass the required callables.

- [ ] **Step 3: Switch the service to the new factory and inject local service dependencies**

Replace the module import with:

```python
from backend.integrations.market_evidence import build_default_adapters
```

Inside `collect_and_run_for_brief_type`, immediately before calling the factory, import the existing implementations locally to avoid new module-import cost or cycles:

```python
from backend.services.knowledge import cls_telegraph_client
from backend.services.market import data_collector

adapters = build_default_adapters(
    client=client,
    fetch_cls_roll_list=cls_telegraph_client.fetch_roll_list,
    fetch_announcements=data_collector.fetch_announcements,
    brief_type=brief_type,
    sector_snapshot=sector_snapshot,
)
```

Do not change HTTP client construction/cleanup, ingestion arguments, session handling, async refresh, status tracking, or singleflight locks.

- [ ] **Step 4: Remove the briefing test's stale import and patch the runtime lookup point**

In `test_run_collects_evidence_before_reading`, delete the unused legacy import and change the patch target to the symbol actually used by the service:

```python
with patch(
    "backend.services.market.market_evidence_service.build_default_adapters",
    noop_adapter_factory,
), patch.object(
    briefing_service,
    "collect_watchlist_snapshot",
    lambda **_: {
        "market_snapshot": [],
        "watchlist_changes": [],
        "errors": [],
        "collect_meta": {},
    },
), patch.object(
    briefing_service,
    "compose_briefing",
    lambda snap, evidence=None, *, profile=None: {
        "markdown": "# 测试简报",
        "sections": {},
        "warnings": [],
        "llm_model": "test",
    },
):
    result = briefing_service.run_daily_briefing(
        trigger="manual",
        session=in_memory_session,
    )
```

Keep the test's database assertions unchanged.

- [ ] **Step 5: Run service and briefing tests**

Run with the disposable PostgreSQL URL available to the current shell:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/pytest -q \
  backend/tests/test_market_evidence_service.py \
  backend/tests/test_briefing_service.py
```

Expected: PASS.

---

### Task 4: Delete the legacy package and close the hard-cut gate

**Files:**
- Delete: `backend/services/market_sources/__init__.py`
- Delete: `backend/services/market_sources/_utils.py`
- Delete: `backend/services/market_sources/cls_telegraph.py`
- Delete: `backend/services/market_sources/cninfo.py`
- Delete: `backend/services/market_sources/fred.py`
- Delete: `backend/services/market_sources/policy_page.py`
- Delete: `backend/services/market_sources/sector.py`

**Interfaces:**
- Consumes: all new imports and provider implementations from Tasks 2–3.
- Produces: no importable legacy path, no duplicate adapter implementation, and a one-way service-to-integrations dependency.

- [ ] **Step 1: Search for legacy consumers before deletion**

Run:

```bash
rg -n 'backend\.services\.market_sources|from backend\.services import market_sources' \
  backend --glob '*.py'
```

Expected: matches only inside `backend/services/market_sources/` itself and the hard-cut test's string literal. Any production or migrated-test import must be corrected before deletion.

- [ ] **Step 2: Delete all seven legacy source files**

Use `apply_patch` file deletions for the seven files listed above. Do not leave an empty `__init__.py`, redirect module, or generated bytecode in the package path.

The current checkout contains only generated bytecode below the legacy `__pycache__`. After source deletion, inspect and remove that cache so the package directory itself disappears:

```bash
find backend/services/market_sources -maxdepth 2 -type f -print
rm -rf backend/services/market_sources/__pycache__
rmdir backend/services/market_sources
```

Expected: the first command lists only `.pyc` files; `rm` and `rmdir` then succeed. Stop if any non-generated file remains.

- [ ] **Step 3: Run the complete hard-cut contract**

Run:

```bash
.venv/bin/pytest -q backend/tests/test_market_integration_contract.py
```

Expected: PASS for path deletion, old imports, one-way dependency, and all provider imports.

- [ ] **Step 4: Run all focused market-evidence tests together**

Run:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/pytest -q \
  backend/tests/test_market_integration_contract.py \
  backend/tests/test_market_source_adapters.py \
  backend/tests/test_market_sources_cls_config.py \
  backend/tests/test_market_evidence_service.py \
  backend/tests/test_market_evidence_ingestion.py \
  backend/tests/test_briefing_service.py
```

Expected: PASS with no network access because all external callables and HTTP responses are mocked.

- [ ] **Step 5: Run static path and compile gates**

Run:

```bash
.venv/bin/python -m compileall -q backend
git diff --check
test ! -d backend/services/market_sources
rg -n 'backend\.services\.market_sources|from backend\.services import market_sources' \
  backend --glob '*.py'
```

Expected: compile and diff checks exit 0, the directory test succeeds, and `rg` finds only the deliberate string inside the contract test. Inspect any other match as a failure.

---

### Task 5: Run full PostgreSQL regression, review, and create the atomic commit

**Files:**
- Verify: every file listed in the File Map; do not add unrelated refactors.

**Interfaces:**
- Consumes: the completed hard cut from Tasks 1–4.
- Produces: verification evidence and one atomic implementation commit.

- [ ] **Step 1: Run the unit marker suite**

Run:

```bash
.venv/bin/python -m pytest -q backend/tests -m unit
```

Expected: no failures.

- [ ] **Step 2: Run the complete PostgreSQL backend suite**

Run:

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/pytest -q backend/tests
```

Expected: no failures. Record passed/skipped/warning counts. If PostgreSQL is not running, start the disposable test cluster and rerun the exact command; do not fall back to SQLite.

- [ ] **Step 3: Run final static gates**

Run:

```bash
.venv/bin/python -m compileall -q backend
git diff --check
test ! -d backend/services/market_sources
rg -n 'backend\.services\.market_sources|from backend\.services import market_sources' \
  backend --glob '*.py'
git status --short
```

Expected: compile and diff checks pass; the legacy directory is absent; the old-path search has only the contract-test literal; status lists only planned provider, service, test, and deletion changes. The AST contract already proves that integrations do not import services.

- [ ] **Step 4: Review the complete diff against the design**

Confirm all of the following before staging:

```text
- Five adapter implementations exist only below backend/integrations.
- No backend/integrations Python file imports backend.services.
- Factory parameters and both injected constructor dependencies are required.
- Policy/FRED defaults and post/pre adapter order are unchanged.
- CLS settings, retry arguments, diagnostics, and client ownership are unchanged.
- CNInfo maps the injected collector result and still isolates collector failures.
- market_evidence_service still owns client cleanup, ingestion, status, and singleflight.
- No Settings, ingestion, repository, transaction, scheduler, or database code changed.
```

- [ ] **Step 5: Stage only the planned implementation files**

Run:

```bash
git add \
  backend/integrations \
  backend/services/market/market_evidence_service.py \
  backend/services/market_sources \
  backend/tests/test_market_integration_contract.py \
  backend/tests/test_market_source_adapters.py \
  backend/tests/test_market_sources_cls_config.py \
  backend/tests/test_market_evidence_service.py \
  backend/tests/test_briefing_service.py
git diff --cached --check
git diff --cached --stat
```

Expected: staged diff contains only the hard cut and all cached checks pass.

- [ ] **Step 6: Create the atomic implementation commit**

Run:

```bash
git commit -m "refactor: hard cut market evidence integrations"
```

Expected: one implementation commit containing provider migration, callable injection, CNInfo correction, consumer updates, legacy deletion, and contract tests.

- [ ] **Step 7: Verify the committed state**

Run:

```bash
git status --short
git log -1 --oneline
```

Expected: worktree is clean and the latest commit is `refactor: hard cut market evidence integrations`.
