# Phase 1.2 统一事务所有权 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 backend 的事务所有权统一为"顶层入口拥有事务"——repository 仅 `flush()`、service 不 commit/close、API 与 scheduler 顶层用 `session_scope()` 包裹。

**Architecture:**
1. `db/repository.py` 全部写函数改为默认 `flush()`;移除内嵌 `s.commit()`,把 commit 决策交回调用方
2. Service 层去掉 `if owns: s.commit() / s.close()` 的 49 处 `owns` 模式;service 只 flush
3. 9 个长事务 service 的网络/LLM 调用挪出事务(先 fetch 再 bind session 写库)
4. API 路由层删除 `session.commit()`,统一通过 `Depends(get_db_session)`,由 service flush
5. 顶层事务(scheduler jobs / CLI)用 `db.session_scope.session_scope()`
6. 关键不变量:在任何 service 函数体里,只能 `flush()`,不能 `commit/rollback/close`

**Tech Stack:** Python 3.11, SQLAlchemy 2.x (PostgreSQL), FastAPI, APScheduler, pytest, PostgreSQL test fixtures

**依据:**
- 规格 `docs/superpowers/specs/2026-07-14-fund-agent-refactoring-design.md` §4.2
- 调研报告:`backend/db/session_scope.py` (已实现但未被调用)、`backend/db/session.py` (ContextVar override 已实现)
- 调研输出:14 个 service 文件 / 31 处 commit / 39 处 close / 17 处 repository commit / 9 个长事务

## Global Constraints

- **PostgreSQL only**: `DATABASE_URL` 必须 postgresql+psycopg2://...;禁止 sqlite 字符串
- **Test DB safety**: `TEST_DATABASE_URL` 必须以 `_test` 结尾;不满足则拒绝运行
- **API 写路由**: FastAPI `Depends(get_db_session)`;事务由依赖注入器控制,service 不 commit
- **Service 契约**: service 函数体内部禁止 `s.commit() / s.rollback() / s.close()`;只允许 `s.flush()` 和 `s.add()` / `s.execute()`
- **Repository 契约**: repository 函数体内部禁止 `s.commit() / s.rollback() / s.close()`;只允许 `s.flush()`,事务边界由 caller 决定
- **顶层事务**: scheduler / CLI / 跨 service 原子操作走 `with session_scope() as s:`
- **保留 commit 边界的 service**(多表原子):`watchlist_service.set_initial_holding`、`watchlist_service.confirm_pending_buy`、`transaction_service.recalc_holding` — 保留原 service 内部 commit(后续单独优化)
- **保留 commit 边界的 service**(短事务示范):`knowledge_reindex_jobs` 的 mark_running / mark_completed / mark_failed — 已是正确的短事务模式,本次不动
- **测试纪律**: 每个 service / repository 改造前先写一个 AST 静态扫描测试防止回归;然后单元测试

---

## Task 0: 准备工作 + 加固测试基础设施

### Task 0.1: 添加事务契约扫描测试(防止后续回归)

**Files:**
- Create: `backend/tests/test_transaction_ownership_contract.py`
- Modify: 无

**目标:** 用 AST 静态扫描所有 `backend/services/**/*.py` 和 `backend/db/repository.py` 的函数体,确认不含 `s.commit()` / `s.rollback()` / `s.close()`。

- [ ] **Step 1: 写扫描测试骨架**

```python
"""事务所有权契约:service / repository 函数体禁止 commit / rollback / close。"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# 已知保留 commit 边界的多步原子 service
ALLOWED_INTERNAL_COMMIT_SERVICES: frozenset[str] = frozenset({
    "backend/services/watchlist/watchlist_service.py",  # set_initial_holding / confirm_pending_buy
    "backend/services/watchlist/transaction_service.py",  # recalc_holding
    "backend/services/knowledge/knowledge_reindex_jobs.py",  # mark_*
})


def _method_bodies(tree: ast.AST) -> list[ast.stmt]:
    """收集所有 FunctionDef / AsyncFunctionDef 的 body。"""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _has_forbidden_call(body: list[ast.stmt]) -> str | None:
    """扫描 body 内的直接方法调用,返回第一个违规项,或 None。"""
    forbidden = {"commit", "rollback", "close"}
    for stmt in body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in forbidden:
                # 只关心 <session_var>.commit() / rollback() / close()
                # 排除 `client.close()` / `engine.dispose()` / `pool.close()`
                if isinstance(func.value, ast.Name) and func.value.id in {
                    "session", "s", "db_session", "_session",
                }:
                    return f"{func.value.id}.{func.attr}()"
    return None


@pytest.mark.parametrize(
    "service_path",
    sorted(Path("backend/services").rglob("*.py")),
    ids=lambda p: str(p),
)
def test_service_does_not_commit_or_close_session(service_path: Path) -> None:
    if str(service_path) in ALLOWED_INTERNAL_COMMIT_SERVICES:
        pytest.skip(f"{service_path.name} is in allowed list")
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(service_path))
    for fn in _method_bodies(tree):
        if not fn.name.startswith("test_"):  # 排除测试函数(本目录不含测试,但保守)
            violation = _has_forbidden_call(fn.body)
            assert violation is None, (
                f"{service_path}:{fn.name}() calls {violation}; "
                f"service 函数体只能 flush(),不能 commit/rollback/close"
            )


def test_repository_does_not_commit_session() -> None:
    """repository 也不允许 commit/rollback/close;只允许 flush。"""
    repo_path = Path("backend/db/repository.py")
    source = repo_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(repo_path))
    for fn in _method_bodies(tree):
        violation = _has_forbidden_call(fn.body)
        assert violation is None, (
            f"repository.{fn.name}() calls {violation}; repository 仅允许 flush"
        )
```

- [ ] **Step 2: 运行测试,确认它能加载且当前 FAIL**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_transaction_ownership_contract.py --no-header -q`

Expected: 大部分 `test_service_does_not_commit_or_close_session` 失败(因为当前 service 内有 `s.commit()` 等);`test_repository_does_not_commit_session` 失败

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/tests/test_transaction_ownership_contract.py
git commit -m "test: add AST contract for service/repository transaction ownership"
```

---

### Task 0.2: 强化 `session_scope` 文档并加测试

**Files:**
- Modify: `backend/db/session_scope.py`
- Create: `backend/tests/test_session_scope.py`

- [ ] **Step 1: 写 session_scope 测试**

```python
"""session_scope() 顶层事务上下文管理器测试(spec 4.2)。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.db.session_scope import session_scope


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.session = MagicMock()
        self.session.commit = MagicMock(side_effect=self._on_commit)
        self.session.rollback = MagicMock(side_effect=self._on_rollback)
        self.session.close = MagicMock(side_effect=self._on_close)

    def _on_commit(self) -> None:
        self.committed = True

    def _on_rollback(self) -> None:
        self.rolled_back = True

    def _on_close(self) -> None:
        self.closed = True

    def __call__(self) -> MagicMock:
        return self.session


def test_commit_on_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.db import session as session_module

    factory = _FakeSessionFactory()
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    with session_scope() as s:
        assert s is factory.session
        assert s.execute  # MagicMock has it
    assert factory.committed
    assert not factory.rolled_back
    assert factory.closed


def test_rollback_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.db import session as session_module

    factory = _FakeSessionFactory()
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    with pytest.raises(RuntimeError, match="boom"):
        with session_scope():
            raise RuntimeError("boom")
    assert factory.rolled_back
    assert not factory.committed
    assert factory.closed


def test_close_always_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.db import session as session_module

    factory = _FakeSessionFactory()
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    with session_scope():
        pass
    assert factory.closed
```

- [ ] **Step 2: 运行测试,确认通过**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_session_scope.py --no-header -q`

Expected: 3 passed

- [ ] **Step 3: 在 session_scope.py 顶部补充 docstring 强调 spec 4.2 用法**

修改 `backend/db/session_scope.py` 顶部 docstring,在 `用途` 列表后追加:

```python
"""
用法示例(scheduler / CLI / 跨 service 原子操作):

    from backend.db.session_scope import session_scope

    def scheduled_job():
        with session_scope() as session:
            # 业务逻辑
            session.add(obj)
        # 自动 commit;异常时自动 rollback + raise

禁止用法:
- service 函数体内部禁止开 session_scope()(破坏调用方事务)
- service 函数体内部禁止 commit/rollback/close(只允许 flush)
"""
```

- [ ] **Step 4: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/tests/test_session_scope.py backend/db/session_scope.py
git commit -m "test+docs: cover session_scope with mocks; document forbidden uses"
```

---

## Task 1: Repository 改写为默认 flush(大爆炸)

### Task 1.1: 拆 `add_to_watchlist` / `add_to_watchlist_full` / `remove_from_watchlist`

**Files:**
- Modify: `backend/db/repository.py:130-205`

- [ ] **Step 1: 读当前实现**

Run: `sed -n '130,210p' backend/db/repository.py`

确认 3 个函数当前形态。

- [ ] **Step 2: 改写 3 个函数,移除内嵌 commit,改为 `s.flush()`**

```python
def add_to_watchlist(
    session: Session,
    *,
    fund_code: str,
    fund_name: str | None = None,
    note: str | None = None,
) -> Watchlist:
    """添加基金到自选池。事务边界由 caller 决定(默认仅 flush)。"""
    row = Watchlist(
        fund_code=fund_code,
        fund_name=fund_name,
        note=note,
        added_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def add_to_watchlist_full(
    session: Session,
    *,
    fund_code: str,
    fund_name: str | None = None,
    note: str | None = None,
    initial_holding: Decimal | None = None,
    initial_cost: Decimal | None = None,
    added_at: datetime | None = None,
) -> Watchlist:
    """完整版本,带初始持仓和成本。事务边界由 caller 决定。"""
    row = Watchlist(
        fund_code=fund_code,
        fund_name=fund_name,
        note=note,
        initial_holding=initial_holding,
        initial_cost=initial_cost,
        added_at=added_at or datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def remove_from_watchlist(
    session: Session,
    *,
    fund_code: str,
) -> None:
    """删除自选池条目(级联 5+ 表)。事务边界由 caller 决定。"""
    row = session.get(Watchlist, fund_code)
    if row is None:
        raise ResourceNotFoundError(f"watchlist fund {fund_code} not found")
    session.delete(row)
    session.flush()
```

注意:`ResourceNotFoundError` 已在 `backend/exceptions.py` 定义(Task 4.3)。

- [ ] **Step 3: 跑 AST 契约测试,确认这部分已通过**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_transaction_ownership_contract.py::test_repository_does_not_commit_session --no-header -q`

Expected: 大概率仍 FAIL(还有 14 处 commit 未改)。**这是预期**——继续。

- [ ] **Step 4: 跑现有 service 测试,确保不破**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_watchlist_service.py --no-header -q 2>&1 | tail -10`

Expected: 部分失败(因为 service 仍调 s.commit,改成 flush 后 service 拿不到 PK),但**先继续完成所有 repository 改造后再统一修 service**。

- [ ] **Step 5: 暂不 commit,继续 Task 1.2**

(避免在过渡期产生 broken commit)

---

### Task 1.2: 拆 `update_watchlist_note` / `update_watchlist` / `update_watchlist_preload` / `backfill_watchlist_fund_names`

**Files:**
- Modify: `backend/db/repository.py:203-285`

- [ ] **Step 1: 改写 4 个函数**

```python
def update_watchlist_note(session: Session, *, fund_code: str, note: str) -> None:
    row = session.get(Watchlist, fund_code)
    if row is None:
        raise ResourceNotFoundError(f"watchlist fund {fund_code} not found")
    row.note = note
    row.updated_at = datetime.now(timezone.utc)
    session.flush()


def update_watchlist(
    session: Session,
    *,
    fund_code: str,
    fund_name: str | None = None,
    note: str | None = None,
    initial_holding: Decimal | None = None,
    initial_cost: Decimal | None = None,
) -> Watchlist:
    row = session.get(Watchlist, fund_code)
    if row is None:
        raise ResourceNotFoundError(f"watchlist fund {fund_code} not found")
    if fund_name is not None:
        row.fund_name = fund_name
    if note is not None:
        row.note = note
    if initial_holding is not None:
        row.initial_holding = initial_holding
    if initial_cost is not None:
        row.initial_cost = initial_cost
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return row


def update_watchlist_preload(
    session: Session,
    *,
    fund_code: str,
    preloaded: bool,
) -> None:
    row = session.get(Watchlist, fund_code)
    if row is None:
        raise ResourceNotFoundError(f"watchlist fund {fund_code} not found")
    row.preloaded = preloaded
    session.flush()


def backfill_watchlist_fund_names(session: Session) -> int:
    """回填缺失的 fund_name。事务边界由 caller 决定。"""
    rows = (
        session.query(Watchlist)
        .filter(or_(Watchlist.fund_name.is_(None), Watchlist.fund_name == ""))
        .all()
    )
    if not rows:
        return 0
    for row in rows:
        # ... 原有回填逻辑 ...
        row.fund_name = ...
    session.flush()
    return len(rows)
```

(回填逻辑保持原样,仅把最后的 `session.commit()` 换 `session.flush()`)

- [ ] **Step 2: 暂不 commit,继续 Task 1.3**

---

### Task 1.3: 拆 `upsert_fund` / `upsert_fund_profile` / `upsert_navs`

**Files:**
- Modify: `backend/db/repository.py:289-360`

- [ ] **Step 1: 改写 3 个函数,移除 commit**

```python
def upsert_fund(session: Session, *, fund_code: str, **fields) -> Fund:
    row = session.get(Fund, fund_code)
    if row is None:
        row = Fund(fund_code=fund_code, **fields)
        session.add(row)
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return row


def upsert_fund_profile(
    session: Session,
    *,
    fund_code: str,
    payload: dict,
    source: str = "akshare",
) -> FundProfile:
    """事务边界由 caller 决定。"""
    # ... 原有 upsert 逻辑,仅把 commit 换 flush ...
    session.flush()
    return row


def upsert_navs(
    session: Session,
    *,
    fund_code: str,
    rows: list[dict],
) -> int:
    """事务边界由 caller 决定。"""
    # ... 原有逻辑,仅把 commit 换 flush ...
    session.flush()
    return len(rows)
```

- [ ] **Step 2: 暂不 commit,继续 Task 1.4**

---

### Task 1.4: 拆剩余 11 个 repository 函数

**Files:**
- Modify: `backend/db/repository.py:512-660`

涉及函数:`add_transaction` / `delete_transaction` / `add_investment_plan` / `update_investment_plan` / `delete_investment_plan` / `add_pending_buy` / `update_pending_buy` / `delete_pending_buy`(如有) / `confirm_pending_buy`(如有) / 等

- [ ] **Step 1: 对所有剩余 `session.commit()` 调用统一改为 `session.flush()`**

```python
# 通用模式
def some_repo_function(session: Session, ...):
    # ... 原逻辑 ...
    session.flush()  # 替换原 session.commit()
    return result
```

- [ ] **Step 2: 跑 AST 契约测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_transaction_ownership_contract.py::test_repository_does_not_commit_session --no-header -q`

Expected: **PASS**(所有 repository 改完)

- [ ] **Step 3: 暂不 commit(等 service 修完一并 commit)**

---

## Task 2: Service 层改造 — watchlist 子域(示范)

### Task 2.1: 简化 `watchlist_service` 18 个函数

**Files:**
- Modify: `backend/services/watchlist/watchlist_service.py`

**前提:** watchlist_service.py 大部分函数已经用 `_with_session()` 工具,内含 `if owns: s.close()` 模式。需要:
- 移除 `_with_session()` 里的 `s.close()` 和 `s.commit()`
- 把 `if owns: s.commit()` 改为 `s.flush()`
- 移除 `s.close()` 全部

- [ ] **Step 1: 读 `_with_session` 当前实现**

Run: `grep -n "_with_session\|owns" backend/services/watchlist/watchlist_service.py | head -30`

- [ ] **Step 2: 改写 `_with_session` 为 `_with_session` (新) + 移除 close**

```python
def _with_session(session: Session | None) -> tuple[Session, bool]:
    """返回 (session, owns)。
    
    owns=True 表示调用方负责 commit 和 close(顶层入口 / with session_scope())。
    owns=False 表示 service 仅 flush,事务由外部 owner 控制。
    """
    if session is None:
        return get_session(), True
    return session, False
```

- [ ] **Step 3: 对 18 个函数逐一改写**

模式:
```python
# 改前
def add_to_watchlist(session=None, ...):
    s, owns = _with_session(session)
    try:
        ...
        repo.add_to_watchlist(s, ...)
        if owns:
            s.commit()
    finally:
        if owns:
            s.close()

# 改后
def add_to_watchlist(session=None, ...):
    s, owns = _with_session(session)
    if owns:
        # 顶层入口,自己开 session 就自己 commit
        try:
            repo.add_to_watchlist(s, ...)
            s.commit()
        finally:
            s.close()
    else:
        # service 路径:仅 flush,事务由 caller 决定
        repo.add_to_watchlist(s, ...)
```

更简洁:用 `session_scope()` 包装:

```python
from backend.db.session_scope import session_scope

def add_to_watchlist(session=None, ...):
    if session is None:
        with session_scope() as s:
            return _add_to_watchlist_impl(s, ...)
    return _add_to_watchlist_impl(session, ...)

def _add_to_watchlist_impl(s, ...):
    # 纯业务逻辑,只 flush
    ...
    repo.add_to_watchlist(s, ...)
```

- [ ] **Step 4: 跑测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_watchlist_service.py backend/tests/test_watchlist_routes.py --no-header -q 2>&1 | tail -10`

Expected: 全部通过

- [ ] **Step 5: 跑 AST 契约测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_transaction_ownership_contract.py -k "watchlist_service" --no-header -q`

Expected: 跳过(在白名单)

- [ ] **Step 6: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/services/watchlist/watchlist_service.py
git commit -m "refactor: simplify watchlist_service session ownership; remove explicit commit/close"
```

---

## Task 3: Service 层 — fund 子域(高风险长事务)

### Task 3.1: 重构 `fund_service.refresh_fund`(拆长事务)

**Files:**
- Modify: `backend/services/fund/fund_service.py:29-71`

**问题:** 当前 `refresh_fund()` 在事务内调 `ak.fetch_nav_history` + `ak.fetch_fund_info`(30s+),违反 spec 4.2。

- [ ] **Step 1: 读当前实现**

Run: `sed -n '29,75p' backend/services/fund/fund_service.py`

- [ ] **Step 2: 拆为 fetch + write 两段**

```python
def refresh_fund(fund_code: str) -> dict:
    """刷新基金的净值历史和基本信息。
    
    拆为 fetch (无事务) + write (短事务) 两段,
    避免在数据库事务内持锁 30s+ 等 akshare 返回。
    """
    # 阶段 1:网络拉取,无事务
    nav_history = dc.fetch_fund_nav_history(fund_code)
    fund_info = dc.fetch_fund_info(fund_code) or {}
    
    # 阶段 2:短事务写库
    with session_scope() as session:
        if fund_info:
            repo.upsert_fund(session, fund_code=fund_code, **fund_info)
        if nav_history:
            repo.upsert_navs(session, fund_code=fund_code, rows=nav_history)
    
    return {
        "fund_code": fund_code,
        "nav_rows": len(nav_history),
        "info_updated": bool(fund_info),
    }
```

- [ ] **Step 3: 跑测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_fund_service.py -k "refresh_fund" --no-header -q 2>&1 | tail -10`

Expected: 通过(可能需要适配 mock)

- [ ] **Step 4: 跑 AST 契约测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_transaction_ownership_contract.py -k "fund_service" --no-header -q`

Expected: 通过

- [ ] **Step 5: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/services/fund/fund_service.py
git commit -m "refactor: split fund_service.refresh_fund into fetch + write phases"
```

---

### Task 3.2: 重构 `fund_profile_service.refresh_profile`(拆长事务)

**Files:**
- Modify: `backend/services/fund/fund_profile_service.py:16-56`

- [ ] **Step 1: 读当前实现**

Run: `sed -n '16,60p' backend/services/fund/fund_profile_service.py`

- [ ] **Step 2: 拆 fetch + write**

```python
def refresh_profile(fund_code: str) -> dict:
    """刷新基金 profile。
    
    5+ ak.fetch 移出事务,fetch 完成后才 bind session 写库。
    """
    # 阶段 1:网络拉取,无事务
    frames = _collect_profile_frames(fund_code)  # 原 _collect_profile_frames 已不含 DB
    payload = _merge_frames(frames, fund_code=fund_code)
    
    # 阶段 2:短事务写库
    with session_scope() as session:
        repo.upsert_fund_profile(
            session,
            fund_code=fund_code,
            payload=payload,
            source="akshare",
        )
    
    return {"fund_code": fund_code, "fields_updated": list(payload.keys())}
```

- [ ] **Step 3: 跑测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_fund_profile_service.py --no-header -q 2>&1 | tail -5`

Expected: 通过

- [ ] **Step 4: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/services/fund/fund_profile_service.py
git commit -m "refactor: split fund_profile_service.refresh_profile into fetch + write"
```

---

## Task 4: Service 层 — market 子域(并发 4 个)

### Task 4.1: 重构 `market_service.refresh_market`

**Files:**
- Modify: `backend/services/market/market_service.py`

- [ ] **Step 1: 读当前实现**

Run: `sed -n '20,40p' backend/services/market/market_service.py`

- [ ] **Step 2: 移除内嵌 commit,用 session_scope 包装**

```python
def refresh_market() -> dict:
    with session_scope() as s:
        # ... 原 refresh 逻辑 ...
        s.flush()
    return {"status": "ok"}
```

- [ ] **Step 3: 跑测试 + AST 测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_market_service.py backend/tests/test_transaction_ownership_contract.py -k "market_service and not fund" --no-header -q 2>&1 | tail -5`

Expected: 全部通过

- [ ] **Step 4: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/services/market/market_service.py
git commit -m "refactor: market_service.refresh_market owns its transaction"
```

---

### Task 4.2: 重构 `market_intel_service.collect_market_intel`(拆长事务)

**Files:**
- Modify: `backend/services/market/market_intel_service.py:64-187`

**问题:** 10+ ak.fetch 在事务内。

- [ ] **Step 1: 拆 fetch + write**

```python
def collect_market_intel(...) -> dict:
    # 阶段 1:网络拉取,无事务
    snapshots = _fetch_all_snapshots(brief_type, trade_date)
    
    # 阶段 2:短事务写库
    with session_scope() as s:
        for snap in snapshots:
            repo.upsert_market_snapshot(s, **snap)
    
    return {"snapshots": len(snapshots)}
```

- [ ] **Step 2: 跑测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_market_intel_service.py --no-header -q 2>&1 | tail -5`

Expected: 通过

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/services/market/market_intel_service.py
git commit -m "refactor: split market_intel_service.collect into fetch + write"
```

---

### Task 4.3: 重构 `market_evidence_ingestion.ingest_market_evidence`

**Files:**
- Modify: `backend/services/market/market_evidence_ingestion.py`

- [ ] **Step 1: 拆 fetch + write**

```python
def ingest_market_evidence(...) -> dict:
    # 阶段 1:adapter 拉取,无事务
    evidence_items = []
    for adapter in adapters:
        items = adapter.fetch(...)
        evidence_items.extend(items)
    
    # 阶段 2:短事务写库
    with session_scope() as s:
        repo.upsert_market_evidence_batch(s, items=evidence_items)
    
    return {"fetched": len(evidence_items), "inserted": len(evidence_items)}
```

- [ ] **Step 2: 跑测试 + commit**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_market_evidence_service.py --no-header -q 2>&1 | tail -5`

```bash
cd /Users/leon/fund-agent
git add backend/services/market/market_evidence_ingestion.py
git commit -m "refactor: split market_evidence_ingestion into fetch + write"
```

---

### Task 4.4: 简化 `market_evidence_service`(只读 + 委托)

**Files:**
- Modify: `backend/services/market/market_evidence_service.py`

- [ ] **Step 1: search_evidence 改用 session_scope**

```python
def search_evidence(*, trade_date=None, category=None, query=None, limit=50) -> list[dict]:
    td = trade_date or _today()
    with session_scope() as s:
        return search_market_evidence(
            s, trade_date=td,
            category=category or None,
            query=(query or "").strip() or None,
            limit=limit,
        )
```

- [ ] **Step 2: collect_and_run_for_brief_type 改为委托已修过的 ingest**

```python
def collect_and_run_for_brief_type(...) -> dict:
    return ingest.ingest_market_evidence(...)
```

(因为 ingest 已自带 session_scope)

- [ ] **Step 3: 跑测试 + commit**

```bash
cd /Users/leon/fund-agent
git add backend/services/market/market_evidence_service.py
git commit -m "refactor: market_evidence_service uses session_scope and delegates"
```

---

## Task 5: Service 层 — knowledge 子域(5 个)

### Task 5.1: 简化 `knowledge_search_service`(拆长事务)

**Files:**
- Modify: `backend/services/knowledge/knowledge_search_service.py:154-310, 313-440`

- [ ] **Step 1: 拆 search_knowledge 的 fetch + write**

```python
def search_knowledge(query, *, limit=10, ...):
    # 阶段 1:embedding + vector search,无事务
    provider = get_embedding_provider()
    if provider:
        vector = provider.embed([query])[0]
    results = vector_store.search(vector, limit=limit, ...)
    
    # 阶段 2:写检索日志,短事务
    with session_scope() as s:
        repo.append_retrieval_log(s, query=query, results=results)
    
    return results
```

- [ ] **Step 2: 拆 _run_knowledge_pipeline_once_inner**

(把 LLM classify + embedding 挪出事务,只 flush 索引状态)

- [ ] **Step 3: 跑测试 + commit**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_knowledge_search_service.py --no-header -q 2>&1 | tail -5`

```bash
cd /Users/leon/fund-agent
git add backend/services/knowledge/knowledge_search_service.py
git commit -m "refactor: split knowledge_search into fetch + write phases"
```

---

### Task 5.2: 简化 `cls_telegraph_sync_service.sync_cls_telegraph_once`(分页提交)

**Files:**
- Modify: `backend/services/knowledge/cls_telegraph_sync_service.py:117-237`

**问题:** multi-page HTTP 在事务内(60s+)。

- [ ] **Step 1: 拆为分页循环,每页独立短事务**

```python
def sync_cls_telegraph_once(...) -> dict:
    state = load_sync_state()  # 读 last_ctime
    total_inserted = 0
    has_more = True
    while has_more:
        # 阶段 1:拉一页,无事务
        page = _fetch_page(page_size=50, since=state.last_ctime)
        if not page.items:
            has_more = False
            break
        
        # 阶段 2:短事务写一页
        with session_scope() as s:
            inserted = repo.upsert_cls_telegraph_batch(s, items=page.items)
            state = update_sync_state(s, last_ctime=page.items[-1].ctime, ...)
        total_inserted += inserted
        has_more = page.has_more
    return {"inserted": total_inserted}
```

- [ ] **Step 2: 跑测试 + commit**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_cls_telegraph_sync_service.py --no-header -q 2>&1 | tail -5`

```bash
cd /Users/leon/fund-agent
git add backend/services/knowledge/cls_telegraph_sync_service.py
git commit -m "refactor: cls_telegraph_sync uses per-page transactions"
```

---

### Task 5.3: 简化 `knowledge_ingestion_service.ingest_recent_knowledge`

**Files:**
- Modify: `backend/services/knowledge/knowledge_ingestion_service.py:310-360`

- [ ] **Step 1: 拆 LLM classify + 写库**

```python
def ingest_recent_knowledge(...) -> dict:
    # 阶段 1:LLM classify,无事务
    candidates = fetch_candidates(...)
    classifications = llm.classify_batch(candidates)  # 网络
    
    # 阶段 2:短事务写
    with session_scope() as s:
        for c, cls in zip(candidates, classifications):
            repo.upsert_knowledge_document(s, doc=c, classification=cls)
    
    return {"ingested": len(candidates)}
```

- [ ] **Step 2: 跑测试 + commit**

---

### Task 5.4: 简化 `knowledge_match_service` / `knowledge_fund_profile_service`

**Files:**
- Modify: `backend/services/knowledge/knowledge_match_service.py:91-`
- Modify: `backend/services/knowledge/knowledge_fund_profile_service.py:88-`

- [ ] **Step 1: 用 session_scope 包装末尾的 commit**

```python
def refresh_knowledge_fund_matches(...) -> None:
    with session_scope() as s:
        # 原逻辑,只 flush
        ...
```

- [ ] **Step 2: 跑测试 + commit**

---

### Task 5.5: `knowledge_reindex_jobs` 标记为白名单(已正确)

**Files:**
- Modify: `backend/tests/test_transaction_ownership_contract.py`

- [ ] **Step 1: 确认 `knowledge_reindex_jobs` 已在白名单**

(已在 Task 0.1 中预先加入)

- [ ] **Step 2: 跑契约测试确认跳过**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_transaction_ownership_contract.py -k "knowledge_reindex_jobs" --no-header -v`

Expected: skipped

---

## Task 6: Service 层 — briefing(LLM 长事务)

### Task 6.1: 拆 `briefing_service.run_daily_briefing`(LLM 拆出事务)

**Files:**
- Modify: `backend/services/briefing/briefing_service.py:490-700`

**问题:** evidence 采集 + DeepSeek LLM + upsert 三段混在事务里。

- [ ] **Step 1: 拆三段**

```python
def run_daily_briefing(...) -> dict:
    # 阶段 1:evidence 采集(无事务)
    evidence = collect_evidence_for_brief(brief_type, trade_date, ...)
    
    # 阶段 2:LLM compose(无事务,无 session)
    briefing_text = compose_briefing(evidence, model=model, ...)
    
    # 阶段 3:短事务写库
    with session_scope() as s:
        repo.upsert_briefing(s, payload={"text": briefing_text, ...})
    
    return {"status": "completed", "text": briefing_text}
```

- [ ] **Step 2: 跑测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_briefing_service.py --no-header -q 2>&1 | tail -5`

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/services/briefing/briefing_service.py
git commit -m "refactor: briefing_service.run_daily_briefing splits fetch/compose/persist"
```

---

## Task 7: API 路由层清理

### Task 7.1: 移除路由层 `session.commit()`(knowledge / briefing)

**Files:**
- Modify: `backend/api/routes/knowledge.py:64, 112`
- Modify: `backend/api/routes/briefing.py:192`

- [ ] **Step 1: 读 knowledge.py 路由层 commit**

Run: `sed -n '60,70p' backend/api/routes/knowledge.py; echo ---; sed -n '108,118p' backend/api/routes/knowledge.py`

- [ ] **Step 2: 把 commit 下沉到 service**

```python
# 改前
@router.post("/reindex")
def reindex(session: Session = Depends(get_db_session)):
    job = service.create_reindex_job(...)
    session.commit()  # 删
    return job

# 改后
@router.post("/reindex")
def reindex(session: Session = Depends(get_db_session)):
    return service.create_reindex_job(...)
```

service.create_reindex_job 内部用 session_scope 或 session.flush(若 owns=False 路径)。

- [ ] **Step 3: briefing.py 同理**

- [ ] **Step 4: 跑测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_api_knowledge.py backend/tests/test_api_briefing.py --no-header -q 2>&1 | tail -5`

- [ ] **Step 5: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/api/routes/knowledge.py backend/api/routes/briefing.py
git commit -m "refactor: remove session.commit from API routes; service owns commit"
```

---

### Task 7.2: 修正绕开 `Depends(get_db_session)` 的 2 个路由

**Files:**
- Modify: `backend/api/routes/watchlist.py:444-481`
- Modify: `backend/api/routes/portfolio.py:71-141`

- [ ] **Step 1: 改用 Depends**

```python
# 改前
@router.get("/api/watchlist")
def list_watchlist():
    s = get_session()
    try:
        return watchlist_service.list_watchlist(s)
    finally:
        s.close()

# 改后
@router.get("/api/watchlist")
def list_watchlist(session: Session = Depends(get_db_session)):
    return watchlist_service.list_watchlist(session)
```

- [ ] **Step 2: 跑测试 + commit**

```bash
cd /Users/leon/fund-agent
git add backend/api/routes/watchlist.py backend/api/routes/portfolio.py
git commit -m "refactor: API routes use Depends(get_db_session) instead of manual session"
```

---

### Task 7.3: 删除 market.py 中拿了 session 不传的浪费

**Files:**
- Modify: `backend/api/routes/market.py:73-104`

- [ ] **Step 1: 删除多余的 session 参数**

```python
# 改前
@router.post("/refresh")
def refresh_market(session: Session = Depends(get_db_session)):
    return market_service.refresh_market()  # session 拿了不传

# 改后
@router.post("/refresh")
def refresh_market():
    return market_service.refresh_market()
```

- [ ] **Step 2: 跑测试 + commit**

```bash
cd /Users/leon/fund-agent
git add backend/api/routes/market.py
git commit -m "refactor: drop unused session parameter from market refresh route"
```

---

## Task 8: Scheduler / CLI 顶层事务

### Task 8.1: 验证 scheduler jobs 顶层用 session_scope

**Files:**
- Modify: `backend/scheduler/scheduler.py` (如必要)

- [ ] **Step 1: 读 scheduler 当前形态**

Run: `grep -n "session\|SessionLocal\|session_scope" backend/scheduler/scheduler.py | head -20`

- [ ] **Step 2: 确认所有 job 函数都通过 service 间接管理 session(不应有 scheduler 层直接用 session)**

(spec 4.2: scheduler job 各自创建 Session,经 service 委托)

- [ ] **Step 3: 跑测试 + 不需要 commit(若 scheduler 没改)**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_scheduler.py --no-header -q 2>&1 | tail -5`

---

### Task 8.2: smoke_fetch.py 改用 session_scope

**Files:**
- Modify: `backend/scripts/smoke_fetch.py`

- [ ] **Step 1: 读脚本**

Run: `cat backend/scripts/smoke_fetch.py`

- [ ] **Step 2: 用 session_scope 包整次 demo**

```python
def main(fund_code: str) -> None:
    init_db()
    with session_scope() as s:
        # 所有 service 调用都接收同一个 s
        r = fs.refresh_fund(fund_code)  # 内部 flush
        ...
```

(注:service 已改造为可接收 session;若 service 仍自管 session,保持原样)

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent
git add backend/scripts/smoke_fetch.py
git commit -m "refactor: smoke_fetch.py uses session_scope for atomic demo"
```

---

## Task 9: 最终验证

### Task 9.1: 全量 AST 契约测试

- [ ] **Step 1: 跑所有契约测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/test_transaction_ownership_contract.py --no-header -q 2>&1 | tail -10`

Expected: 全部通过(白名单跳过)

- [ ] **Step 2: 跑所有非 DB 单元测试**

Run: `cd /Users/leon/fund-agent && source .venv/bin/activate && python -m pytest backend/tests/ -k "not real_db and not test_api_funds and not test_api_briefing and not test_api_knowledge and not test_api_market and not test_api_watchlist and not test_api_admin and not test_api_cls and not test_api_portfolio" --no-header -q 2>&1 | tail -10`

Expected: 全通过(或仅 Phase 0 已知失败)

- [ ] **Step 3: 检查无新破窗**

如果出现新失败,逐个修复。

---

### Task 9.2: 写 Phase 1.2 决策文档

**Files:**
- Create: `docs/superpowers/decisions/0002-transaction-ownership.md`

- [ ] **Step 1: 写 ADR**

```markdown
# ADR-002: 统一事务所有权

**状态**: 已实施
**日期**: 2026-07-14
**对应规格**: §4.2

## 决策

- **Repository**: 写函数仅 `session.flush()`,不再内嵌 commit;事务边界由 caller 决定
- **Service**: 函数体内不调用 `commit/rollback/close`;只 flush
- **API 路由**: 写路由通过 `Depends(get_db_session)` 获取 session;不 commit
- **Scheduler / CLI**: 顶层用 `with session_scope() as s:` 显式声明事务
- **保留边界**: 已知多步原子 service(set_initial_holding / confirm_pending_buy / recalc_holding / knowledge_reindex jobs)保留原 commit

## 不变量测试

`backend/tests/test_transaction_ownership_contract.py` 用 AST 静态扫描防止回归。

## 错误处理

- `session_scope()` 上下文退出时 commit on clean / rollback on exception
- service 不再处理 rollback,异常直接向上抛,由顶层 owner 决定
```

- [ ] **Step 2: 提交**

```bash
cd /Users/leon/fund-agent
git add docs/superpowers/decisions/0002-transaction-ownership.md
git commit -m "docs: ADR-002 transaction ownership decisions"
```

---

## 完工

完成 23 个 task 后,Phase 1.2 全部完成。下一阶段可选:

- **Phase 1.3-1.4 收尾**: 已完成(commit 2251d61)
- **Phase 2 模块化**: repository 拆分、service 拆子目录
- **Phase 0 收尾**: fixture 完整化、docker-compose、CI
- **Phase 5.6 前端**: 组件拆分
