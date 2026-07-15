"""Alembic 迁移后的 PostgreSQL 核心 schema 回归测试。"""

import pytest
from sqlalchemy import inspect


pytestmark = pytest.mark.db_ddl


def test_core_tables_created(postgres_engine):
    names = set(inspect(postgres_engine).get_table_names())
    assert {"funds", "watchlist", "fund_nav", "market_data", "market_evidence"} <= names


def test_fund_nav_columns_and_unique_constraint(postgres_engine):
    inspector = inspect(postgres_engine)
    columns = {column["name"] for column in inspector.get_columns("fund_nav")}
    assert {
        "fund_code",
        "nav_date",
        "unit_nav",
        "accumulated_nav",
        "daily_return",
        "source",
        "source_updated_at",
    } <= columns
    unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("fund_nav")
    }
    assert ("fund_code", "nav_date") in unique_sets


def test_watchlist_does_not_include_obsolete_peer_category(postgres_engine):
    columns = {
        column["name"] for column in inspect(postgres_engine).get_columns("watchlist")
    }
    assert "peer_category" not in columns


def test_briefing_unique_constraint_is_date_and_type(postgres_engine):
    unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspect(postgres_engine).get_unique_constraints("briefings")
    }
    assert ("briefing_date", "brief_type") in unique_sets
    assert ("briefing_date",) not in unique_sets
