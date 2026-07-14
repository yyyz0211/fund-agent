"""fetch_market_breadth 的 staleness 标记单测。"""
import pandas as pd
import pytest

from backend.services.market import data_collector as dc


class _StubAkshare:
    """替换 ak 接口,测试空 df / 缺列 / 全 0 三种 staleness 触发条件。"""

    def __init__(self, df: pd.DataFrame | None, exc: Exception | None = None):
        self._df = df
        self._exc = exc

    def stock_market_activity_legu(self):
        if self._exc is not None:
            raise self._exc
        return self._df


def test_fetch_market_breadth_success_returns_stale_false(monkeypatch):
    df = pd.DataFrame({
        "item": ["上涨", "下跌", "涨停", "跌停", "统计日期"],
        "value": [1500.0, 3000.0, 50.0, 40.0, "2026-07-08 15:00:00"],
    })
    monkeypatch.setattr(dc, "ak", _StubAkshare(df))
    result = dc.fetch_market_breadth()
    assert "error" not in result
    assert result["stale"] is False
    assert result["up"] == 1500
    assert result["down"] == 3000


def test_fetch_market_breadth_empty_df_returns_stale(monkeypatch):
    monkeypatch.setattr(dc, "ak", _StubAkshare(pd.DataFrame()))
    result = dc.fetch_market_breadth()
    assert "error" not in result
    assert result["stale"] is True
    assert result["up"] == 0
    assert result["down"] == 0
    assert result.get("stale_reason") == "empty_dataframe"


def test_fetch_market_breadth_missing_keys_returns_stale(monkeypatch):
    df = pd.DataFrame({"item": ["统计日期"], "value": ["2026-07-08 15:00:00"]})
    monkeypatch.setattr(dc, "ak", _StubAkshare(df))
    result = dc.fetch_market_breadth()
    assert "error" not in result
    assert result["stale"] is True
    assert result["up"] == 0


def test_fetch_market_breadth_zero_total_returns_stale(monkeypatch):
    """数据完整但 up+down=0(可能是周末真没交易,标记 stale)。"""
    df = pd.DataFrame({
        "item": ["上涨", "下跌", "涨停", "跌停"],
        "value": [0.0, 0.0, 0.0, 0.0],
    })
    monkeypatch.setattr(dc, "ak", _StubAkshare(df))
    result = dc.fetch_market_breadth()
    assert result["stale"] is True
    assert result["total"] == 0


def test_fetch_market_breadth_nan_value_returns_stale(monkeypatch):
    """上游 value='abc' 无法 parse → _num 兜底 0 → 触发 staleness。"""
    df = pd.DataFrame({
        "item": ["上涨", "下跌", "涨停", "跌停"],
        "value": ["abc", "xyz", "—", "—"],
    })
    monkeypatch.setattr(dc, "ak", _StubAkshare(df))
    result = dc.fetch_market_breadth()
    assert "error" not in result
    assert result["stale"] is True
    assert result["up"] == 0
    assert result["down"] == 0


def test_fetch_market_breadth_exception_returns_error(monkeypatch):
    monkeypatch.setattr(dc, "ak", _StubAkshare(None, exc=Exception("api offline")))
    result = dc.fetch_market_breadth()
    assert "error" in result
    assert "api offline" in result["error"]
    assert result.get("stale") is True
    assert result.get("stale_reason") == "exception"


def test_empty_breadth_has_stale_flag():
    out = dc._empty_breadth("test")
    assert out["stale"] is True
    assert out["stale_reason"] == "empty_dataframe"
    assert out["as_of"] == dc.today_str()
