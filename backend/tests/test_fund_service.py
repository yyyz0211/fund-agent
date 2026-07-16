import pytest
from threading import Event
from backend.services.fund import fund_service as fs
from backend.services.market import data_collector as dc
from backend.db.repositories import fund as fund_repo
pytestmark = pytest.mark.db


@pytest.fixture()
def session(db_session):
    return db_session


def test_get_latest_nav_no_data(session):
    out = fs.get_latest_nav("110011", session=session)
    assert "error" in out


def test_refresh_then_latest_and_metrics(session, monkeypatch):
    monkeypatch.setattr(dc, "fetch_fund_info", lambda c: {
        "fund_code": c, "fund_name": "FundA", "fund_type": "混合型",
        "manager": "X", "company": "Y", "source": "akshare", "as_of": "2026-06-30"})
    navs = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 11)]
    monkeypatch.setattr(dc, "fetch_fund_nav_history", lambda c: navs)

    r = fs.refresh_fund("110011", session=session)
    assert r["navs_inserted"] == 10

    latest = fs.get_latest_nav("110011", session=session)
    assert latest["accumulated_nav"] == pytest.approx(1.10)
    assert latest["daily_return"] == pytest.approx(0.0)
    assert latest["source"] == "akshare"

    m = fs.get_metrics("110011", period="1w", session=session)
    assert m["max_drawdown"] is not None
    assert m["source"] == "akshare"


def test_get_metrics_invalid_period_returns_error(session, monkeypatch):
    navs = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 4)]
    fund_repo.upsert_navs(session, "110011", navs)

    out = fs.get_metrics("110011", period="bad", session=session)

    assert out["error"] == "unsupported period: bad"
    assert out["source"] == "akshare"


def test_refresh_propagates_collector_error(session, monkeypatch):
    monkeypatch.setattr(dc, "fetch_fund_info", lambda c: {
        "fund_code": c, "source": "akshare", "as_of": "2026-06-30"})
    monkeypatch.setattr(dc, "fetch_fund_nav_history",
                        lambda c: {"error": "boom", "source": "akshare"})
    out = fs.refresh_fund("110011", session=session)
    assert "error" in out
    assert "error" in fs.get_latest_nav("110011", session=session)


def test_refresh_collector_starts_nav_and_info_in_parallel(monkeypatch):
    nav_started = Event()
    info_started = Event()
    navs = [{"nav_date": "2026-06-01", "unit_nav": None,
             "accumulated_nav": 1.0, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}]
    info = {"fund_code": "110011", "fund_name": "FundA", "source": "akshare",
            "as_of": "2026-06-30"}

    def fetch_nav(code):
        nav_started.set()
        assert info_started.wait(1), "fund_info collector did not start in parallel"
        return navs

    def fetch_info(code):
        info_started.set()
        assert nav_started.wait(1), "nav collector did not start in parallel"
        return info

    monkeypatch.setattr(dc, "fetch_fund_nav_history", fetch_nav)
    monkeypatch.setattr(dc, "fetch_fund_info", fetch_info)

    collected_navs, collected_info = fs._collect_refresh_data("110011")

    assert collected_navs == navs
    assert collected_info == info


def test_refresh_continues_when_fund_info_fails(session, monkeypatch):
    """2026-07 行为:fund_info 失败不阻断,NAV 仍然入库并返回。

    场景:雪球蛋卷 API 100% 拒绝时(返回 "版本过低"),仍能从东财
    拉到 NAV 历史。旧行为是 info 失败直接 return,用户连 NAV 都
    拿不到 —— 改后 info 失败只放进 `fund_info_warn` 字段,NAV 写入
    库且返回值 success。
    """
    navs = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 6)]
    monkeypatch.setattr(dc, "fetch_fund_nav_history", lambda c: navs)
    monkeypatch.setattr(dc, "fetch_fund_info",
                        lambda c: {"error": "fetch_fund_info failed for 022084: 'data'",
                                   "source": "akshare"})

    out = fs.refresh_fund("022084", session=session)

    assert "error" not in out
    assert out["navs_inserted"] == 5
    assert out["fund_info_warn"] is not None
    assert "'data'" in out["fund_info_warn"]
    # NAV 已入库
    latest = fs.get_latest_nav("022084", session=session)
    assert latest["accumulated_nav"] == pytest.approx(1.05)


def test_refresh_fund_info_success_has_no_warn(session, monkeypatch):
    """正常情况:fund_info 也成功 → fund_info_warn 字段为 None。"""
    monkeypatch.setattr(dc, "fetch_fund_info", lambda c: {
        "fund_code": c, "fund_name": "FundA", "fund_type": "混合型",
        "manager": "X", "company": "Y", "source": "akshare", "as_of": "2026-06-30"})
    navs = [{"nav_date": "2026-06-01", "unit_nav": None,
             "accumulated_nav": 1.0, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}]
    monkeypatch.setattr(dc, "fetch_fund_nav_history", lambda c: navs)

    out = fs.refresh_fund("110011", session=session)

    assert out["navs_inserted"] == 1
    assert out["fund_info_warn"] is None
    # 基础信息入库
    info = fs.get_basic_info("110011", session=session)
    assert info["fund_name"] == "FundA"


def test_lookup_fund_auto_refreshes_when_nav_missing(session, monkeypatch):
    """本地没有 NAV 时,auto 入口应主动 refresh,再返回可分析数据。"""
    monkeypatch.setattr(dc, "today_str", lambda: "2026-07-07")

    def fake_refresh(code, session=None):
        fund_repo.upsert_fund(session, {
            "fund_code": code,
            "fund_name": "FundA",
            "fund_type": "混合型",
            "manager": "X",
            "company": "Y",
        })
        navs = [
            {"nav_date": f"2026-07-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.01,
             "source": "akshare", "source_updated_at": "2026-07-07"}
            for d in range(1, 8)
        ]
        fund_repo.upsert_navs(session, code, navs)
        return {"fund_code": code, "navs_inserted": 7,
                "source": "akshare", "as_of": "2026-07-07"}

    monkeypatch.setattr(fs, "refresh_fund", fake_refresh)

    out = fs.lookup_fund_auto("110011", period="1w", session=session)

    assert out["refresh"]["attempted"] is True
    assert out["refresh"]["reason"] == "missing_nav"
    assert out["latest_nav"]["nav_date"] == "2026-07-07"
    assert out["fund"]["fund_name"] == "FundA"
    assert out["metrics"]["period"] == "1w"
    assert out["source"] == "akshare"
    assert out["as_of"] == "2026-07-07"


def test_lookup_fund_auto_skips_refresh_when_nav_fresh(session, monkeypatch):
    """本地 NAV 足够新时,auto 入口不应重复联网刷新。"""
    monkeypatch.setattr(dc, "today_str", lambda: "2026-07-07")
    fund_repo.upsert_fund(session, {"fund_code": "110011", "fund_name": "FundA"})
    fund_repo.upsert_navs(session, "110011", [
        {"nav_date": f"2026-07-{d:02d}", "unit_nav": None,
         "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.01,
         "source": "akshare", "source_updated_at": "2026-07-07"}
        for d in range(1, 8)
    ])

    def fail_refresh(code, session=None):  # pragma: no cover - should not run
        raise AssertionError("refresh_fund should not be called for fresh local NAV")

    monkeypatch.setattr(fs, "refresh_fund", fail_refresh)

    out = fs.lookup_fund_auto("110011", period="1w", session=session)

    assert out["refresh"]["attempted"] is False
    assert out["refresh"]["reason"] is None
    assert out["latest_nav"]["nav_date"] == "2026-07-07"


def test_lookup_fund_auto_degrades_when_refresh_fails(session, monkeypatch):
    """主动刷新失败时返回结构化 refresh error,不抛裸异常也不编数据。"""
    monkeypatch.setattr(dc, "today_str", lambda: "2026-07-07")
    monkeypatch.setattr(fs, "refresh_fund", lambda code, session=None: {
        "error": "akshare timeout",
        "source": "akshare",
    })

    out = fs.lookup_fund_auto("110011", period="1w", session=session)

    assert out["refresh"]["attempted"] is True
    assert out["refresh"]["reason"] == "missing_nav"
    assert out["refresh"]["error"] == "akshare timeout"
    assert out["latest_nav"] is None
    assert "latest_nav" in out["errors"]


def test_diagnose_fund_auto_attaches_refresh_metadata(session, monkeypatch):
    """诊断 auto 入口应先走 lookup auto,再把刷新元信息带给调用方。"""
    monkeypatch.setattr(fs, "lookup_fund_auto", lambda code, period="1y",
                        refresh_policy="if_missing_or_stale", stale_days=3,
                        session=None: {
                            "fund_code": code,
                            "refresh": {
                                "attempted": True,
                                "reason": "missing_nav",
                                "result": {"navs_inserted": 5},
                                "error": None,
                            },
                            "errors": {},
                            "as_of": "2026-07-07",
                        })

    from backend.services.shared import diagnosis_service as ds

    monkeypatch.setattr(ds, "diagnose_fund", lambda code, period="1y",
                        session=None: {
                            "fund_code": code,
                            "period": period,
                            "decision_label": "观察",
                            "source": "akshare",
                            "as_of": "2026-07-07",
                        })

    out = fs.diagnose_fund_auto("110011", period="1y", session=session)

    assert out["decision_label"] == "观察"
    assert out["refresh"]["attempted"] is True
    assert out["refresh"]["reason"] == "missing_nav"
    assert out["lookup_as_of"] == "2026-07-07"


def test_get_basic_info_no_data(session):
    assert "error" in fs.get_basic_info("110011", session=session)


def test_get_basic_info_returns_row(session):
    fund_repo.upsert_fund(session, {"fund_code": "110011", "fund_name": "FundA",
                               "fund_type": "混合型", "manager": "X", "company": "Y"})
    out = fs.get_basic_info("110011", session=session)
    assert out["fund_name"] == "FundA"
    assert out["source"] == "akshare"
    assert "as_of" in out


def test_get_nav_history_no_data(session):
    assert "error" in fs.get_nav_history("110011", session=session)


def test_get_nav_history_full_and_range(session):
    rows = [{"nav_date": f"2026-06-{d:02d}", "unit_nav": None,
             "accumulated_nav": 1.0 + d * 0.01, "daily_return": 0.0,
             "source": "akshare", "source_updated_at": "2026-06-30"}
            for d in range(1, 11)]
    fund_repo.upsert_navs(session, "110011", rows)

    full = fs.get_nav_history("110011", session=session)
    assert full["count"] == 10
    assert full["navs"][0]["nav_date"] == "2026-06-01"
    assert "accumulated_nav" in full["navs"][0]
    assert full["source"] == "akshare"

    ranged = fs.get_nav_history("110011", start_date="2026-06-03",
                                end_date="2026-06-05", session=session)
    assert [r["nav_date"] for r in ranged["navs"]] == \
        ["2026-06-03", "2026-06-04", "2026-06-05"]
    assert ranged["count"] == 3
