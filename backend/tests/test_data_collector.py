import pytest
from backend.services import data_collector as dc


def test_with_retry_succeeds_first_try():
    calls = []
    def ok():
        calls.append(1)
        return "ok"
    assert dc.with_retry(ok, sleep=lambda _: None) == "ok"
    assert len(calls) == 1


def test_with_retry_retries_then_succeeds():
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("transient")
        return "ok"
    assert dc.with_retry(flaky, retries=3, sleep=lambda _: None) == "ok"
    assert len(calls) == 3


def test_with_retry_exhausts_and_raises():
    def always_fail():
        raise RuntimeError("nope")
    with pytest.raises(RuntimeError):
        dc.with_retry(always_fail, retries=3, sleep=lambda _: None)


def test_today_str_format():
    s = dc.today_str()
    assert len(s) == 10 and s[4] == "-" and s[7] == "-"