"""watchlist schema migration regression tests."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import init_db
from backend.db.models import Fund, Watchlist
from backend.db.repository import (
    add_to_watchlist_full,
    backfill_watchlist_fund_names,
    get_watchlist,
    update_watchlist,
)


def _fresh_db():
    eng = create_engine("sqlite:///:memory:")
    init_db.init_db(eng)
    return eng


def test_watchlist_has_fund_name_column():
    """watchlist 表必须有 fund_name 列 (Wave 2 加列)。"""
    eng = _fresh_db()
    insp = __import__("sqlalchemy").inspect(eng)
    cols = {c["name"] for c in insp.get_columns("watchlist")}
    assert "fund_name" in cols, f"watchlist 缺 fund_name 列, 现有: {cols}"


def test_add_to_watchlist_can_store_fund_name():
    """add_to_watchlist_full 接受 fund_name 进入白名单并落库。"""
    eng = _fresh_db()
    S = sessionmaker(bind=eng)
    with S() as s:
        row = add_to_watchlist_full(s, "110011", {"fund_name": "易方达蓝筹精选"})
    assert row["fund_name"] == "易方达蓝筹精选"
    assert row["fund_code"] == "110011"


def test_backfill_watchlist_fund_names_only_fills_nulls():
    """回填只更新 fund_name IS NULL 的行, 不覆盖用户手工设置的名字。
    这是 idempotent migration 的标准行为。
    """
    eng = _fresh_db()
    S = sessionmaker(bind=eng)
    with S() as s:
        # 先塞两条 Fund 行
        s.add(Fund(fund_code="000001", fund_name="FundA"))
        s.add(Fund(fund_code="000002", fund_name="FundB"))
        s.commit()
        # 一条 watchlist 已有基金名(手工), 一条没有
        add_to_watchlist_full(s, "000001", {"fund_name": "用户起名"})
        add_to_watchlist_full(s, "000002", {"fund_name": None})
        # 跑回填
        n = backfill_watchlist_fund_names(s)
    assert n == 1, f"应只回填 1 行 (000002), 实际回填 {n}"
    with S() as s:
        rows = get_watchlist(s)
    by_code = {r["fund_code"]: r["fund_name"] for r in rows}
    assert by_code["000001"] == "用户起名", "已手工设置的名不能被覆盖"
    assert by_code["000002"] == "FundB", "NULL 行应从 Fund 表回填"


def test_backfill_is_idempotent():
    """二次回填返回 0 行(已填好的不再动)。"""
    eng = _fresh_db()
    S = sessionmaker(bind=eng)
    with S() as s:
        s.add(Fund(fund_code="000003", fund_name="FundC"))
        s.commit()
        add_to_watchlist_full(s, "000003", {"fund_name": None})
        n1 = backfill_watchlist_fund_names(s)
        n2 = backfill_watchlist_fund_names(s)
    assert n1 == 1
    assert n2 == 0


def test_update_watchlist_can_change_fund_name():
    """PATCH /watchlist 走 update_watchlist 时 fund_name 应可更新。"""
    eng = _fresh_db()
    S = sessionmaker(bind=eng)
    with S() as s:
        add_to_watchlist_full(s, "000004", {"fund_name": "旧名"})
        updated = update_watchlist(s, "000004", {"fund_name": "新名", "note": "abc"})
    assert updated["fund_name"] == "新名"
    assert updated["note"] == "abc"