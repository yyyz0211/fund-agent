"""`postgres_fixtures` 纯函数单元测试(不依赖数据库)。"""
from __future__ import annotations

import pytest

from backend.tests.postgres_fixtures import (
    validate_test_database_url,
    worker_schema_name,
)


class TestValidateTestDatabaseUrl:
    @pytest.mark.parametrize("url", [
        "postgresql+psycopg2://u:p@localhost/fund_agent",
        "sqlite:///:memory:",
        "",
    ])
    def test_rejects_unsafe_test_database_url(self, url):
        """非 PostgreSQL 或非 `_test` 结尾的 URL 必须立即拒绝。"""
        with pytest.raises(pytest.UsageError):
            validate_test_database_url(url)

    def test_accepts_postgres_with_test_suffix(self):
        """合法 PG 测试 URL 通过校验。"""
        url = "postgresql+psycopg2://u:p@localhost:55432/fund_agent_test"
        assert validate_test_database_url(url) == url

    def test_accepts_postgres_asyncpg_driver(self):
        """asyncpg 等其他 PG 驱动也允许。"""
        url = "postgresql+asyncpg://u@localhost/db_test"
        assert validate_test_database_url(url) == url

    def test_rejects_missing_hostname(self):
        with pytest.raises(pytest.UsageError):
            validate_test_database_url("postgresql:///fund_agent_test")


class TestWorkerSchemaName:
    @pytest.mark.parametrize(("worker_id", "expected"), [
        ("master", "test_master"),
        ("gw0", "test_gw0"),
        ("gw12", "test_gw12"),
    ])
    def test_worker_schema_name(self, worker_id, expected):
        assert worker_schema_name(worker_id) == expected

    def test_default_worker_is_master(self):
        """`None` 视为主进程。"""
        assert worker_schema_name(None) == "test_master"

    @pytest.mark.parametrize("worker_id", [
        "../public",
        "gw0;drop schema public",
        "gw0'",
        "",
        "GW0",  # 不允许大写:会让大小写折叠逻辑分裂
        "a" * 33,  # 超过 32
        "gw0 ",
        "gw0.schema",
    ])
    def test_worker_schema_rejects_uncontrolled_names(self, worker_id):
        """任何包含非 `[a-z0-9_]` 字符的 worker_id 拒绝。"""
        with pytest.raises(ValueError):
            worker_schema_name(worker_id)

    def test_worker_schema_accepts_simple_lowercase_word(self):
        """纯小写字母单词是合法的(允许普通测试 fixture name)。"""
        assert worker_schema_name("worker") == "test_worker"

    def test_worker_schema_name_is_safe_to_concatenate(self):
        """`worker_schema_name` 输出可以安全拼到 DDL/SQL 字符串里。"""
        name = worker_schema_name("gw0")
        # 必须只含 `[a-z0-9_]` 和 `test_` 前缀
        assert name.replace("test_", "").replace("_", "").isalnum()
        assert name.startswith("test_")