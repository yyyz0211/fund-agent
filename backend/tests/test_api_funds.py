"""`/api/funds/*` 路由离线测试 —— `POST /refresh` 等增量端点。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.app import app
from backend.db import repository as repo
from backend.db import session as db_session
from backend.db.init_db import init_db
from backend.db.models import Fund, FundNav
from backend.services import fund_service as fs

client = TestClient(app)


@pytest.fixture()
def session(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()

    monkeypatch.setattr(fs, "get_session", lambda: Session())
    monkeypatch.setattr(db_session, "get_session", lambda: Session())

    yield s
    s.close()


def test_refresh_success(monkeypatch):
    """refresh 成功:service 返回正常 dict,端点 200。"""
    monkeypatch.setattr(
        fs, "refresh_fund",
        lambda code, session=None: {
            "fund_code": code, "navs_inserted": 5,
            "already_up_to_date": False,
            "source": "akshare", "as_of": "2026-07-01",
        },
    )
    r = client.post("/api/funds/110011/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "110011"
    assert body["navs_inserted"] == 5
    assert body["already_up_to_date"] is False


def test_refresh_already_up_to_date(monkeypatch):
    """already_up_to_date=True 也返回 200(不是错误)。"""
    monkeypatch.setattr(
        fs, "refresh_fund",
        lambda code, session=None: {
            "fund_code": code, "navs_inserted": 0,
            "already_up_to_date": True,
            "source": "akshare", "as_of": "2026-07-01",
        },
    )
    r = client.post("/api/funds/110011/refresh")
    assert r.status_code == 200
    assert r.json()["already_up_to_date"] is True


def test_refresh_failure_returns_502(monkeypatch):
    """service 返回带 error 的 dict → 502(上游抓取失败)。"""
    monkeypatch.setattr(
        fs, "refresh_fund",
        lambda code, session=None: {"error": "akshare timeout", "source": "akshare"},
    )
    r = client.post("/api/funds/999999/refresh")
    assert r.status_code == 502
    assert "akshare timeout" in r.json()["detail"]


class TestFundSummaryEndpoint:
    def test_nav_endpoint_returns_exact_date_when_date_query_is_set(self, session):
        session.add_all([
            FundNav(fund_code="110011", nav_date="2026-06-01",
                    accumulated_nav=1.0, daily_return=0.0, source="akshare",
                    source_updated_at="2026-06-01"),
            FundNav(fund_code="110011", nav_date="2026-06-30",
                    accumulated_nav=1.2, daily_return=0.01, source="akshare",
                    source_updated_at="2026-06-30"),
        ])
        session.commit()

        r = client.get("/api/funds/110011/nav", params={"date": "2026-06-01"})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["nav_date"] == "2026-06-01"
        assert body["accumulated_nav"] == pytest.approx(1.0)

    def test_nav_endpoint_returns_404_for_missing_exact_date(self, session):
        session.add(FundNav(
            fund_code="110011",
            nav_date="2026-06-30",
            accumulated_nav=1.2,
            source="akshare",
        ))
        session.commit()

        r = client.get("/api/funds/110011/nav", params={"date": "2026-06-01"})

        assert r.status_code == 404
        assert "2026-06-01" in r.json()["detail"]

    def test_nav_endpoint_rejects_invalid_date_query(self, session):
        r = client.get("/api/funds/110011/nav", params={"date": "2026/06/01"})

        assert r.status_code == 400
        assert "invalid date" in r.json()["detail"]

    def test_summary_returns_local_detail_payload(self, session):
        session.add(Fund(
            fund_code="110011",
            fund_name="FundA",
            fund_type="混合型",
            manager="Manager",
            company="Company",
        ))
        session.add_all([
            FundNav(fund_code="110011", nav_date="2026-06-01",
                    accumulated_nav=1.0, daily_return=0.0, source="akshare",
                    source_updated_at="2026-06-01"),
            FundNav(fund_code="110011", nav_date="2026-06-30",
                    accumulated_nav=1.2, daily_return=0.01, source="akshare",
                    source_updated_at="2026-06-30"),
        ])
        session.commit()
        repo.add_to_watchlist_full(session, "110011", {
            "is_holding": True,
            "holding_share": 1000.0,
            "cost_nav": 1.0,
        })

        r = client.get(
            "/api/funds/110011/summary",
            params={"period": "1m", "start": "2026-06-01"},
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["fund"]["fund_name"] == "FundA"
        assert body["latest_nav"]["nav_date"] == "2026-06-30"
        assert body["latest_nav"]["daily_return"] == pytest.approx(0.01)
        assert body["metrics"]["fund_code"] == "110011"
        assert body["nav_history"]["count"] == 2
        assert body["watchlist"]["fund_code"] == "110011"
        assert body["pnl_item"]["fund_code"] == "110011"
        assert body["errors"] == {}

    def test_summary_returns_200_with_local_missing_errors(self, session):
        r = client.get("/api/funds/999999/summary")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["fund"] is None
        assert body["latest_nav"] is None
        assert body["metrics"] is None
        assert body["nav_history"] is None
        assert body["watchlist"] is None
        assert body["pnl_item"] is None
        assert "fund" in body["errors"]
        assert "latest_nav" in body["errors"]

    def test_summary_rejects_invalid_period(self, session):
        r = client.get("/api/funds/110011/summary", params={"period": "bad"})

        assert r.status_code == 400
        assert "unsupported period" in r.json()["detail"]


class TestFundDiagnosisEndpoint:
    def test_diagnosis_endpoint(self, monkeypatch):
        from backend.api.routes import funds as funds_routes

        monkeypatch.setattr(funds_routes.ds, "diagnose_fund", lambda code, period="1y": {
            "fund_code": code,
            "decision_label": "观察",
            "confidence": "medium",
            "summary": "测试结论",
            "reasons": [],
            "risk_lights": [],
            "pitfalls": [],
            "suitable_for": {"fit": [], "avoid": []},
            "peers": [],
            "missing_data": [],
            "source": "akshare",
            "as_of": "2026-07-02",
        })

        r = client.get("/api/funds/110011/diagnosis", params={"period": "1y"})

        assert r.status_code == 200
        assert r.json()["decision_label"] == "观察"

    def test_diagnosis_rejects_bad_period(self):
        r = client.get("/api/funds/110011/diagnosis", params={"period": "bad"})

        assert r.status_code == 400
        assert "unsupported period" in r.json()["detail"]

    def test_peers_rejects_bad_limit(self):
        r = client.get("/api/funds/110011/peers", params={"limit": 0})

        assert r.status_code == 422

    def test_peers_endpoint(self, monkeypatch):
        from backend.api.routes import funds as funds_routes

        monkeypatch.setattr(
            funds_routes.ds,
            "get_peers",
            lambda code, limit=5, period="1y": [{"fund_code": "000001"}],
        )

        r = client.get("/api/funds/110011/peers", params={"limit": 5, "period": "1y"})

        assert r.status_code == 200
        assert r.json() == {"fund_code": "110011", "peers": [{"fund_code": "000001"}]}

    def test_refresh_diagnosis_starts_background_job(self, monkeypatch):
        from backend.api.routes import funds as funds_routes

        calls = []

        def fake_start_refresh_job(code, force=False):
            calls.append((code, force))
            return {
                "job_id": "job-1",
                "fund_code": code,
                "status": "started",
                "started_at": "2026-07-02T12:00:00",
                "finished_at": None,
                "missing_data": [],
                "error": None,
                "as_of": "2026-07-02",
            }

        monkeypatch.setattr(funds_routes.refresh_jobs, "start_refresh_job", fake_start_refresh_job)

        r = client.post("/api/funds/110011/diagnosis/refresh", params={"force": "true"})

        assert r.status_code == 202
        assert r.json()["job_id"] == "job-1"
        assert calls == [("110011", True)]

    def test_refresh_diagnosis_status(self, monkeypatch):
        from backend.api.routes import funds as funds_routes

        monkeypatch.setattr(funds_routes.refresh_jobs, "get_refresh_job", lambda code, job_id: {
            "job_id": job_id,
            "fund_code": code,
            "status": "done",
            "started_at": "2026-07-02T12:00:00",
            "finished_at": "2026-07-02T12:00:03",
            "missing_data": ["manager"],
            "error": None,
            "as_of": "2026-07-02",
        })

        r = client.get("/api/funds/110011/diagnosis/refresh/job-1")

        assert r.status_code == 200
        assert r.json()["status"] == "done"
