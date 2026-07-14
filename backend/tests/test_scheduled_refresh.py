"""定时批量刷新服务测试。"""
import pytest
from sqlalchemy.orm import sessionmaker

import backend.db.models  # noqa: F401
from backend.db.init_db import init_db
from backend.db.session import make_engine
from backend.services.watchlist import watchlist_service as ws


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_snapshot():
    from backend.services.market import scheduled_refresh as sr
    sr.reset_for_tests()
    yield
    sr.reset_for_tests()


def test_refresh_all_walks_watchlist(monkeypatch, session):
    from backend.services.market import scheduled_refresh as sr

    ws.add("110011", session=session)
    ws.add("000001", session=session)

    calls = []
    monkeypatch.setattr(
        sr.fund_service, "refresh_fund",
        lambda code: calls.append(("fund", code)) or {
            "fund_code": code, "navs_inserted": 1, "already_up_to_date": False,
            "fund_info_warn": None, "source": "akshare", "as_of": "2026-07-06",
        },
    )
    monkeypatch.setattr(
        sr.profile_service, "refresh_profile",
        lambda code: calls.append(("profile", code)) or {
            "profile": {}, "missing_data": [], "errors": [],
        },
    )

    snap = sr.refresh_all_watchlist(trigger="manual", session=session)
    assert snap["total"] == 2
    assert snap["succeeded"] == 2
    assert snap["failed"] == 0
    assert {c for _, c in calls} == {"110011", "000001"}


def test_refresh_all_counts_already_up_to_date(monkeypatch, session):
    from backend.services.market import scheduled_refresh as sr

    ws.add("110011", session=session)

    monkeypatch.setattr(
        sr.fund_service, "refresh_fund",
        lambda code: {
            "fund_code": code, "navs_inserted": 0, "already_up_to_date": True,
            "fund_info_warn": None, "source": "akshare", "as_of": "2026-07-06",
        },
    )
    monkeypatch.setattr(
        sr.profile_service, "refresh_profile",
        lambda code: {"profile": {}, "missing_data": [], "errors": []},
    )

    snap = sr.refresh_all_watchlist(trigger="scheduled", session=session)
    assert snap["succeeded"] == 1
    assert snap["already_up_to_date"] == 1


def test_refresh_all_records_failures_but_continues(monkeypatch, session):
    from backend.services.market import scheduled_refresh as sr

    ws.add("110011", session=session)
    ws.add("000001", session=session)

    def fake_refresh(code):
        if code == "110011":
            return {"error": "akshare timeout", "source": "akshare"}
        return {
            "fund_code": code, "navs_inserted": 1, "already_up_to_date": False,
            "fund_info_warn": None, "source": "akshare", "as_of": "2026-07-06",
        }

    monkeypatch.setattr(sr.fund_service, "refresh_fund", fake_refresh)
    monkeypatch.setattr(
        sr.profile_service, "refresh_profile",
        lambda code: {"profile": {}, "missing_data": [], "errors": []},
    )

    snap = sr.refresh_all_watchlist(trigger="manual", session=session)
    assert snap["succeeded"] == 1
    assert snap["failed"] == 1
    assert snap["failures"][0]["fund_code"] == "110011"
    assert "akshare timeout" in snap["failures"][0]["error"]


def test_refresh_all_survives_refresh_exception(monkeypatch, session):
    from backend.services.market import scheduled_refresh as sr

    ws.add("110011", session=session)

    def boom(code):
        raise RuntimeError("network down")

    monkeypatch.setattr(sr.fund_service, "refresh_fund", boom)
    monkeypatch.setattr(
        sr.profile_service, "refresh_profile",
        lambda code: {"profile": {}, "missing_data": [], "errors": []},
    )

    snap = sr.refresh_all_watchlist(trigger="manual", session=session)
    assert snap["failed"] == 1
    assert "network down" in snap["failures"][0]["error"]


def test_profile_failure_is_soft(monkeypatch, session):
    from backend.services.market import scheduled_refresh as sr

    ws.add("110011", session=session)

    monkeypatch.setattr(
        sr.fund_service, "refresh_fund",
        lambda code: {
            "fund_code": code, "navs_inserted": 1, "already_up_to_date": False,
            "fund_info_warn": None, "source": "akshare", "as_of": "2026-07-06",
        },
    )

    def boom(code):
        raise RuntimeError("profile source down")

    monkeypatch.setattr(sr.profile_service, "refresh_profile", boom)

    snap = sr.refresh_all_watchlist(trigger="manual", session=session)
    # NAV 成功,所以即便画像失败该行仍算成功。
    assert snap["succeeded"] == 1
    assert snap["failed"] == 0


def test_get_last_run_empty_default():
    from backend.services.market import scheduled_refresh as sr

    sr.reset_for_tests()
    snap = sr.get_last_run()
    assert snap["last_run_at"] is None
    assert snap["total"] == 0
    assert snap["failures"] == []


def test_get_last_run_returns_snapshot(monkeypatch, session):
    from backend.services.market import scheduled_refresh as sr

    ws.add("110011", session=session)
    monkeypatch.setattr(
        sr.fund_service, "refresh_fund",
        lambda code: {
            "fund_code": code, "navs_inserted": 1, "already_up_to_date": False,
            "fund_info_warn": None, "source": "akshare", "as_of": "2026-07-06",
        },
    )
    monkeypatch.setattr(
        sr.profile_service, "refresh_profile",
        lambda code: {"profile": {}, "missing_data": [], "errors": []},
    )

    sr.refresh_all_watchlist(trigger="manual", session=session)
    snap = sr.get_last_run()
    assert snap["last_run_at"] is not None
    assert snap["trigger"] == "manual"
    assert snap["total"] == 1


def test_start_refresh_all_async_single_flight(monkeypatch):
    from backend.services.market import scheduled_refresh as sr

    monkeypatch.setattr(sr.watchlist_service, "list_watchlist", lambda: [])

    # 阻塞后台任务,让 active 标记在两次调用之间保持置位。
    import threading
    gate = threading.Event()
    monkeypatch.setattr(sr, "refresh_all_watchlist",
                        lambda *, trigger="scheduled": gate.wait(2))

    first = sr.start_refresh_all_async(trigger="manual")
    second = sr.start_refresh_all_async(trigger="manual")
    gate.set()

    assert first["status"] == "started"
    assert second["status"] == "running"
