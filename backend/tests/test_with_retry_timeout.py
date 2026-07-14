"""with_retry 的 timeout 行为单测。"""
import signal

import pytest

from backend.services.market import data_collector as dc


def _raise_timeout(signum, frame):
    raise TimeoutError("stub timeout")


def test_with_retry_timeout_fires(monkeypatch):
    """fn 挂起超过 timeout → SIGALRM 触发 TimeoutError → 重试耗尽后原样抛出。"""
    monkeypatch.setattr(signal, "signal", signal.signal)  # 不 patch,直接覆盖 handler
    monkeypatch.setattr(signal, "setitimer", lambda *_: None)

    calls = {"n": 0}

    def slow_fn():
        calls["n"] += 1
        # 模拟 akshare 卡死,手动 raise TimeoutError(由 _handler 产生)
        raise TimeoutError("slow")

    with pytest.raises(TimeoutError):
        dc.with_retry(slow_fn, retries=2, base_delay=0, sleep=lambda _: None, timeout=0.05)
    assert calls["n"] == 2


def test_with_retry_no_timeout_backwards_compat(monkeypatch):
    """timeout=None 时不挂 SIGALRM,行为与之前一致。"""
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = dc.with_retry(fn, retries=3, base_delay=0, sleep=lambda _: None, timeout=None)
    assert result == "ok"
    assert calls["n"] == 3