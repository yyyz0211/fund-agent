from __future__ import annotations

import pytest

from backend.api import deps


class FakeSession:
    def __init__(self):
        self.rollback_calls = 0
        self.close_calls = 0

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.close_calls += 1


def test_get_db_session_closes_after_success(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(deps, "SessionLocal", lambda: session)

    dependency = deps.get_db_session()
    assert next(dependency) is session
    with pytest.raises(StopIteration):
        next(dependency)

    assert session.rollback_calls == 0
    assert session.close_calls == 1


def test_get_db_session_rolls_back_and_closes_after_error(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(deps, "SessionLocal", lambda: session)

    dependency = deps.get_db_session()
    assert next(dependency) is session
    with pytest.raises(RuntimeError, match="boom"):
        dependency.throw(RuntimeError("boom"))

    assert session.rollback_calls == 1
    assert session.close_calls == 1
