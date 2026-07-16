"""watchlist schema migration regression tests."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect

from backend.db.models import Fund, Watchlist
from backend.db.repositories.watchlist import (
    add_to_watchlist_full,
    backfill_watchlist_fund_names,
    get_watchlist,
    update_watchlist,
)

pytestmark = pytest.mark.db


def test_watchlist_has_fund_name_column(postgres_engine):
    """watchlist 表必须有 fund_name 列 (Wave 2 加列)。"""
    insp = inspect(postgres_engine)
    cols = {c["name"] for c in insp.get_columns("watchlist")}
    assert "fund_name" in cols, f"watchlist 缺 fund_name 列, 现有: {cols}"


def test_add_to_watchlist_can_store_fund_name(db_session):
    """add_to_watchlist_full 接受 fund_name 进入白名单并落库。"""
    row = add_to_watchlist_full(
        db_session, "110011", {"fund_name": "易方达蓝筹精选"}
    )
    assert row["fund_name"] == "易方达蓝筹精选"
    assert row["fund_code"] == "110011"


def test_backfill_watchlist_fund_names_only_fills_nulls(db_session):
    """回填只更新 fund_name IS NULL 的行, 不覆盖用户手工设置的名字。
    这是 idempotent migration 的标准行为。
    """
    # 先塞两条 Fund 行
    db_session.add(Fund(fund_code="000001", fund_name="FundA"))
    db_session.add(Fund(fund_code="000002", fund_name="FundB"))
    db_session.flush()
    # 一条 watchlist 已有基金名(手工), 一条没有
    add_to_watchlist_full(db_session, "000001", {"fund_name": "用户起名"})
    add_to_watchlist_full(db_session, "000002", {"fund_name": None})
    # 跑回填
    n = backfill_watchlist_fund_names(db_session)
    assert n == 1, f"应只回填 1 行 (000002), 实际回填 {n}"
    rows = get_watchlist(db_session)
    by_code = {r["fund_code"]: r["fund_name"] for r in rows}
    assert by_code["000001"] == "用户起名", "已手工设置的名不能被覆盖"
    assert by_code["000002"] == "FundB", "NULL 行应从 Fund 表回填"


def test_backfill_is_idempotent(db_session):
    """二次回填返回 0 行(已填好的不再动)。"""
    db_session.add(Fund(fund_code="000003", fund_name="FundC"))
    db_session.flush()
    add_to_watchlist_full(db_session, "000003", {"fund_name": None})
    n1 = backfill_watchlist_fund_names(db_session)
    n2 = backfill_watchlist_fund_names(db_session)
    assert n1 == 1
    assert n2 == 0


def test_update_watchlist_can_change_fund_name(db_session):
    """PATCH /watchlist 走 update_watchlist 时 fund_name 应可更新。"""
    add_to_watchlist_full(db_session, "000004", {"fund_name": "旧名"})
    updated = update_watchlist(
        db_session, "000004", {"fund_name": "新名", "note": "abc"}
    )
    assert updated["fund_name"] == "新名"
    assert updated["note"] == "abc"
