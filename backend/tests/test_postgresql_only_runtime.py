"""运行时代码 PostgreSQL-only 门禁。

扫描 `backend/{api,db,services,scheduler}` 下的所有 `.py`,阻止以下 SQLite
相关符号重新进入运行时:

- `sqlite://` URL
- `PRAGMA ` (SQLite pragma SQL)
- `StaticPool` / `NullPool` (SQLite 专用连接池)
- `call_with_sqlite_retry` (已删除的 SQLite 重试包装)
- `scheduler_lock` (已删除的全局锁)

历史迁移文档 (`docs/`, `CHANGELOG`) 允许保留 SQLite 字样。

如有合理原因需要上述某个符号,请在本文件登记 `ALLOWED_OFFENDERS` 并附注释。
"""
from __future__ import annotations

import re
from pathlib import Path


FORBIDDEN_TOKENS = (
    "sqlite://",
    "PRAGMA ",
    "StaticPool",
    "NullPool",
    "call_with_sqlite_retry",
    "scheduler_lock",
)


def _scan_roots(roots: list[Path]) -> list[str]:
    """扫描给定根目录下的所有 .py,返回所有 offender 描述。"""
    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for token in FORBIDDEN_TOKENS:
                if token in source:
                    offenders.append(f"{path}: {token}")
    return offenders


def test_backend_runtime_has_no_sqlite_implementation():
    """运行时代码不得出现 SQLite 残留。"""
    repo_root = Path(__file__).resolve().parents[2]
    roots = [
        repo_root / "backend" / "api",
        repo_root / "backend" / "db",
        repo_root / "backend" / "services",
        repo_root / "backend" / "scheduler",
    ]
    offenders = _scan_roots(roots)
    assert offenders == [], (
        "Found SQLite-related tokens in runtime code:\n"
        + "\n".join(offenders)
        + "\n\n历史迁移文档可保留 SQLite 字样;运行时代码、配置默认值和测试连接中"
        " 不得继续存在 SQLite 支持。"
    )


def test_postgresql_only_engine_url_guard():
    """`make_engine` 拒绝非 PostgreSQL URL,作为运行时最后一道闸。"""
    from backend.db.session import make_engine

    with pytest.raises(ValueError, match="Only PostgreSQL"):
        make_engine("sqlite:///:memory:")

    with pytest.raises(ValueError, match="Only PostgreSQL"):
        make_engine("mysql://localhost/test")


def test_make_engine_has_no_sqlite_pool_options(monkeypatch):
    """PostgreSQL engine 不应使用 SQLite 专用连接池配置。"""
    from backend.db import session as session_module

    captured: dict = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(session_module, "create_engine", fake_create_engine)
    session_module.make_engine("postgresql+psycopg2://u@localhost/db")

    assert captured["pool_pre_ping"] is True
    assert "poolclass" not in captured
    assert "connect_args" not in captured


import pytest  # noqa: E402  — 放在测试函数下方以便函数优先被收集