from sqlalchemy.orm import sessionmaker

import backend.db.models  # noqa: F401
from backend.db import repository as repo
from backend.db.init_db import init_db
from backend.db.session import make_engine


def test_preload_job_refreshes_data_without_backfilling_peer_category(monkeypatch):
    from backend.services.watchlist import watchlist_preload_jobs as jobs

    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    repo.add_to_watchlist(s, "110011")
    s.close()

    monkeypatch.setattr(jobs, "get_session", lambda: Session())
    monkeypatch.setattr(
        jobs.fs,
        "refresh_fund",
        lambda code: {"fund_code": code, "navs_inserted": 2, "source": "test", "as_of": "2026-07-02"},
    )
    monkeypatch.setattr(
        jobs.profile_service,
        "refresh_profile",
        lambda code: {
            "fund_code": code,
            "profile": {"peer_category": "偏股混合"},
            "missing_data": [],
            "errors": [],
            "source": "test",
            "as_of": "2026-07-02",
        },
    )

    result = jobs.start_preload_job("110011", run_inline=True)

    assert result["status"] == "done"
    s = Session()
    try:
        row = repo.get_watchlist_row(s, "110011")
        assert "peer_category" not in row
        assert row["preload_status"] == "done"
    finally:
        s.close()


def test_preload_job_marks_partial_when_profile_missing_data(monkeypatch):
    from backend.services.watchlist import watchlist_preload_jobs as jobs

    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    repo.add_to_watchlist(s, "110011")
    s.close()

    monkeypatch.setattr(jobs, "get_session", lambda: Session())
    monkeypatch.setattr(
        jobs.fs,
        "refresh_fund",
        lambda code: {"fund_code": code, "navs_inserted": 0, "source": "test", "as_of": "2026-07-02"},
    )
    monkeypatch.setattr(
        jobs.profile_service,
        "refresh_profile",
        lambda code: {
            "fund_code": code,
            "profile": {"peer_category": None},
            "missing_data": ["rank", "peers"],
            "errors": [],
            "source": "test",
            "as_of": "2026-07-02",
        },
    )

    result = jobs.start_preload_job("110011", run_inline=True)

    assert result["status"] == "partial"
    assert "rank" in result["missing_data"]
    assert "peers" in result["missing_data"]
    assert "peer_category" not in result["missing_data"]
    s = Session()
    try:
        row = repo.get_watchlist_row(s, "110011")
        assert "peer_category" not in row
        assert row["preload_status"] == "partial"
    finally:
        s.close()
