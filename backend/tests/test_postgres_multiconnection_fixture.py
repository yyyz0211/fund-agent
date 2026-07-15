"""Real-commit PostgreSQL fixture contract tests."""
from __future__ import annotations

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.db_multiconnection


def test_connection_b_observes_connection_a_commit(db_multiconnection_engine):
    with db_multiconnection_engine.begin() as connection_a:
        connection_a.execute(text(
            "INSERT INTO funds (fund_code, fund_name) VALUES ('multi-visible', 'A')"
        ))

    with db_multiconnection_engine.connect() as connection_b:
        name = connection_b.execute(text(
            "SELECT fund_name FROM funds WHERE fund_code='multi-visible'"
        )).scalar_one()

    assert name == "A"


def test_previous_multiconnection_test_was_truncated(db_multiconnection_engine):
    with db_multiconnection_engine.connect() as connection:
        count = connection.execute(text(
            "SELECT count(*) FROM funds WHERE fund_code='multi-visible'"
        )).scalar_one()

    assert count == 0
