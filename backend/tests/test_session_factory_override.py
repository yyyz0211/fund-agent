"""`set_session_factory` / `reset_session_factory` 接缝单元测试。

不依赖数据库 — 仅验证 ContextVar 行为。
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from backend.db.session import (
    get_session,
    reset_session_factory,
    set_session_factory,
)


def _real_session_sentinel() -> Session:
    """返回进程级 SessionLocal 的 Session,用于确认 reset 真的还原。"""
    from backend.db.session import SessionLocal

    return SessionLocal()


def test_set_session_factory_redirects_get_session():
    """`set_session_factory` 让 `get_session()` 返回工厂的实例。"""
    sentinel = object()
    factory = lambda: sentinel  # noqa: E731 — test sentinel

    token = set_session_factory(factory)
    try:
        assert get_session() is sentinel
    finally:
        reset_session_factory(token)


def test_reset_session_factory_restores_default():
    """`reset_session_factory` 之后 `get_session()` 回到默认 SessionLocal。"""
    sentinel = object()
    token = set_session_factory(lambda: sentinel)
    reset_session_factory(token)
    # 现在拿到的应该不再是 sentinel;在无数据库环境我们只能验证类型
    assert get_session() is not sentinel


def test_factory_override_is_scoped():
    """`set_session_factory` 仅影响当前 ContextVar 上下文。"""
    sentinel_a = object()
    sentinel_b = object()
    token_a = set_session_factory(lambda: sentinel_a)
    try:
        # 嵌套:内层覆盖后,内层 exit 时还原应回到 sentinel_a
        token_b = set_session_factory(lambda: sentinel_b)
        try:
            assert get_session() is sentinel_b
        finally:
            reset_session_factory(token_b)
        assert get_session() is sentinel_a
    finally:
        reset_session_factory(token_a)
    assert get_session() is not sentinel_a


def test_factory_override_does_not_leak_across_threads():
    """`set_session_factory` 不能跨线程隐式继承(避免请求 session 泄漏)。"""
    import threading

    sentinel = object()
    token = set_session_factory(lambda: sentinel)
    try:
        results: dict[str, object] = {}

        def worker():
            # 后台线程必须显式设置 — 这里没设,应该拿不到 sentinel
            try:
                results["session"] = get_session()
            except Exception as exc:
                results["error"] = exc

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=2.0)
        # 后台线程拿到的不应该是 sentinel(可能因为未配置 DATABASE_URL 抛错)
        assert results.get("session") is not sentinel
    finally:
        reset_session_factory(token)


def test_get_session_returns_session_instance_by_default():
    """默认工厂返回真实 `Session` 实例。"""
    # 无 DATABASE_URL 环境也能构造(只是无法连接)
    s = get_session()
    assert isinstance(s, Session)
    s.close()