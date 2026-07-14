import json

import pytest
from sqlalchemy.orm import sessionmaker

import backend.db.models  # noqa: F401
from backend.db.init_db import init_db
from backend.db.session import make_engine
from backend.services.fund import fund_profile_service as fps


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    s = Local()
    yield s
    s.close()


def test_refresh_profile_persists_partial_data(session, monkeypatch):
    monkeypatch.setattr(fps.dc, "fetch_fund_profile", lambda code: {
        "fund_code": code,
        "scale": 12.3,
        "scale_date": "2026-06-30",
        "peer_category": "偏股混合",
        "rank_total": None,
        "rank_position": None,
        "peer_candidates": [{"fund_code": "000001", "fund_name": "PeerA"}],
        "top10_holding_pct": None,
        "top_industry_pct": None,
        "manager_summary": None,
        "missing_data": ["rank", "holdings"],
        "errors": ["rank failed"],
        "source": "akshare",
        "as_of": "2026-07-02",
    })

    out = fps.refresh_profile("110011", session=session)

    assert out["profile"]["scale"] == pytest.approx(12.3)
    assert "rank" in out["missing_data"]
    assert json.loads(out["profile"]["peer_candidates_json"]) == [
        {"fund_code": "000001", "fund_name": "PeerA"},
    ]
    assert json.loads(out["profile"]["raw_errors"]) == ["rank failed"]


def test_get_profile_missing_returns_none(session):
    assert fps.get_profile("999999", session=session) is None


def test_is_profile_fresh_uses_updated_at(session, monkeypatch):
    monkeypatch.setattr(fps.dc, "fetch_fund_profile", lambda code: {
        "fund_code": code,
        "scale": 12.3,
        "scale_date": None,
        "peer_category": None,
        "rank_total": None,
        "rank_position": None,
        "peer_candidates": [],
        "top10_holding_pct": None,
        "top_industry_pct": None,
        "manager_summary": None,
        "missing_data": [],
        "errors": [],
        "source": "akshare",
        "as_of": "2026-07-02",
    })
    fps.refresh_profile("110011", session=session)

    assert fps.is_profile_fresh("110011", ttl_hours=24, session=session) is True
    assert fps.is_profile_fresh("999999", ttl_hours=24, session=session) is False
