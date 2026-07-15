"""Alembic 在 pytest worker schema 中执行的集成测试。"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.tests.postgres_fixtures import run_alembic_upgrade


pytestmark = pytest.mark.db_ddl


def test_alembic_upgrades_worker_schema(postgres_admin_engine, worker_schema):
    run_alembic_upgrade(postgres_admin_engine, worker_schema)

    with postgres_admin_engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=:schema"
            ),
            {"schema": worker_schema},
        ).scalars().all()

    assert "alembic_version" in tables
    assert "funds" in tables
