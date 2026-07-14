"""PostgreSQL 测试 fixture 工具。

提供三类能力:

1. 纯函数
   - `validate_test_database_url`: 检查 URL 安全(database 必须以 `_test`
     结尾,只接受 postgresql+psycopg2),并强制只读 `TEST_DATABASE_URL`
     环境变量。
   - `worker_schema_name`: 把 pytest-xdist worker_id 映射成受控 schema 名,
     防止 `worker_id` 拼接进 SQL 导致 schema injection。

2. Session-scope fixture(本文件不实现,需要真实 PostgreSQL)
   - `test_database_url`、`worker_schema`、`postgres_engine` 在
     `conftest.py` 中实例化。

3. Function-scope fixture(同上)
   - `db_session`、`db_multiconnection_engine`、`db_ddl_schema`。

注:本文件只放纯函数,具体 fixture 实例化在 `conftest.py`。fixture 实例化
需要在真实 PostgreSQL 上才能验证;纯函数部分可以独立单测。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest


# database 必须以 `_test` 结尾,这是 fixture 唯一的"破坏面"保护。
_TEST_SUFFIX = "_test"

# worker schema 名允许的字符:`test_` 前缀 + 1-32 位 `[a-z0-9_]`。
# 任何其它字符(包括 `;`、`/`、`.`、`%` 等)都不允许,避免 SQL 注入。
_WORKER_SCHEMA_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")


def validate_test_database_url(url: str | None) -> str:
    """校验并规范化测试数据库 URL。

    Args:
        url: 通常是 `os.environ["TEST_DATABASE_URL"]`。

    Returns:
        校验通过的原始 URL。

    Raises:
        pytest.UsageError: URL 不安全时立即失败,不允许测试"侥幸跑通"。
            这是 pytest session 级别的事务 — fixture 越早拒绝,代价越小。
    """
    if not url:
        raise pytest.UsageError(
            "TEST_DATABASE_URL is required. PostgreSQL is the only test database; "
            "SQLite fixtures have been removed.",
        )
    if "://" not in url:
        raise pytest.UsageError(
            f"TEST_DATABASE_URL is not a valid URL: {url!r}",
        )
    parsed = urlparse(url)
    if not parsed.scheme.startswith("postgresql"):
        raise pytest.UsageError(
            f"TEST_DATABASE_URL must use a postgresql driver, got scheme={parsed.scheme!r}. "
            "SQLite and other dialects are not supported in tests.",
        )
    database = parsed.path.lstrip("/")
    if not database.endswith(_TEST_SUFFIX):
        raise pytest.UsageError(
            f"TEST_DATABASE_URL database must end with {_TEST_SUFFIX!r} to be recognized "
            "as a disposable test database; got "
            f"database={database!r}. Refusing to run tests against a non-test database.",
        )
    if not parsed.hostname:
        raise pytest.UsageError(
            f"TEST_DATABASE_URL must include a hostname; got {url!r}",
        )
    return url


def worker_schema_name(worker_id: str | None) -> str:
    """把 pytest-xdist `worker_id` 映射成受控的 PostgreSQL schema 名。

    约定:
    - 主进程 (`worker_id="master"`) → `test_master`
    - xdist worker (`worker_id="gw0"`、`gw1`...) → `test_gw0`、`test_gw1`...

    Args:
        worker_id: pytest 提供的 worker 标识;`None` 视为 `master`。

    Returns:
        形如 `test_<suffix>` 的 schema 名。

    Raises:
        ValueError: `worker_id` 含不允许字符(可能是注入尝试)。
    """
    if worker_id is None:
        suffix = "master"
    elif not _WORKER_SCHEMA_PATTERN.match(worker_id):
        raise ValueError(
            f"worker_id {worker_id!r} contains disallowed characters; "
            "expected alphanumeric/underscore 1-32 chars",
        )
    else:
        suffix = worker_id.lower()
    return f"test_{suffix}"