"""fetch_sector_history 的单测。"""
import pandas as pd
import pytest

from backend.services import data_collector as dc


def _fake_sector_df():
    """akshare 同花顺板块接口返回的"涨跌幅"是百分数(0.5 表示 +0.5%)。"""
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2026-06-12", "2026-06-13", "2026-06-16", "2026-06-17", "2026-06-18",
        ]),
        "涨跌幅": [0.5, -0.3, 1.2, 0.8, 2.1],
    })


class _StubAkshareIndustry:
    def __init__(self, df=None, exc=None, capture=None):
        self._df = df
        self._exc = exc
        self._capture = capture

    def stock_board_industry_index_ths(self, symbol: str = "", start_date: str = "", end_date: str = ""):
        if self._capture is not None:
            self._capture.append({"symbol": symbol, "start": start_date, "end": end_date})
        if self._exc is not None:
            raise self._exc
        return self._df


class _StubAkshareConcept:
    def __init__(self, df=None, exc=None):
        self._df = df
        self._exc = exc

    def stock_board_concept_index_ths(self, symbol: str = "", start_date: str = "", end_date: str = ""):
        if self._exc is not None:
            raise self._exc
        return self._df


def test_fetch_industry_history_success(monkeypatch):
    monkeypatch.setattr(dc, "ak", _StubAkshareIndustry(df=_fake_sector_df()))
    result = dc.fetch_sector_history("电子", kind="industry", days=10)
    assert isinstance(result, list)
    assert len(result) == 5
    assert result[0]["date"] == "2026-06-12"
    # 0.5 表示 +0.5% 百分点(akshare 同花顺接口语义)
    assert result[0]["change_pct"] == pytest.approx(0.5)
    assert result[-1]["change_pct"] == pytest.approx(2.1)
    assert result[0]["source"] == dc.SOURCE


def test_fetch_concept_history_truncates_to_days(monkeypatch):
    monkeypatch.setattr(dc, "ak", _StubAkshareConcept(df=_fake_sector_df()))
    result = dc.fetch_sector_history("AI算力", kind="concept", days=3)
    assert len(result) == 3
    assert result[-1]["date"] == "2026-06-18"


def test_fetch_sector_history_returns_error_on_failure(monkeypatch):
    monkeypatch.setattr(dc, "ak", _StubAkshareIndustry(exc=Exception("api down")))
    result = dc.fetch_sector_history("电子", kind="industry", days=10)
    assert isinstance(result, dict)
    assert "error" in result
    assert "api down" in result["error"]


def test_fetch_sector_history_invalid_kind():
    result = dc.fetch_sector_history("X", kind="bad", days=10)
    assert isinstance(result, dict)
    assert "error" in result
    assert "industry|concept" in result["error"]


def test_fetch_sector_history_uses_date_range(monkeypatch):
    """实现必须用 start_date/end_date 参数(而非 period)。"""
    captured: list[dict] = []
    monkeypatch.setattr(dc, "ak", _StubAkshareIndustry(df=_fake_sector_df(), capture=captured))
    dc.fetch_sector_history("电子", kind="industry", days=10)
    assert len(captured) == 1
    call = captured[0]
    assert call["symbol"] == "电子"
    assert len(call["start"]) == 8 and call["start"].isdigit()  # YYYYMMDD
    assert len(call["end"]) == 8 and call["end"].isdigit()
