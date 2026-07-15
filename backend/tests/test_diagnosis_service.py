import json

import pytest

import backend.db.models  # noqa: F401
from backend.db import repository as repo

pytestmark = pytest.mark.db


@pytest.fixture()
def session(db_session):
    return db_session


def test_diagnosis_with_core_data_returns_structured_payload(session, monkeypatch):
    from backend.services.shared import diagnosis_service as ds

    monkeypatch.setattr(ds.fs, "get_summary", lambda code, period="1y", start_date="", session=None: {
        "fund_code": code,
        "fund": {"fund_code": code, "fund_name": "FundA", "fund_type": "偏股混合",
                 "source": "akshare", "as_of": "2026-07-02"},
        "latest_nav": {"fund_code": code, "nav_date": "2026-06-30", "source": "akshare",
                       "as_of": "2026-06-30"},
        "metrics": {"fund_code": code, "period": period, "period_return": 0.05,
                    "max_drawdown": -0.18, "volatility": 0.16,
                    "source": "akshare", "as_of": "2026-07-02"},
        "nav_history": {"fund_code": code, "navs": [], "count": 0,
                        "source": "akshare", "as_of": "2026-07-02"},
        "watchlist": None,
        "pnl_item": None,
        "pnl_skipped": None,
        "errors": {},
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    monkeypatch.setattr(ds.profile_service, "get_profile", lambda code, session=None: None)
    monkeypatch.setattr(ds, "get_peers", lambda code, limit=5, period="1y", session=None: [])

    out = ds.diagnose_fund("110011", period="1y", session=session)

    assert out["fund_code"] == "110011"
    assert out["decision_label"] in {"观察", "小仓试验", "候选", "暂不碰"}
    assert out["confidence"] in {"low", "medium", "high"}
    assert len(out["reasons"]) <= 3
    assert out["risk_lights"]
    assert "scale" in out["missing_data"]


def test_diagnosis_missing_core_data_is_low_confidence_block(session, monkeypatch):
    from backend.services.shared import diagnosis_service as ds

    monkeypatch.setattr(ds.fs, "get_summary", lambda code, period="1y", start_date="", session=None: {
        "fund_code": code,
        "fund": None,
        "latest_nav": None,
        "metrics": None,
        "nav_history": None,
        "watchlist": None,
        "pnl_item": None,
        "pnl_skipped": None,
        "errors": {"latest_nav": "no nav", "metrics": "no metrics"},
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    monkeypatch.setattr(ds.profile_service, "get_profile", lambda code, session=None: None)
    monkeypatch.setattr(ds, "get_peers", lambda code, limit=5, period="1y", session=None: [])

    out = ds.diagnose_fund("110011", period="1y", session=session)

    assert out["decision_label"] == "暂不碰"
    assert out["confidence"] == "low"
    assert "latest_nav" in out["missing_data"]
    assert "metrics" in out["missing_data"]


def test_diagnosis_uses_basic_manager_when_profile_manager_missing(session, monkeypatch):
    from backend.services.shared import diagnosis_service as ds

    monkeypatch.setattr(ds.fs, "get_summary", lambda code, period="1y", start_date="", session=None: {
        "fund_code": code,
        "fund": {"fund_code": code, "fund_name": "FundA", "fund_type": "偏股混合",
                 "manager": "Manager A", "source": "akshare", "as_of": "2026-07-02"},
        "latest_nav": {"fund_code": code, "nav_date": "2026-06-30", "source": "akshare",
                       "as_of": "2026-06-30"},
        "metrics": {"fund_code": code, "period": period, "period_return": 0.05,
                    "max_drawdown": -0.08, "volatility": 0.10,
                    "source": "akshare", "as_of": "2026-07-02"},
        "errors": {},
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    monkeypatch.setattr(ds.profile_service, "get_profile", lambda code, session=None: {
        "scale": 10.0,
        "rank_total": 100,
        "rank_position": 20,
        "peer_candidates_json": "[]",
        "top10_holding_pct": 0.2,
        "top_industry_pct": 0.2,
        "manager_summary": None,
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    monkeypatch.setattr(ds, "get_peers", lambda code, limit=5, period="1y", session=None: [])

    out = ds.diagnose_fund("110011", period="1y", session=session)

    assert "manager" not in out["missing_data"]


def test_get_peers_returns_candidates_without_local_nav(session):
    from backend.services.shared import diagnosis_service as ds

    repo.upsert_fund_profile(session, "110011", {
        "peer_candidates_json": json.dumps([
            {"fund_code": "000001", "fund_name": "PeerA", "fund_type": "偏股混合"},
            {"fund_code": "000002", "fund_name": "PeerB", "fund_type": "偏股混合"},
        ], ensure_ascii=False),
    })
    repo.upsert_fund_profile(session, "000001", {"scale": 20.0})
    navs = [
        {"nav_date": f"2026-06-{day:02d}", "unit_nav": None,
         "accumulated_nav": 1 + day * 0.01, "daily_return": 0.0,
         "source": "akshare", "source_updated_at": "2026-07-02"}
        for day in range(1, 8)
    ]
    repo.upsert_navs(session, "000001", navs)

    peers = ds.get_peers("110011", limit=5, period="1w", session=session)

    assert [peer["fund_code"] for peer in peers] == ["000001", "000002"]
    assert peers[0]["period_return"] is not None
    assert peers[0]["max_drawdown"] is not None
    assert peers[0]["volatility"] is not None
    assert peers[0]["scale"] == pytest.approx(20.0)
    assert peers[0]["has_local_nav"] is True
    assert peers[1]["period_return"] is None
    assert peers[1]["max_drawdown"] is None
    assert peers[1]["volatility"] is None
    assert peers[1]["scale"] is None
    assert peers[1]["has_local_nav"] is False


def test_diagnosis_marks_peer_metrics_not_peers_when_candidates_exist(session, monkeypatch):
    from backend.services.shared import diagnosis_service as ds

    monkeypatch.setattr(ds.fs, "get_summary", lambda code, period="1y", start_date="", session=None: {
        "fund_code": code,
        "fund": {"fund_code": code, "fund_name": "FundA", "fund_type": "偏股混合",
                 "manager": "Manager A", "source": "akshare", "as_of": "2026-07-02"},
        "latest_nav": {"fund_code": code, "nav_date": "2026-06-30", "source": "akshare",
                       "as_of": "2026-06-30"},
        "metrics": {"fund_code": code, "period": period, "period_return": 0.05,
                    "max_drawdown": -0.08, "volatility": 0.10,
                    "source": "akshare", "as_of": "2026-07-02"},
        "errors": {},
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    monkeypatch.setattr(ds.profile_service, "get_profile", lambda code, session=None: {
        "scale": 10.0,
        "rank_total": 100,
        "rank_position": 20,
        "peer_candidates_json": json.dumps([{"fund_code": "000001", "fund_name": "PeerA"}]),
        "top10_holding_pct": 0.2,
        "top_industry_pct": 0.2,
        "manager_summary": None,
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    monkeypatch.setattr(ds, "get_peers", lambda code, limit=5, period="1y", session=None: [{
        "fund_code": "000001",
        "fund_name": "PeerA",
        "fund_type": "偏股混合",
        "period_return": None,
        "max_drawdown": None,
        "volatility": None,
        "scale": None,
        "has_local_nav": False,
    }])

    out = ds.diagnose_fund("110011", period="1y", session=session)

    assert "peers" not in out["missing_data"]
    assert "peer_metrics" in out["missing_data"]


def test_get_peers_does_not_call_akshare(session, monkeypatch):
    from backend.services.market import data_collector as dc
    from backend.services.shared import diagnosis_service as ds

    def fail_if_called(_code):
        raise AssertionError("GET peers must not call AkShare")

    monkeypatch.setattr(dc, "fetch_fund_profile", fail_if_called)

    assert ds.get_peers("110011", limit=5, period="1w", session=session) == []
