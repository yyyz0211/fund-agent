"""PostgreSQL connection-bound transaction fixture contract tests."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.db.models import Fund


pytestmark = pytest.mark.db


def test_01_commit_stays_inside_outer_fixture_transaction(db_session):
    db_session.add(Fund(fund_code="fixture-rollback", fund_name="temporary"))
    db_session.commit()

    assert db_session.get(Fund, "fixture-rollback") is not None


def test_02_previous_test_commit_was_rolled_back(db_session):
    assert db_session.scalar(
        select(Fund).where(Fund.fund_code == "fixture-rollback")
    ) is None
