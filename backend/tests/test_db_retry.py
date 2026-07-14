"""`backend.services.db_retry.call_with_sqlite_retry` 单元测试。"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from backend.services.db_retry import call_with_sqlite_retry


def _make_locked_error() -> OperationalError:
    """构造一个语义上表示「database is locked」的 OperationalError。

    真实场景下 OperationalError 由 SQLAlchemy 在 `raise ... from orig` 时构造,
    会带 `__cause__` 指向原始的 sqlite3.OperationalError。直接 raise OperationalError
    会被 SQLAlchemy 的异常链机制干扰（generator can't stop after throw）,
    所以用 try/except + raise from 模拟真实链路。
    """
    try:
        raise RuntimeError("database is locked")
    except RuntimeError as orig:
        return OperationalError("INSERT ...", {}, orig)


def _make_other_operational_error() -> OperationalError:
    try:
        raise RuntimeError("no such column")
    except RuntimeError as orig:
        return OperationalError("SELECT ...", {}, orig)


def test_passes_through_on_success():
    """成功路径不重试,直接返回 fn 的结果。"""
    result = call_with_sqlite_retry(lambda: 1 + 1, max_attempts=3, base_delay=0.01)
    assert result == 2


def test_returns_fn_value_on_retry():
    """fn 在某次重试后成功,返回值要返回。"""
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _make_locked_error()
        return "ok"

    result = call_with_sqlite_retry(fn, max_attempts=5, base_delay=0.01)
    assert result == "ok"
    assert attempts["count"] == 3


def test_retries_on_database_locked():
    """`database is locked` 触发指数退避重试,最终成功后退出。"""
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _make_locked_error()

    call_with_sqlite_retry(fn, max_attempts=5, base_delay=0.01)
    assert attempts["count"] == 3


def test_raises_after_max_attempts():
    """耗尽重试次数后重新抛 OperationalError。"""
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        raise _make_locked_error()

    with pytest.raises(OperationalError):
        call_with_sqlite_retry(fn, max_attempts=3, base_delay=0.01)
    assert attempts["count"] == 3


def test_non_locked_operational_error_not_retried():
    """非 locked 的 OperationalError 立即上抛,不浪费重试。"""
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        raise _make_other_operational_error()

    with pytest.raises(OperationalError):
        call_with_sqlite_retry(fn, max_attempts=5, base_delay=0.01)
    assert attempts["count"] == 1


def test_non_operational_error_not_retried():
    """非 OperationalError 立即上抛。"""
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        raise ValueError("boom")

    with pytest.raises(ValueError):
        call_with_sqlite_retry(fn, max_attempts=5, base_delay=0.01)
    assert attempts["count"] == 1


def test_max_attempts_must_be_positive():
    """max_attempts < 1 立即抛 ValueError。"""
    with pytest.raises(ValueError):
        call_with_sqlite_retry(lambda: None, max_attempts=0, base_delay=0.01)


def test_passes_args_and_kwargs():
    """args / kwargs 要透传给 fn。"""
    def fn(a, b, *, c):
        return a + b + c

    result = call_with_sqlite_retry(fn, 1, 2, c=3, max_attempts=1, base_delay=0.01)
    assert result == 6
