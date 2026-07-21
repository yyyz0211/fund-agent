"""PostgreSQL 独立 DDL schema fixture 回归测试。"""

import pytest
from sqlalchemy import inspect, text


pytestmark = pytest.mark.db_ddl


def test_ddl_schema_is_created_and_isolated(db_ddl_schema):
    tables = set(inspect(db_ddl_schema).get_table_names())
    assert {"funds", "watchlist"} <= tables

    with db_ddl_schema.begin() as connection:
        connection.execute(text("CREATE TABLE fixture_probe (id integer primary key)"))

    assert "fixture_probe" in inspect(db_ddl_schema).get_table_names()
