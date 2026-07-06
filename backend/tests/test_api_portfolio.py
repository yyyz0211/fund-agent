"""`/api/portfolio/*` 离线测试。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.app import app
from backend.db import repository as repo
from backend.db.init_db import init_db
from backend.db.models import Fund, FundNav

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

    from backend.api.routes import portfolio as portfolio_routes
    monkeypatch.setattr(portfolio_routes, "get_session", lambda: Session())
    # pnl_service 走的是 `from backend.db.session import get_session`,
    # 实际调用时拿到的是 `backend.db.session` 模块的 name。
    from backend.db import session as db_session
    monkeypatch.setattr(db_session, "get_session", lambda: Session())

    yield s
    s.close()


def _seed(s, fund_code, share, cost, current_nav, nav_date="2026-06-30",
          fund_name=None):
    repo.add_to_watchlist_full(
        s, fund_code,
        {"is_holding": True, "holding_share": share, "cost_nav": cost},
    )
    if not s.get(Fund, fund_code):
        s.add(Fund(fund_code=fund_code, fund_name=fund_name or fund_code))
        s.commit()
    s.add(FundNav(
        fund_code=fund_code, nav_date=nav_date,
        accumulated_nav=current_nav, source="akshare",
    ))
    s.commit()


class TestPnlEndpoint:
    def test_empty_portfolio(self, session):
        r = client.get("/api/portfolio/pnl")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["totals"]["count"] == 0

    def test_single_holding(self, session):
        _seed(session, "110011", share=1000, cost=2.0, current_nav=2.5)
        r = client.get("/api/portfolio/pnl")
        assert r.status_code == 200
        body = r.json()
        assert body["totals"]["count"] == 1
        item = body["items"][0]
        assert item["fund_code"] == "110011"
        assert item["pnl_abs"] == 500.0

    def test_codes_filter(self, session):
        _seed(session, "110011", share=1000, cost=2.0, current_nav=2.5)
        _seed(session, "000001", share=500, cost=3.0, current_nav=2.4)
        r = client.get("/api/portfolio/pnl", params={"codes": "110011"})
        body = r.json()
        assert body["totals"]["count"] == 1
        assert body["items"][0]["fund_code"] == "110011"


class TestCompareEndpoint:
    def _seed_history(self, s, code, dates, navs):
        if not s.get(Fund, code):
            s.add(Fund(fund_code=code, fund_name=code))
            s.commit()
        for d, n in zip(dates, navs):
            s.add(FundNav(
                fund_code=code, nav_date=d, accumulated_nav=n, source="akshare",
            ))
        s.commit()

    def test_two_funds_overlap(self, session):
        dates = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
        self._seed_history(session, "110011", dates, [1.0, 1.1, 1.15, 1.2, 1.3])
        self._seed_history(session, "000001", dates, [2.0, 2.1, 2.05, 2.2, 2.3])

        r = client.get(
            "/api/portfolio/compare",
            params={"codes": "110011,000001", "start": "2025-01-01", "end": "2026-06-30"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["start"] == "2025-01-01"
        assert body["end"] == "2026-06-30"
        assert len(body["series"]) == 2
        for s in body["series"]:
            assert len(s["points"]) == 5

    def test_empty_codes(self, session):
        r = client.get("/api/portfolio/compare", params={"codes": ""})
        assert r.status_code == 400

    def test_no_data_in_range(self, session):
        r = client.get(
            "/api/portfolio/compare",
            params={"codes": "110011", "start": "2025-01-01", "end": "2025-02-01"},
        )
        assert r.status_code == 404
        assert "无任何 NAV 数据" in r.json()["detail"]

    def test_invalid_date(self, session):
        r = client.get(
            "/api/portfolio/compare",
            params={"codes": "110011", "start": "not-a-date"},
        )
        assert r.status_code == 400


class TestPnlSeriesEndpoint:
    def _seed_holding_with_history(self, s, code, dates, navs, tx_date, amount):
        repo.add_to_watchlist_full(s, code, {"is_holding": True})
        if not s.get(Fund, code):
            s.add(Fund(fund_code=code, fund_name=code))
            s.commit()
        for d, n in zip(dates, navs):
            s.add(FundNav(fund_code=code, nav_date=d, accumulated_nav=n, source="akshare"))
        s.commit()
        repo.add_transaction(s, code, {"tx_date": tx_date, "amount": amount, "nav": navs[0]})

    def test_empty_portfolio_returns_zero_summary(self, session):
        r = client.get("/api/portfolio/pnl-series")
        assert r.status_code == 200
        body = r.json()
        assert body["dates"] == []
        assert body["summary"]["invested"] == 0.0
        assert body["summary"]["daily_points"] == 0

    def test_single_holding_series(self, session):
        self._seed_holding_with_history(
            session, "110011",
            ["2026-01-01", "2026-01-02"], [1.0, 1.1],
            tx_date="2026-01-01", amount=1000.0,
        )
        r = client.get(
            "/api/portfolio/pnl-series",
            params={"start": "2026-01-01", "end": "2026-01-02"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["dates"][0]["invested"] == 1000.0
        assert body["dates"][0]["market_value"] == 1000.0
        assert body["dates"][1]["market_value"] == 1100.0
        assert body["dates"][1]["pnl"] == 100.0
        assert body["summary"]["invested"] == 1000.0
        assert body["summary"]["market_value"] == 1100.0

    def test_rejects_bad_date(self, session):
        r = client.get("/api/portfolio/pnl-series", params={"start": "bad-date"})
        assert r.status_code == 400
