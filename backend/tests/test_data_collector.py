import types

import pandas as pd
import pytest

from backend.services import data_collector as dc


class _FakeAkshare:
    """极简 AKShare 替身,只暴露 `data_collector` 用到的接口。"""

    def __init__(self, info_df: pd.DataFrame, nav_df: pd.DataFrame,
                 unit_df: pd.DataFrame, market_df: pd.DataFrame):
        self._info_df = info_df
        self._nav_df = nav_df
        self._unit_df = unit_df
        self._market_df = market_df
        self.calls = []

    def fund_individual_basic_info_xq(self, symbol: str) -> pd.DataFrame:
        self.calls.append(("info", symbol))
        return self._info_df

    def fund_open_fund_info_em(self, fund: str, indicator: str) -> pd.DataFrame:
        self.calls.append(("nav", fund, indicator))
        if indicator == "单位净值走势":
            return self._unit_df
        return self._nav_df

    def stock_zh_index_spot_em(self) -> pd.DataFrame:
        self.calls.append(("market",))
        return self._market_df


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


def test_fetch_fund_info_parses_xueqiu(monkeypatch):
    """`_FakeAkshare` 模拟雪球真实返回:`item` / `value` 两列,14 行。

    `fetch_fund_info` 应该从中提取 fund_name / fund_type / manager / company,
    其余字段允许 None。
    """
    info_df = pd.DataFrame({
        "item": ["基金代码", "基金名称", "基金类型", "基金经理", "基金公司"],
        "value": ["110011", "易方达优质精选混合(QDII)", "QDII-混合", "张坤 彭珂",
                  "易方达基金管理有限公司"],
    })
    fake = _FakeAkshare(info_df=info_df, nav_df=pd.DataFrame(),
                        unit_df=pd.DataFrame(), market_df=pd.DataFrame())
    monkeypatch.setattr(dc, "ak", fake)

    out = dc.fetch_fund_info("110011")
    assert out["fund_code"] == "110011"
    assert out["fund_name"] == "易方达优质精选混合(QDII)"
    assert out["fund_type"] == "QDII-混合"
    assert out["manager"] == "张坤 彭珂"
    assert out["company"] == "易方达基金管理有限公司"
    assert "error" not in out


def test_fetch_fund_nav_history_joins_unit_and_accumulated(monkeypatch):
    """`fetch_fund_nav_history` 应该同时取单位净值和累计净值并按日期对齐。

    用与 AKShare 一致的列名(`净值日期` / `单位净值` / `累计净值`),
    验证 `unit_nav` 不再是 None,以及 `daily_return` 是从累计净值
    本地算出的(不是来自接口的 `日增长率`)。
    """
    nav_df = pd.DataFrame({
        "净值日期": ["2026-06-01", "2026-06-02", "2026-06-03"],
        "累计净值": [1.00, 1.01, 0.99],
    })
    unit_df = pd.DataFrame({
        "净值日期": ["2026-06-01", "2026-06-02", "2026-06-03"],
        "单位净值": [0.80, 0.81, 0.79],
        "日增长率": ["0.10%", "1.00%", "-1.98%"],
    })
    fake = _FakeAkshare(info_df=pd.DataFrame(), nav_df=nav_df,
                        unit_df=unit_df, market_df=pd.DataFrame())
    monkeypatch.setattr(dc, "ak", fake)

    out = dc.fetch_fund_nav_history("110011")
    assert isinstance(out, list)
    assert len(out) == 3
    assert out[0]["nav_date"] == "2026-06-01"
    assert out[0]["accumulated_nav"] == 1.00
    assert out[0]["unit_nav"] == 0.80
    # 第二行:1.01 / 1.00 - 1 = 0.01(本接口自己算)
    assert out[1]["daily_return"] == pytest.approx(0.01)
    # 第三行:0.99 / 1.01 - 1 ≈ -0.01980198
    assert out[2]["daily_return"] == pytest.approx(0.99 / 1.01 - 1)