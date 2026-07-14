"""fetch_index_history 的单测,mock akshare 避免外网依赖。

使用 monkeypatch 替换 `dc.ak` 上的方法,不依赖真实 akshare 网络/库。
"""
from unittest.mock import patch
import pandas as pd
import pytest

from backend.services.market import data_collector as dc


def _fake_daily_df():
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19",
        ]),
        "close": [3000.0, 3010.5, 3005.2, 3020.0, 3030.0],
    })


class _StubAkshare:
    """只暴露本测试需要的 stock_zh_index_daily 方法。"""

    def __init__(self, df=None, exc=None, capture=None):
        self._df = df
        self._exc = exc
        self._capture = capture

    def stock_zh_index_daily(self, symbol: str = ""):
        if self._capture is not None:
            self._capture.append(symbol)
        if self._exc is not None:
            raise self._exc
        return self._df


def test_fetch_index_history_success(monkeypatch):
    monkeypatch.setattr(dc, "ak", _StubAkshare(df=_fake_daily_df()))
    result = dc.fetch_index_history("000300", days=5)
    assert isinstance(result, list)
    assert len(result) == 5
    assert result[0]["date"] == "2026-06-15"
    assert result[-1]["close"] == 3030.0
    assert result[0]["source"] == dc.SOURCE


def test_fetch_index_history_truncates_to_days(monkeypatch):
    monkeypatch.setattr(dc, "ak", _StubAkshare(df=_fake_daily_df()))
    result = dc.fetch_index_history("000300", days=3)
    assert len(result) == 3
    assert result[-1]["date"] == "2026-06-19"


def test_fetch_index_history_returns_error_on_failure(monkeypatch):
    monkeypatch.setattr(dc, "ak", _StubAkshare(exc=Exception("network down")))
    result = dc.fetch_index_history("000300", days=10)
    assert isinstance(result, dict)
    assert "error" in result
    assert "network down" in result["error"]


def test_fetch_index_history_empty_df_returns_error(monkeypatch):
    empty_df = pd.DataFrame({"date": pd.to_datetime([]), "close": []})
    monkeypatch.setattr(dc, "ak", _StubAkshare(df=empty_df))
    result = dc.fetch_index_history("000300", days=10)
    assert isinstance(result, dict)
    assert "error" in result


def test_fetch_index_history_missing_close_column_returns_error(monkeypatch):
    df = pd.DataFrame({"date": pd.to_datetime(["2026-06-15"]), "open": [1.0]})
    monkeypatch.setattr(dc, "ak", _StubAkshare(df=df))
    result = dc.fetch_index_history("000300", days=10)
    assert isinstance(result, dict)
    assert "error" in result
    assert "cols miss" in result["error"]


def test_fetch_index_history_normalizes_symbol_prefix(monkeypatch):
    """symbol 6 位代码应自动加 sh/sz 前缀传给 akshare。"""
    captured: list[str] = []
    monkeypatch.setattr(dc, "ak", _StubAkshare(df=_fake_daily_df(), capture=captured))
    dc.fetch_index_history("000001", days=5)
    assert captured[0] == "sh000001"
    captured.clear()
    dc.fetch_index_history("399001", days=5)
    assert captured[0] == "sz399001"


def test_fetch_index_history_passes_through_prefixed_symbol(monkeypatch):
    """已带前缀的 symbol 不应重复加前缀。"""
    captured: list[str] = []
    monkeypatch.setattr(dc, "ak", _StubAkshare(df=_fake_daily_df(), capture=captured))
    dc.fetch_index_history("sh000001", days=5)
    assert captured[0] == "sh000001"
