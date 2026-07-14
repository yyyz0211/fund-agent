"""session_scope() 顶层事务上下文管理器测试(spec 4.2)。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.session = MagicMock()
        self.session.commit = MagicMock(side_effect=self._on_commit)
        self.session.rollback = MagicMock(side_effect=self._on_rollback)
        self.session.close = MagicMock(side_effect=self._on_close)

    def _on_commit(self) -> None:
        self.committed = True

    def _on_rollback(self) -> None:
        self.rolled_back = True

    def _on_close(self) -> None:
        self.closed = True

    def __call__(self) -> MagicMock:
        return self.session


def test_commit_on_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.db import session as session_module

    factory = _FakeSessionFactory()
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    from backend.db.session_scope import session_scope

    with session_scope() as s:
        assert s is factory.session
    assert factory.committed
    assert not factory.rolled_back
    assert factory.closed


def test_rollback_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.db import session as session_module

    factory = _FakeSessionFactory()
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    from backend.db.session_scope import session_scope

    with pytest.raises(RuntimeError, match="boom"):
        with session_scope():
            raise RuntimeError("boom")
    assert factory.rolled_back
    assert not factory.committed
    assert factory.closed


def test_close_always_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.db import session as session_module

    factory = _FakeSessionFactory()
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    from backend.db.session_scope import session_scope

    with session_scope():
        pass
    assert factory.closed