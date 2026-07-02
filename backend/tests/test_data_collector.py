import types

import pandas as pd
import pytest

from backend.services import data_collector as dc


class _FakeAkshare:
    """极简 AKShare 替身,只暴露 `data_collector` 用到的接口。"""

    def __init__(self, info_df: pd.DataFrame, nav_df: pd.DataFrame,
                 unit_df: pd.DataFrame, market_df: pd.DataFrame,
                 ths_df: pd.DataFrame | None = None):
        self._info_df = info_df
        self._nav_df = nav_df
        self._unit_df = unit_df
        self._market_df = market_df
        self._ths_df = ths_df if ths_df is not None else pd.DataFrame()
        self.calls = []

    def fund_individual_basic_info_xq(self, symbol: str) -> pd.DataFrame:
        self.calls.append(("info_xq", symbol))
        return self._info_df

    def fund_info_ths(self, symbol: str) -> pd.DataFrame:
        self.calls.append(("info_ths", symbol))
        return self._ths_df

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


def test_fetch_fund_info_falls_back_to_ths_when_xueqiu_fails(monkeypatch):
    """2026-07:雪球蛋卷 API 拒服时,fetch_fund_info 应 fallback 到
    `ak.fund_info_ths`(同花顺),提取基金简称/投资类型/基金经理/基金管理人。

    这里用 FakeAkshare 让 `fund_individual_basic_info_xq` 抛 KeyError('data')
    模拟雪球拒服,`fund_info_ths` 返回 022084 实测的 18 行 `(字段,值)` 数据。
    `fetch_fund_info` 不再返回 error,而是返回 4 个字段都填好的 dict。
    """

    class _BrokenXq:
        def fund_individual_basic_info_xq(self, symbol: str) -> pd.DataFrame:
            raise KeyError("'data'")  # 模拟雪球"版本过低"异常

        def fund_info_ths(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame({
                "字段": ["基金简称", "投资类型", "基金经理", "基金管理人"],
                "值": ["华安中证有色金属矿业主题ETF发起式联接C",
                       "指数型",
                       "王超,许之彦",
                       "华安基金管理有限公司"],
            })

    monkeypatch.setattr(dc, "ak", _BrokenXq())

    out = dc.fetch_fund_info("022084")
    assert "error" not in out, f"expected success via ths fallback, got {out}"
    assert out["fund_code"] == "022084"
    assert out["fund_name"] == "华安中证有色金属矿业主题ETF发起式联接C"
    assert out["fund_type"] == "指数型"
    assert out["manager"] == "王超,许之彦"
    assert out["company"] == "华安基金管理有限公司"
    assert out["source"] == dc.SOURCE


def test_fetch_fund_info_returns_error_when_both_sources_fail(monkeypatch):
    """两个数据源都失败时,仍按既有契约返回 `{error, source}` —— 上层
    (refresh_fund) 据此把错误放进 `fund_info_warn`,不阻断 NAV 入库。"""
    class _BothBroken:
        def fund_individual_basic_info_xq(self, symbol: str) -> pd.DataFrame:
            raise KeyError("'data'")

        def fund_info_ths(self, symbol: str) -> pd.DataFrame:
            raise RuntimeError("ths timeout")

    monkeypatch.setattr(dc, "ak", _BothBroken())

    out = dc.fetch_fund_info("022084")
    assert "error" in out
    assert "thp" in out["source"] or "akshare" in out["source"]
    assert out["source"] == dc.SOURCE


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


def test_fetch_fund_profile_parses_profile_sources(monkeypatch):
    """画像采集是体检功能的可选增强:多源并行读,局部字段可缺失。

    这里用本地 DataFrame 固定列名,验证 scale、同类候选、持仓集中度、
    行业集中度和经理摘要能被解析到统一 contract。
    """

    class _ProfileAkshare:
        def fund_scale_change_em(self):
            return pd.DataFrame({
                "基金代码": ["110011"],
                "截止日期": ["2026-06-30"],
                "基金规模": [12.3],
            })

        def fund_open_fund_rank_em(self, symbol="全部"):
            return pd.DataFrame({
                "基金代码": ["110011", "000001", "000002"],
                "基金简称": ["目标基金", "PeerA", "PeerB"],
                "基金类型": ["偏股混合", "偏股混合", "偏股混合"],
                "同类排名": [25, 10, 30],
                "同类总数": [100, 100, 100],
            })

        def fund_portfolio_hold_em(self, symbol: str, date: str):
            return pd.DataFrame({
                "股票名称": ["A", "B", "C"],
                "占净值比例": ["20%", "15%", "10%"],
            })

        def fund_portfolio_industry_allocation_em(self, symbol: str, date: str):
            return pd.DataFrame({
                "行业类别": ["消费", "科技"],
                "占净值比例": ["38%", "20%"],
            })

        def fund_manager_em(self):
            return pd.DataFrame({
                "基金代码": ["110011"],
                "基金经理": ["经理A"],
                "任职日期": ["2020-01-01"],
            })

    monkeypatch.setattr(dc, "ak", _ProfileAkshare())
    monkeypatch.setattr(dc, "today_str", lambda: "2026-07-02")

    out = dc.fetch_fund_profile("110011")

    assert out["fund_code"] == "110011"
    assert out["scale"] == pytest.approx(12.3)
    assert out["scale_date"] == "2026-06-30"
    assert out["peer_category"] == "偏股混合"
    assert out["rank_total"] == 100
    assert out["rank_position"] == 25
    assert out["peer_candidates"] == [
        {"fund_code": "000001", "fund_name": "PeerA", "fund_type": "偏股混合", "rank_position": 10},
        {"fund_code": "000002", "fund_name": "PeerB", "fund_type": "偏股混合", "rank_position": 30},
    ]
    assert out["top10_holding_pct"] == pytest.approx(0.45)
    assert out["top_industry_pct"] == pytest.approx(0.38)
    assert out["manager_summary"] == "经理A 任职日期:2020-01-01"
    assert out["missing_data"] == []
    assert out["errors"] == []
    assert out["source"] == dc.SOURCE
    assert out["as_of"] == "2026-07-02"


def test_fetch_fund_profile_degrades_when_source_fails(monkeypatch):
    class _BrokenProfileAkshare:
        def fund_scale_change_em(self):
            raise RuntimeError("scale timeout")

        def fund_open_fund_rank_em(self, symbol="全部"):
            return pd.DataFrame()

        def fund_portfolio_hold_em(self, symbol: str, date: str):
            return pd.DataFrame()

        def fund_portfolio_industry_allocation_em(self, symbol: str, date: str):
            return pd.DataFrame()

        def fund_manager_em(self):
            return pd.DataFrame()

    monkeypatch.setattr(dc, "ak", _BrokenProfileAkshare())

    out = dc.fetch_fund_profile("110011")

    assert out["fund_code"] == "110011"
    assert out["scale"] is None
    assert "scale" in out["missing_data"]
    assert any("scale" in error for error in out["errors"])
