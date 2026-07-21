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

import os
import re
from uuid import uuid4
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from backend.db import session as session_module
from backend.db.session import Base, reset_session_factory, set_session_factory


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


def _quoted_identifier(value: str) -> str:
    """Quote a previously validated PostgreSQL identifier."""
    if not re.fullmatch(r"[a-z0-9_]+", value):
        raise ValueError(f"unsafe PostgreSQL identifier: {value!r}")
    return f'"{value}"'


def create_worker_schema_tables(engine) -> None:
    """在 worker schema 中用模型 metadata 建表。

    engine 的 connect 监听器已把 search_path 指向目标 schema，create_all
    因而在该 schema 内建表。pgvector 的 knowledge_embeddings 非模型定义
    （见 init_db.ensure_pgvector_schema），由需要它的测试各自建。
    """
    Base.metadata.create_all(engine)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return validate_test_database_url(os.environ.get("TEST_DATABASE_URL"))


@pytest.fixture(scope="session")
def worker_schema(request) -> str:
    worker_input = getattr(request.config, "workerinput", None) or {}
    return worker_schema_name(worker_input.get("workerid", "master"))


@pytest.fixture(scope="session")
def postgres_admin_engine(test_database_url, worker_schema):
    engine = create_engine(test_database_url, pool_pre_ping=True, future=True)
    quoted_schema = _quoted_identifier(worker_schema)
    with engine.begin() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE"))
        engine.dispose()


@pytest.fixture(scope="session")
def postgres_engine(test_database_url, worker_schema, postgres_admin_engine):
    quoted_schema = _quoted_identifier(worker_schema)
    engine = create_engine(test_database_url, pool_pre_ping=True, future=True)

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET search_path TO {quoted_schema}, public")
        finally:
            cursor.close()

    create_worker_schema_tables(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(postgres_engine, monkeypatch):
    """Connection-bound Session whose writes are rolled back after each test."""
    connection = postgres_engine.connect()
    outer = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    token = set_session_factory(factory)
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    try:
        from backend.api import deps as api_deps

        monkeypatch.setattr(api_deps, "SessionLocal", factory)
    except ImportError:
        pass
    session = factory()
    try:
        yield session
    finally:
        session.close()
        reset_session_factory(token)
        if outer.is_active:
            outer.rollback()
        connection.close()


def _truncate_worker_tables(engine, schema: str) -> None:
    quoted_schema = _quoted_identifier(schema)
    tables = [
        f"{quoted_schema}.{_quoted_identifier(table.name)}"
        for table in reversed(Base.metadata.sorted_tables)
    ]
    if not tables:
        return
    with engine.begin() as connection:
        connection.execute(text(
            f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"
        ))


@pytest.fixture
def db_multiconnection_engine(postgres_engine, worker_schema, monkeypatch):
    """Engine for tests that require independent connections and real commits."""
    _truncate_worker_tables(postgres_engine, worker_schema)
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    try:
        from backend.api import deps as api_deps

        monkeypatch.setattr(api_deps, "SessionLocal", factory)
    except ImportError:
        pass
    try:
        yield postgres_engine
    finally:
        _truncate_worker_tables(postgres_engine, worker_schema)


@pytest.fixture
def db_ddl_schema(test_database_url, postgres_admin_engine, worker_schema):
    """独立、可丢弃的 PostgreSQL schema，供 DDL/迁移测试使用。"""
    schema = f"{worker_schema}_ddl_{uuid4().hex[:12]}"
    quoted_schema = _quoted_identifier(schema)
    with postgres_admin_engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))

    engine = create_engine(test_database_url, pool_pre_ping=True, future=True)

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET search_path TO {quoted_schema}, public")
        finally:
            cursor.close()

    try:
        create_worker_schema_tables(engine)
        yield engine
    finally:
        engine.dispose()
        with postgres_admin_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE"))
