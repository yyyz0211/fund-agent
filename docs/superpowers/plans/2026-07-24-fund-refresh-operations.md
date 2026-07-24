# Shared Fund Refresh Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 manual refresh、Scheduler 和 Watchlist preload 重复使用的 basic+NAV 与 profile 刷新收拢为两个稳定、类型化的 Application 操作，同时保留每个触发方现有的失败组合语义。

**Architecture:** `backend/application/fund/refresh.py` 拥有 collect → short persist 的唯一实现和 frozen DTO；现有 Fund/Profile service 只作兼容 facade；Route、Graph tool、Scheduler 和 preload 改用具体 Application 操作；没有 mode flag、万能协调器、通用 UoW 或新的线程/协程 fan-out。

**Tech Stack:** Python 3.11、dataclasses、FastAPI、SQLAlchemy 2 同步 Session、PostgreSQL、AkShare 串行 Provider facade、pytest。

## Global Constraints

- 必须在 `2026-07-24-scheduler-akshare-safety.md` 和 `2026-07-24-watchlist-atomic-feature.md` 完成后执行。
- 前置安全单元已经移除 `_collect_refresh_data()` 与 `_collect_profile_frames()` 的线程 fan-out；本计划不得重新引入 executor、`asyncio.to_thread()` 或协程包装。
- `backend/application/fund/refresh.py` 不 import ORM Model、Delivery/Graph 模块或通用 Service facade；它只依赖 Repository、`session_scope()`、Provider facade 和稳定异常类型。
- 网络 collect 必须发生在打开自有 `session_scope()` 之前。传入 `session` 时，只使用该 Session 的 flush-based Repository 操作，不 commit/rollback/close，也不进入第二个 `session_scope()`。
- 新组合用例必须显式 collect 后再在短事务 persist；不得把一体化 refresh 函数作为“已经执行 SQL 的长事务”内的新代码模式。
- mandatory NAV 失败抛 `DataSourceError`；fund info 失败只进入 `fund_info_warn`；profile 有可用 payload 但字段缺失时返回 `missing_data/errors`，只有无法形成结果时抛 `DataSourceError`。
- 持久化异常保持数据库异常，不包装成 `DataSourceError`。
- `BasicNavRefreshResult` 与 `ProfileRefreshResult` 内部使用 frozen dataclass；跨 Route/Graph/facade 边界前必须转为 plain dict/list/scalar。
- `fund_service.refresh_fund()` 继续把 `DataSourceError` 映射为旧 `{error, source}` dict。
- `fund_profile_service.refresh_profile()` 不捕获 `DataSourceError`。`backend/services/shared/diagnosis_refresh_jobs.py` 仍依赖“异常 → failed”；若 profile facade 改成 error dict，该 job 会错误标记为 done。
- 本切片不迁移 `diagnosis_refresh_jobs.py`；把它登记为 profile facade 的剩余生产调用者和删除阻塞项。
- 手动 Funds Route 必须显式保留旧 502 +
  `{"detail": "akshare timeout"}` 形状，包括
  `DataSourceTimeoutError`，不得被全局 handler 改成 504/结构化 error。
- Scheduler 保持 basic 成功后才 profile；basic 失败跳过 profile；profile 失败是 soft failure。
- Watchlist preload 始终分别尝试 basic 和 profile；两步都失败为 `failed`，只成功一步或有 warning/missing/error 为 `partial`，全部成功为 `done`。
- 不引入 `scopes`、`trigger` mode、Provider Protocol、DI container、泛型 result、Command Bus 或全局刷新协调器。
- 每个 checkpoint 的 `git diff --cached --name-status` 必须只包含该命令后
  明确列出的路径；出现额外路径时停止提交。所有 checkpoint 使用
  `git commit --only -- <exact paths>`，不得消费并行存在的用户暂存修改。

---

## File Map

**Create**

- `backend/application/fund/__init__.py`
- `backend/application/fund/refresh.py`
- `backend/tests/test_fund_refresh_application.py`
- `backend/tests/test_fund_refresh_contract.py`

**Modify**

- `backend/application/__init__.py` — 若前一切片已创建则保留为空或只维护包说明。
- `backend/services/fund/fund_service.py` — basic facade 与 auto lookup。
- `backend/services/fund/fund_profile_service.py` — profile facade。
- `backend/api/routes/funds.py` — manual HTTP adapter。
- `backend/tools/fund_tools.py` — Graph/LangChain adapter。
- `backend/services/market/scheduled_refresh.py` — Scheduler 组合规则。
- `backend/services/watchlist/watchlist_preload_jobs.py` — preload 组合规则。
- `backend/tests/test_service_transaction_boundaries.py`
- `backend/tests/test_fund_service.py`
- `backend/tests/test_fund_profile_service.py`
- `backend/tests/test_api_funds.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_scheduled_refresh.py`
- `backend/tests/test_watchlist_preload_jobs.py`
- `docs/superpowers/specs/2026-07-24-maintainability-first-vertical-slices-design.md` — facade 退出清单。

**Verify without modifying**

- `backend/services/shared/diagnosis_refresh_jobs.py` — 唯一保留的 profile facade 生产调用者。
- `backend/exceptions.py` — 复用 `DataSourceError` / `DataSourceTimeoutError`。
- `backend/db/repositories/fund.py` — 继续只 flush。

**Do not modify**

- `backend/services/market/data_collector.py` 的安全基线和锁策略。
- Watchlist add Application/Route/Frontend Feature。
- Diagnosis refresh job 的状态机。
- SQLAlchemy engine/session 类型。

---

### Task 1: Record the caller and compatibility baseline

**Files:**

- Inspect: every production caller listed in the File Map.

- [ ] **Step 1: Confirm the implementation index is empty**

Run:

```bash
if ! git diff --cached --quiet; then
  echo "The Git index already contains changes; reconcile ownership before implementing this plan"
  exit 1
fi

if ! git diff --quiet -- \
  docs/superpowers/specs/2026-07-24-maintainability-first-vertical-slices-design.md; then
  echo "The design inventory has uncommitted owner changes; preserve them before this plan updates it"
  exit 1
fi
```

Expected: both guards exit 0. Do not begin this plan while another person's
changes are staged or while the inventory document has an uncommitted owner
hunk, because every later checkpoint assumes only this plan owns the named
paths.

- [ ] **Step 2: Confirm the safety prerequisite**

Run:

```bash
if rg -n \
  'ThreadPoolExecutor|_REFRESH_FETCH_WORKERS|_PROFILE_FETCH_WORKERS|_PROFILE_SOURCE_TIMEOUT_SECONDS' \
  backend/services/fund/fund_service.py \
  backend/services/market/data_collector.py; then
  echo "AkShare safety prerequisite is incomplete"
  exit 1
fi
```

Expected: the guard exits 0. If it prints a match, finish the safety plan before proceeding.

- [ ] **Step 3: Capture the exact legacy caller inventory**

Run:

```bash
rg -n 'refresh_fund\(|refresh_profile\(' \
  backend --glob '*.py' --glob '!backend/tests/**'
```

Expected before migration:

- Funds Route;
- fund Graph tool;
- `fund_service.lookup_fund_auto`;
- Scheduler;
- Watchlist preload;
- `diagnosis_refresh_jobs` profile path;
- the two compatibility facade definitions.

Save the output. It is the deletion-baseline evidence for Task 6.

- [ ] **Step 4: Run current compatibility tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_service_transaction_boundaries.py \
  backend/tests/test_tools.py::test_refresh_fund_tool
```

When the disposable PostgreSQL test database is available:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_fund_service.py \
  backend/tests/test_fund_profile_service.py \
  backend/tests/test_api_funds.py \
  backend/tests/test_scheduled_refresh.py \
  backend/tests/test_watchlist_preload_jobs.py
```

Expected: current legacy behavior passes before the types and callers are moved.

---

### Task 2: Define typed collect/persist operations

**Files:**

- Create: `backend/application/fund/refresh.py`
- Create: `backend/application/fund/__init__.py`
- Create: `backend/tests/test_fund_refresh_application.py`
- Modify: `backend/tests/test_service_transaction_boundaries.py`

**Public interfaces:**

| Function | Parameters | Return |
|---|---|---|
| `collect_basic_and_nav` | `fund_code: str` | `CollectedBasicAndNav` |
| `persist_basic_and_nav` | `collected: CollectedBasicAndNav`, keyword-only `session: Session` | `BasicNavRefreshResult` |
| `refresh_basic_and_nav` | `fund_code: str`, keyword-only `session: Session \| None = None` | `BasicNavRefreshResult` |
| `collect_profile` | `fund_code: str` | `CollectedProfile` |
| `persist_profile` | `collected: CollectedProfile`, keyword-only `session: Session` | `ProfileRefreshResult` |
| `refresh_profile` | `fund_code: str`, keyword-only `session: Session \| None = None` | `ProfileRefreshResult` |

- [ ] **Step 1: Add RED mandatory-NAV and optional-info tests**

Create `backend/tests/test_fund_refresh_application.py`, mark it `pytest.mark.unit`, and add:

- `test_basic_collect_nav_error_raises_datasource_error_and_skips_info`
- `test_basic_collect_nav_exception_raises_datasource_error`
- `test_basic_collect_rejects_non_list_nav_payload`
- `test_basic_info_error_is_warning_and_nav_is_persisted`
- `test_basic_info_exception_is_warning_and_nav_is_persisted`

For NAV failure:

```python
with pytest.raises(DataSourceError) as raised:
    fund_refresh.collect_basic_and_nav("110011")

assert raised.value.source == "akshare"
assert raised.value.details == {
    "fund_code": "110011",
    "stage": "collect_nav",
}
assert info_calls == []
assert session_events == []
```

For optional info:

```python
assert result.navs_inserted == 1
assert result.fund_info_warn == "fund info unavailable"
assert nav_writes == ["110011"]
assert fund_writes == []
```

Expected RED: the Application module does not exist.

- [ ] **Step 2: Add RED transaction-order and injected-session tests**

Add:

- `test_refresh_basic_and_nav_collects_before_owned_session`
- `test_refresh_basic_and_nav_uses_injected_session_without_owning_it`
- `test_persistence_exception_is_not_wrapped_as_datasource_error`

Exact order:

```python
assert events == [
    "collect",
    "session_enter",
    "nav_flush",
    "fund_flush",
    "session_exit",
]
```

For the injected path, patch `session_scope` to fail if entered and provide an object with `commit`, `rollback`, and `close` methods that fail if called. Assert both Repository operations receive that exact object.

- [ ] **Step 3: Add RED profile typing, partial result and fatal payload tests**

Add:

- `test_profile_partial_result_is_typed_and_serializable`
- `test_profile_error_payload_raises_datasource_error_before_session`
- `test_profile_provider_exception_raises_datasource_error_before_session`
- `test_profile_non_mapping_payload_raises_datasource_error_before_session`
- `test_profile_mapping_without_profile_fields_raises_datasource_error_before_session`
- `test_profile_metadata_only_mapping_raises_datasource_error_before_session`
- `test_refresh_profile_uses_injected_session_without_owning_it`

For the partial result:

```python
assert isinstance(result.profile, FundProfileSnapshot)
assert result.missing_data == ("rank", "peers")
assert result.errors == ("rank unavailable",)
assert result.to_dict()["missing_data"] == ["rank", "peers"]
assert result.to_dict()["errors"] == ["rank unavailable"]
assert result.profile.peer_candidates_json == (
    '[{"fund_code": "000001"}]'
)
assert result.profile.raw_errors == (
    '["rank unavailable"]'
)
```

Add ordered de-duplication input with repeated missing/error strings and assert first-occurrence order.

- [ ] **Step 4: Implement frozen collection and result DTOs**

Create the dataclasses in `backend/application/fund/refresh.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
from typing import Any

from sqlalchemy.orm import Session

from backend.db.repositories import fund as fund_repo
from backend.db.session_scope import session_scope
from backend.exceptions import DataSourceError
from backend.services.market import data_collector as dc


@dataclass(frozen=True)
class CollectedBasicAndNav:
    fund_code: str
    nav_rows: tuple[dict[str, Any], ...]
    fund_info: dict[str, Any] | None
    fund_info_warn: str | None
    source: str
    as_of: str


@dataclass(frozen=True)
class BasicNavRefreshResult:
    fund_code: str
    navs_inserted: int
    already_up_to_date: bool
    fund_info_warn: str | None
    source: str
    as_of: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CollectedProfile:
    fund_code: str
    scale: float | None
    scale_date: str | None
    peer_category: str | None
    rank_total: int | None
    rank_position: int | None
    peer_candidates: tuple[dict[str, Any], ...]
    top10_holding_pct: float | None
    top_industry_pct: float | None
    manager_summary: str | None
    missing_data: tuple[str, ...]
    errors: tuple[str, ...]
    source: str
    as_of: str | None


@dataclass(frozen=True)
class FundProfileSnapshot:
    fund_code: str
    scale: float | None = None
    scale_date: str | None = None
    peer_category: str | None = None
    rank_total: int | None = None
    rank_position: int | None = None
    peer_candidates_json: str | None = None
    top10_holding_pct: float | None = None
    top_industry_pct: float | None = None
    manager_summary: str | None = None
    source: str | None = None
    as_of: str | None = None
    raw_errors: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileRefreshResult:
    fund_code: str
    profile: FundProfileSnapshot
    missing_data: tuple[str, ...]
    errors: tuple[str, ...]
    source: str
    as_of: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "profile": self.profile.to_dict(),
            "missing_data": list(self.missing_data),
            "errors": list(self.errors),
            "source": self.source,
            "as_of": self.as_of,
        }
```

- [ ] **Step 5: Implement basic collect/persist**

Add:

```python
def _data_source_error(
    message: str,
    *,
    fund_code: str,
    stage: str,
    source: str | None = None,
) -> DataSourceError:
    return DataSourceError(
        message,
        source=source or dc.SOURCE,
        details={
            "fund_code": fund_code,
            "stage": stage,
        },
    )


def collect_basic_and_nav(
    fund_code: str,
) -> CollectedBasicAndNav:
    try:
        nav_payload = dc.fetch_fund_nav_history(fund_code)
    except Exception as exc:
        raise _data_source_error(
            f"fetch_fund_nav_history failed for {fund_code}: {exc}",
            fund_code=fund_code,
            stage="collect_nav",
        ) from exc

    if (
        isinstance(nav_payload, Mapping)
        and "error" in nav_payload
    ):
        raise _data_source_error(
            str(nav_payload["error"]),
            fund_code=fund_code,
            stage="collect_nav",
            source=str(
                nav_payload.get("source") or dc.SOURCE
            ),
        )
    if (
        not isinstance(nav_payload, list)
        or not all(
            isinstance(row, Mapping)
            for row in nav_payload
        )
    ):
        raise _data_source_error(
            f"invalid NAV payload for {fund_code}",
            fund_code=fund_code,
            stage="collect_nav",
        )

    fund_info: dict[str, Any] | None
    fund_info_warn: str | None
    try:
        info_payload = dc.fetch_fund_info(fund_code)
    except Exception as exc:
        fund_info = None
        fund_info_warn = (
            f"fetch_fund_info failed for {fund_code}: {exc}"
        )
    else:
        if (
            isinstance(info_payload, Mapping)
            and "error" in info_payload
        ):
            fund_info = None
            fund_info_warn = str(info_payload["error"])
        elif isinstance(info_payload, Mapping):
            fund_info = dict(info_payload)
            fund_info_warn = None
        else:
            fund_info = None
            fund_info_warn = (
                f"invalid fund info payload for {fund_code}"
            )

    return CollectedBasicAndNav(
        fund_code=fund_code,
        nav_rows=tuple(
            dict(row) for row in nav_payload
        ),
        fund_info=fund_info,
        fund_info_warn=fund_info_warn,
        source=dc.SOURCE,
        as_of=dc.today_str(),
    )


def persist_basic_and_nav(
    collected: CollectedBasicAndNav,
    *,
    session: Session,
) -> BasicNavRefreshResult:
    inserted = fund_repo.upsert_navs(
        session,
        collected.fund_code,
        list(collected.nav_rows),
    )
    if collected.fund_info is not None:
        fund_repo.upsert_fund(
            session,
            {
                "fund_code": collected.fund_code,
                **{
                    key: collected.fund_info.get(key)
                    for key in (
                        "fund_name",
                        "fund_type",
                        "manager",
                        "company",
                    )
                },
            },
        )
    return BasicNavRefreshResult(
        fund_code=collected.fund_code,
        navs_inserted=inserted,
        already_up_to_date=inserted == 0,
        fund_info_warn=collected.fund_info_warn,
        source=collected.source,
        as_of=collected.as_of,
    )


def refresh_basic_and_nav(
    fund_code: str,
    *,
    session: Session | None = None,
) -> BasicNavRefreshResult:
    collected = collect_basic_and_nav(fund_code)
    if session is not None:
        return persist_basic_and_nav(
            collected,
            session=session,
        )
    with session_scope() as owned_session:
        return persist_basic_and_nav(
            collected,
            session=owned_session,
        )
```

- [ ] **Step 6: Implement profile collect/persist**

Add:

```python
def _ordered_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        dict.fromkeys(str(item) for item in value)
    )


def collect_profile(fund_code: str) -> CollectedProfile:
    try:
        payload = dc.fetch_fund_profile(fund_code)
    except Exception as exc:
        raise _data_source_error(
            f"fetch_fund_profile failed for {fund_code}: {exc}",
            fund_code=fund_code,
            stage="collect_profile",
        ) from exc

    if not isinstance(payload, Mapping):
        raise _data_source_error(
            f"invalid profile payload for {fund_code}",
            fund_code=fund_code,
            stage="collect_profile",
        )
    if "error" in payload:
        raise _data_source_error(
            str(payload["error"]),
            fund_code=fund_code,
            stage="collect_profile",
            source=str(payload.get("source") or dc.SOURCE),
        )
    profile_value_fields = {
        "scale",
        "scale_date",
        "peer_category",
        "rank_total",
        "rank_position",
        "peer_candidates",
        "top10_holding_pct",
        "top_industry_pct",
        "manager_summary",
    }
    if profile_value_fields.isdisjoint(payload):
        raise _data_source_error(
            f"unformable profile payload for {fund_code}",
            fund_code=fund_code,
            stage="collect_profile",
        )

    candidates = payload.get("peer_candidates")
    normalized_candidates = (
        tuple(
            dict(item)
            for item in candidates
            if isinstance(item, Mapping)
        )
        if isinstance(candidates, (list, tuple))
        else ()
    )
    as_of = payload.get("as_of")
    return CollectedProfile(
        fund_code=fund_code,
        scale=payload.get("scale"),
        scale_date=payload.get("scale_date"),
        peer_category=payload.get("peer_category"),
        rank_total=payload.get("rank_total"),
        rank_position=payload.get("rank_position"),
        peer_candidates=normalized_candidates,
        top10_holding_pct=payload.get(
            "top10_holding_pct"
        ),
        top_industry_pct=payload.get(
            "top_industry_pct"
        ),
        manager_summary=payload.get("manager_summary"),
        missing_data=_ordered_strings(
            payload.get("missing_data")
        ),
        errors=_ordered_strings(payload.get("errors")),
        source=str(payload.get("source") or dc.SOURCE),
        as_of=str(as_of) if as_of is not None else None,
    )


def persist_profile(
    collected: CollectedProfile,
    *,
    session: Session,
) -> ProfileRefreshResult:
    attrs = {
        "scale": collected.scale,
        "scale_date": collected.scale_date,
        "peer_category": collected.peer_category,
        "rank_total": collected.rank_total,
        "rank_position": collected.rank_position,
        "peer_candidates_json": json.dumps(
            list(collected.peer_candidates),
            ensure_ascii=False,
        ),
        "top10_holding_pct": (
            collected.top10_holding_pct
        ),
        "top_industry_pct": collected.top_industry_pct,
        "manager_summary": collected.manager_summary,
        "source": collected.source,
        "as_of": collected.as_of or dc.today_str(),
        "raw_errors": json.dumps(
            list(collected.errors),
            ensure_ascii=False,
        ),
    }
    persisted = fund_repo.upsert_fund_profile(
        session,
        collected.fund_code,
        attrs,
    )
    snapshot = FundProfileSnapshot(
        fund_code=str(persisted["fund_code"]),
        scale=persisted.get("scale"),
        scale_date=persisted.get("scale_date"),
        peer_category=persisted.get("peer_category"),
        rank_total=persisted.get("rank_total"),
        rank_position=persisted.get("rank_position"),
        peer_candidates_json=persisted.get(
            "peer_candidates_json"
        ),
        top10_holding_pct=persisted.get(
            "top10_holding_pct"
        ),
        top_industry_pct=persisted.get(
            "top_industry_pct"
        ),
        manager_summary=persisted.get(
            "manager_summary"
        ),
        source=persisted.get("source"),
        as_of=persisted.get("as_of"),
        raw_errors=persisted.get("raw_errors"),
        created_at=persisted.get("created_at"),
        updated_at=persisted.get("updated_at"),
    )
    return ProfileRefreshResult(
        fund_code=collected.fund_code,
        profile=snapshot,
        missing_data=collected.missing_data,
        errors=collected.errors,
        source=collected.source,
        as_of=collected.as_of or dc.today_str(),
    )


def refresh_profile(
    fund_code: str,
    *,
    session: Session | None = None,
) -> ProfileRefreshResult:
    collected = collect_profile(fund_code)
    if session is not None:
        return persist_profile(
            collected,
            session=session,
        )
    with session_scope() as owned_session:
        return persist_profile(
            collected,
            session=owned_session,
        )
```

Metadata-only mappings such as `{"source": "akshare"}` or
`{"errors": ["down"]}` are fatal because they contain no actual profile field.
A mapping that includes at least one value-field key remains formable even when
that value is `None`; it becomes a typed partial result with
`missing_data/errors`.

- [ ] **Step 7: Export the concrete operations**

Create `backend/application/fund/__init__.py`:

```python
from .refresh import (
    BasicNavRefreshResult,
    CollectedBasicAndNav,
    CollectedProfile,
    FundProfileSnapshot,
    ProfileRefreshResult,
    collect_basic_and_nav,
    collect_profile,
    persist_basic_and_nav,
    persist_profile,
    refresh_basic_and_nav,
    refresh_profile,
)

__all__ = [
    "BasicNavRefreshResult",
    "CollectedBasicAndNav",
    "CollectedProfile",
    "FundProfileSnapshot",
    "ProfileRefreshResult",
    "collect_basic_and_nav",
    "collect_profile",
    "persist_basic_and_nav",
    "persist_profile",
    "refresh_basic_and_nav",
    "refresh_profile",
]
```

- [ ] **Step 8: Run the typed Application GREEN suite**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_fund_refresh_application.py
```

Expected GREEN: mandatory/optional errors, collect-before-session, injected Session and frozen serialization tests pass.

- [ ] **Step 9: Keep the boundary uncommitted until its first production caller**

```bash
git diff --check -- \
  backend/application/fund \
  backend/tests/test_fund_refresh_application.py
git status --short -- \
  backend/application/fund \
  backend/tests/test_fund_refresh_application.py
```

Expected: the typed boundary and RED/GREEN tests are present and clean under
`git diff --check`, but no commit is created yet. Proceed directly to Task 3
and connect both compatibility facades in the same logical commit; do not land
an Application abstraction with no production caller.

---

### Task 3: Convert the old services into compatibility facades

**Files:**

- Modify: `backend/services/fund/fund_service.py`
- Modify: `backend/services/fund/fund_profile_service.py`
- Modify: `backend/tests/test_service_transaction_boundaries.py`
- Modify: `backend/tests/test_fund_service.py`
- Modify: `backend/tests/test_fund_profile_service.py`

- [ ] **Step 1: Add RED facade error-mapping tests**

Add:

```python
def test_legacy_refresh_fund_maps_typed_error_to_error_dict(
    monkeypatch,
):
    monkeypatch.setattr(
        fund_refresh,
        "refresh_basic_and_nav",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DataSourceError(
                "akshare timeout",
                source="akshare",
            )
        ),
    )

    assert fund_service.refresh_fund("110011") == {
        "error": "akshare timeout",
        "source": "akshare",
    }


def test_legacy_refresh_profile_keeps_typed_error_as_exception(
    monkeypatch,
):
    monkeypatch.setattr(
        fund_refresh,
        "refresh_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DataSourceError(
                "profile source down",
                source="akshare",
            )
        ),
    )

    with pytest.raises(
        DataSourceError,
        match="profile source down",
    ):
        fund_profile_service.refresh_profile("110011")
```

Expected RED: facades still own direct collection/persistence.

- [ ] **Step 2: Replace the basic facade and remove duplicate orchestration**

In `fund_service.py`, import:

```python
from backend.application.fund import refresh as fund_refresh
from backend.exceptions import DataSourceError
```

Replace `refresh_fund` with:

```python
def refresh_fund(fund_code: str, session=None) -> dict:
    """Compatibility facade for legacy dict callers."""
    try:
        result = fund_refresh.refresh_basic_and_nav(
            fund_code,
            session=session,
        )
    except DataSourceError as exc:
        return {
            "error": str(exc),
            "source": exc.source or dc.SOURCE,
        }
    return result.to_dict()
```

Delete the old `_persist_refresh_data`, `_collector_error`, and `_collect_refresh_data` implementations. Replace the safety-plan tests that named `_collect_refresh_data` with the equivalent `collect_basic_and_nav` order/error tests in `test_fund_refresh_application.py`; do not keep tests for a deleted private function.

- [ ] **Step 3: Replace the profile facade without catching typed errors**

In `fund_profile_service.py`, import:

```python
from backend.application.fund import refresh as fund_refresh
```

Replace only `refresh_profile`:

```python
def refresh_profile(fund_code: str, session=None) -> dict:
    """Compatibility facade; profile failures remain exceptions."""
    return fund_refresh.refresh_profile(
        fund_code,
        session=session,
    ).to_dict()
```

Remove `import json` and the `data_collector as dc` import. Retain
`datetime/timedelta`, `fund_repo`, and `session_scope`, because `get_profile()`
and `is_profile_fresh()` still use them.

- [ ] **Step 4: Rewrite transaction-boundary tests around the Application**

In `backend/tests/test_service_transaction_boundaries.py`:

- delete the safety-unit tests that directly name the now-removed
  `_collect_refresh_data`; their NAV → info and independent-error behavior is
  now covered against `collect_basic_and_nav()` in
  `test_fund_refresh_application.py`;
- rewrite `test_refresh_fund_accepts_injected_session_and_only_persists_there`
  to patch `fund_service.fund_refresh.refresh_basic_and_nav`, record the exact
  `session` argument, return a fake object with `to_dict()`, and assert the
  facade output remains a dict;
- rewrite the corresponding profile test to patch
  `fund_profile_service.fund_refresh.refresh_profile` in the same way.

The Application tests themselves patch `fund_refresh.collect_*`/Repository
functions and assert:

- exact injected Session reaches persist;
- no owned `session_scope()` is entered;
- no commit/rollback/close method is called;
- facade output remains a dict.

Keep PostgreSQL persistence assertions in `test_fund_service.py` and
`test_fund_profile_service.py`. In the two existing profile persistence tests,
import `backend.application.fund.refresh as fund_refresh` and change
`monkeypatch.setattr(fps.dc, "fetch_fund_profile", ...)` to
`monkeypatch.setattr(fund_refresh.dc, "fetch_fund_profile", ...)`; the profile
facade no longer owns a `dc` attribute. Basic collector tests similarly patch
the Application collector module rather than a deleted service private.

- [ ] **Step 5: Run facade GREEN tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_fund_refresh_application.py \
  backend/tests/test_service_transaction_boundaries.py
```

Run with PostgreSQL:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_fund_service.py \
  backend/tests/test_fund_profile_service.py
```

Expected GREEN: public dict fields, partial profile encoding and injected-session compatibility are unchanged.

- [ ] **Step 6: Commit the compatibility facades**

```bash
git add backend/application/fund/__init__.py \
  backend/application/fund/refresh.py \
  backend/services/fund/fund_service.py \
  backend/services/fund/fund_profile_service.py \
  backend/tests/test_fund_refresh_application.py \
  backend/tests/test_service_transaction_boundaries.py \
  backend/tests/test_fund_service.py \
  backend/tests/test_fund_profile_service.py
git diff --cached --name-status
git diff --cached --check
git commit --only -m "refactor: add typed fund refresh operations and facades" -- \
  backend/application/fund/__init__.py \
  backend/application/fund/refresh.py \
  backend/services/fund/fund_service.py \
  backend/services/fund/fund_profile_service.py \
  backend/tests/test_fund_refresh_application.py \
  backend/tests/test_service_transaction_boundaries.py \
  backend/tests/test_fund_service.py \
  backend/tests/test_fund_profile_service.py
```

---

### Task 4: Migrate manual HTTP, Graph and auto-lookup callers

**Files:**

- Modify: `backend/api/routes/funds.py`
- Modify: `backend/tools/fund_tools.py`
- Modify: `backend/services/fund/fund_service.py`
- Modify: `backend/tests/test_api_funds.py`
- Modify: `backend/tests/test_tools.py`
- Modify: `backend/tests/test_fund_service.py`

- [ ] **Step 1: Add RED manual HTTP compatibility tests**

Change route tests to patch `funds_routes.fund_refresh.refresh_basic_and_nav`.

Cover:

- success DTO → HTTP 200 and exact legacy fields;
- `DataSourceError("akshare timeout")` → 502 and `{"detail":"akshare timeout"}`;
- `DataSourceTimeoutError("akshare slow")` → still 502/detail, not 504/structured body.

The timeout assertion:

```python
assert response.status_code == 502
assert response.json() == {
    "detail": "akshare slow",
}
```

Expected RED: Route still consumes `fs.refresh_fund()` dict.

- [ ] **Step 2: Migrate the Funds Route with a local legacy mapping**

Import:

```python
from backend.application.fund import refresh as fund_refresh
from backend.exceptions import DataSourceError
```

Replace `post_refresh` body:

```python
try:
    result = fund_refresh.refresh_basic_and_nav(code)
except DataSourceError as exc:
    raise HTTPException(
        status_code=502,
        detail=str(exc),
    ) from exc
return result.to_dict()
```

The local catch intentionally maps `DataSourceTimeoutError` to the old 502.

- [ ] **Step 3: Add RED Graph tool DTO/error tests**

Update `backend/tests/test_tools.py`:

- success mock returns `BasicNavRefreshResult`; assert tool output is a dict;
- typed error returns exact
  `{"error": "akshare timeout", "source": "akshare"}`;
- no dataclass escapes into LangChain serialization.

- [ ] **Step 4: Migrate the Graph tool**

Replace the tool body with:

```python
try:
    result = fund_refresh.refresh_basic_and_nav(fund_code)
except DataSourceError as exc:
    return {
        "error": str(exc),
        "source": exc.source or "akshare",
    }
return result.to_dict()
```

Import the Application module and `DataSourceError`; do not return the dataclass itself.

- [ ] **Step 5: Migrate `lookup_fund_auto` while preserving degradation**

Inside `fund_service.lookup_fund_auto`, replace the facade call with:

```python
try:
    refresh_result = fund_refresh.refresh_basic_and_nav(
        fund_code,
        session=session,
    )
    result = refresh_result.to_dict()
except Exception as exc:  # noqa: BLE001
    result = {
        "error": str(exc),
        "source": (
            exc.source
            if isinstance(exc, DataSourceError)
            and exc.source
            else dc.SOURCE
        ),
    }
```

Keep `refresh_meta` shape and error extraction unchanged. Add a test asserting the injected Session is forwarded unchanged.
In that test, also monkeypatch `fund_service.refresh_fund` to raise
`AssertionError("lookup_fund_auto must not call the legacy facade")`; the test
must still pass through `fund_refresh.refresh_basic_and_nav`.

- [ ] **Step 6: Run manual-caller GREEN tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_api_funds.py::test_refresh_success \
  backend/tests/test_api_funds.py::test_refresh_already_up_to_date \
  backend/tests/test_api_funds.py::test_refresh_failure_returns_502 \
  backend/tests/test_api_funds.py::test_refresh_timeout_still_returns_502_detail \
  backend/tests/test_tools.py::test_refresh_fund_tool \
  backend/tests/test_tools.py::test_refresh_fund_tool_maps_typed_error_to_legacy_dict
```

Run the auto-lookup subset with PostgreSQL:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_fund_service.py \
  backend/tests/test_api_funds.py \
  backend/tests/test_tools.py
```

Expected GREEN: legacy HTTP/Graph/auto response contracts are preserved.

- [ ] **Step 7: Commit manual caller migration**

```bash
git add backend/api/routes/funds.py \
  backend/tools/fund_tools.py \
  backend/services/fund/fund_service.py \
  backend/tests/test_api_funds.py \
  backend/tests/test_tools.py \
  backend/tests/test_fund_service.py
git diff --cached --name-status
git diff --cached --check
git commit --only -m "refactor: migrate manual fund refresh callers" -- \
  backend/api/routes/funds.py \
  backend/tools/fund_tools.py \
  backend/services/fund/fund_service.py \
  backend/tests/test_api_funds.py \
  backend/tests/test_tools.py \
  backend/tests/test_fund_service.py
```

---

### Task 5: Migrate the Scheduler composition rule

**Files:**

- Modify: `backend/services/market/scheduled_refresh.py`
- Modify: `backend/tests/test_scheduled_refresh.py`

- [ ] **Step 1: Rewrite RED Scheduler tests with typed DTOs**

Patch `sr.fund_refresh.refresh_basic_and_nav` and `refresh_profile`. Cover:

- exact order basic then profile for each successful fund;
- basic failure marks that fund failed, skips its profile, and loop continues;
- profile exception is soft: `succeeded=1`, `failed=0`, no public failure entry;
- profile DTO with `missing_data/errors` is still Scheduler success;
- `already_up_to_date` comes from the DTO boolean;
- the Session used to list Watchlist rows is not passed into network refresh operations.

Expected RED: production still imports both legacy service facades.

- [ ] **Step 2: Replace `_refresh_one` with typed Application calls**

Replace service imports with:

```python
from backend.application.fund import refresh as fund_refresh
```

Replace `_refresh_one`:

```python
def _refresh_one(fund_code: str) -> dict:
    try:
        basic = fund_refresh.refresh_basic_and_nav(
            fund_code,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "fund_code": fund_code,
            "ok": False,
            "error": str(exc),
        }

    try:
        fund_refresh.refresh_profile(fund_code)
    except Exception as exc:  # noqa: BLE001
        return {
            "fund_code": fund_code,
            "ok": True,
            "already_up_to_date": (
                basic.already_up_to_date
            ),
            "profile_error": str(exc),
        }

    return {
        "fund_code": fund_code,
        "ok": True,
        "already_up_to_date": basic.already_up_to_date,
    }
```

- [ ] **Step 3: Run Scheduler GREEN tests**

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_scheduled_refresh.py
```

Expected GREEN: all existing batch snapshot behavior and new call-order/skip assertions pass.

- [ ] **Step 4: Commit Scheduler migration**

```bash
git add backend/services/market/scheduled_refresh.py \
  backend/tests/test_scheduled_refresh.py
git diff --cached --name-status
git diff --cached --check
git commit --only -m "refactor: migrate scheduled fund refresh" -- \
  backend/services/market/scheduled_refresh.py \
  backend/tests/test_scheduled_refresh.py
```

---

### Task 6: Migrate Watchlist preload while retaining independent attempts

**Files:**

- Modify: `backend/services/watchlist/watchlist_preload_jobs.py`
- Modify: `backend/tests/test_watchlist_preload_jobs.py`

- [ ] **Step 1: Add the RED six-case preload matrix**

Use typed `BasicNavRefreshResult` and `ProfileRefreshResult` fixtures. Cover:

| Basic outcome | Profile outcome | Expected status |
|---|---|---|
| clean success | clean success | `done` |
| success with info warning | clean success | `partial`, missing `fund` |
| clean success | partial DTO | `partial`, profile missing/errors retained |
| typed failure | clean success | `partial`, profile still called |
| clean success | exception | `partial`, missing `profile` |
| typed failure | exception | `failed` |

Each case must assert:

- returned job snapshot;
- persisted `watchlist.preload_status`;
- ordered, de-duplicated `missing_data/errors`;
- profile runs even after basic failure;
- non-empty profile `as_of` replaces basic `as_of`.

Expected RED: `_run_preload` still interprets dicts from both service facades.

- [ ] **Step 2: Replace preload service imports and result handling**

Import:

```python
from backend.application.fund import refresh as fund_refresh
from backend.exceptions import DataSourceError
```

Inside `_run_preload`, replace the two refresh blocks with:

```python
        try:
            basic = fund_refresh.refresh_basic_and_nav(
                fund_code,
            )
            successful_steps += 1
            as_of = basic.as_of
            if basic.fund_info_warn:
                errors.append(basic.fund_info_warn)
                missing_data.append("fund")
        except DataSourceError as exc:
            errors.append(str(exc))
            missing_data.extend(["fund", "nav"])
        except Exception as exc:  # noqa: BLE001
            errors.append(
                f"refresh_fund failed: {exc}"
            )
            missing_data.extend(["fund", "nav"])

        try:
            profile = fund_refresh.refresh_profile(
                fund_code,
            )
            successful_steps += 1
            as_of = profile.as_of or as_of
            missing_data.extend(profile.missing_data)
            errors.extend(profile.errors)
        except Exception as exc:  # noqa: BLE001
            errors.append(
                f"refresh_profile failed: {exc}"
            )
            missing_data.append("profile")
```

Keep the existing ordered `dict.fromkeys` de-duplication and status formula:

```python
if successful_steps == 0:
    status = "failed"
elif missing_data or errors:
    status = "partial"
else:
    status = "done"
```

Remove the now-unused `get_session`, `fund_service` and `fund_profile_service` imports.

- [ ] **Step 3: Run preload GREEN tests**

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q -n 0 \
  backend/tests/test_watchlist_preload_jobs.py \
  backend/tests/test_watchlist_preload_dispatch.py
```

Expected GREEN: all six outcomes and the earlier submit-cleanup lifecycle pass.

- [ ] **Step 4: Commit preload migration**

```bash
git add backend/services/watchlist/watchlist_preload_jobs.py \
  backend/tests/test_watchlist_preload_jobs.py
git diff --cached --name-status
git diff --cached --check
git commit --only -m "refactor: migrate watchlist preload refresh" -- \
  backend/services/watchlist/watchlist_preload_jobs.py \
  backend/tests/test_watchlist_preload_jobs.py
```

---

### Task 7: Guard the boundary and update facade exit inventory

**Files:**

- Create: `backend/tests/test_fund_refresh_contract.py`
- Modify: `docs/superpowers/specs/2026-07-24-maintainability-first-vertical-slices-design.md`

- [ ] **Step 1: Add unit architecture and serialization guards**

Create `backend/tests/test_fund_refresh_contract.py`, mark it `pytest.mark.unit`, and assert:

- both integrated operations have keyword-only `session=None`;
- `refresh.py` imports neither `backend.db.models` nor Delivery/Graph modules;
- source contains no `.commit()`, `.rollback()`, `.close()`, `ThreadPoolExecutor`, `executor.submit`, `asyncio` or `to_thread`;
- Funds Route, fund Graph tool, Scheduler and preload do not call legacy refresh facades;
- a function-scoped AST test named
  `test_lookup_fund_auto_calls_application_directly` asserts
  `lookup_fund_auto()` contains a call to
  `fund_refresh.refresh_basic_and_nav(...)` and contains no bare
  `refresh_fund(...)` call;
- all five collection/result/snapshot dataclasses are frozen;
- `to_dict()` output recursively contains only dict/list/string/number/bool/None;
- no ORM object escapes.

- [ ] **Step 2: Update the explicit facade inventory**

In the design document’s facade table/nearby text, record:

```text
fund_service.refresh_fund
  production callers after this slice: none
  deletion blocker: compatibility imports/tests and an explicit removal release

fund_profile_service.refresh_profile
  remaining production caller:
    backend/services/shared/diagnosis_refresh_jobs.py::_run_refresh
  deletion blocker:
    migrate that job while preserving exception → failed semantics
```

Do not claim the profile facade can be deleted in this slice.

- [ ] **Step 3: Verify the static caller result**

Run:

```bash
rg -n \
  '(fund_service|fs)\.refresh_fund|profile_service\.refresh_profile' \
  backend --glob '*.py' --glob '!backend/tests/**'
```

Expected: only the profile call in `backend/services/shared/diagnosis_refresh_jobs.py`; no production basic-facade call.

Run:

```bash
if rg -n \
  'ThreadPoolExecutor|executor\.submit|asyncio|to_thread' \
  backend/application/fund; then
  echo "unexpected concurrency wrapper in fund refresh application"
  exit 1
fi
```

Expected: the guard exits 0.

- [ ] **Step 4: Run architecture GREEN tests**

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_fund_refresh_application.py \
  backend/tests/test_fund_refresh_contract.py \
  backend/tests/test_transaction_ownership_contract.py \
  backend/tests/test_service_layer_import_boundaries.py
```

Expected GREEN: all boundary, ownership and import checks pass.

- [ ] **Step 5: Commit the guard and inventory**

```bash
git add backend/tests/test_fund_refresh_contract.py \
  docs/superpowers/specs/2026-07-24-maintainability-first-vertical-slices-design.md
git diff --cached --name-status
git diff --cached -- \
  docs/superpowers/specs/2026-07-24-maintainability-first-vertical-slices-design.md
git diff --cached --check
git commit --only -m "test: guard the fund refresh application boundary" -- \
  backend/tests/test_fund_refresh_contract.py \
  docs/superpowers/specs/2026-07-24-maintainability-first-vertical-slices-design.md
```

---

### Task 8: Verify the complete shared refresh slice

**Files:**

- Verify: all files in this plan.

- [ ] **Step 1: Run the complete backend unit partition**

```bash
.venv/bin/python -m pytest -q backend/tests -m unit
```

Expected: all unit tests pass.

- [ ] **Step 2: Run ordinary PostgreSQL integration tests**

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q backend/tests -n 2 \
  -m "not unit and not db_multiconnection and not db_ddl and not db_pgvector"
```

Expected: all selected tests pass.

- [ ] **Step 3: Run multi-connection PostgreSQL tests**

```bash
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
.venv/bin/python -m pytest -q backend/tests -n 0 \
  -m db_multiconnection
```

Expected: all multi-connection tests pass serially.

- [ ] **Step 4: Run static verification**

```bash
.venv/bin/python -m compileall -q backend
git diff --check
```

Expected: both exit 0.

- [ ] **Step 5: Review the final production dependency direction**

Run:

```bash
if rg -n \
  '(fund_service|fs)\.refresh_fund\(|(profile_service|fund_profile_service|fps)\.refresh_profile\(' \
  backend/api/routes/funds.py \
  backend/tools/fund_tools.py \
  backend/services/market/scheduled_refresh.py \
  backend/services/watchlist/watchlist_preload_jobs.py; then
  echo "migrated caller still invokes a legacy refresh facade"
  exit 1
fi
```

Expected: the guard exits 0. Imports of `fund_service` for unrelated read
operations are allowed; this gate rejects only legacy refresh call sites. The
Task 7 AST contract remains the authoritative alias-independent check.

Run the function-scoped guard explicitly:

```bash
.venv/bin/python -m pytest -q \
  backend/tests/test_fund_refresh_contract.py::test_lookup_fund_auto_calls_application_directly
```

Expected: `lookup_fund_auto()` invokes the Application operation directly; a
facade call fails even though that facade currently delegates to the same
operation.

- [ ] **Step 6: Review scope and commits**

```bash
git status --short
git log --oneline --stat HEAD~5..HEAD
git diff --stat HEAD~5..HEAD
git diff --check HEAD~5..HEAD
git diff HEAD~5..HEAD
```

Expected: the five planned commits contain no empty Application-only commit,
new async wrapper, mode flag, generic UoW, Provider protocol, ORM leakage, or
unrelated user change.
