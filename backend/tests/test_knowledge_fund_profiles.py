from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.db.models import Fund, FundProfile, FundWatchlistProfile, Watchlist
from backend.services.knowledge.knowledge_fund_profile_service import (
    infer_theme_tags,
    refresh_fund_watchlist_profiles,
)


def test_infer_theme_tags_from_fund_name_and_peer_category():
    tags, basis = infer_theme_tags(
        "人工智能主题混合",
        "混合型",
        "科技成长",
        None,
    )

    assert "人工智能" in tags
    assert "科技成长" in tags
    assert "fund_name" in basis
    assert "peer_category" in basis


@pytest.mark.db
def test_refresh_profiles_uses_holding_weight(db_session):
    s = db_session
    s.add_all([
            Fund(fund_code="000001", fund_name="人工智能主题混合", fund_type="混合型"),
            FundProfile(fund_code="000001", peer_category="科技成长"),
            Watchlist(
                fund_code="000001",
                fund_name="人工智能主题混合",
                is_holding=True,
                holding_amount=3000.0,
            ),
            Fund(fund_code="000002", fund_name="消费主题混合", fund_type="混合型"),
            Watchlist(
                fund_code="000002",
                fund_name="消费主题混合",
                is_holding=True,
                holding_amount=1000.0,
            ),
    ])
    s.commit()

    result = refresh_fund_watchlist_profiles(session=s)

    assert result["profiles_written"] == 2
    profile = s.scalar(select(FundWatchlistProfile).where(
        FundWatchlistProfile.fund_code == "000001"
    ))
    assert profile.priority == "holding"
    assert profile.holding_weight == 0.75


@pytest.mark.db
def test_refresh_profiles_deletes_funds_removed_from_watchlist(db_session):
    s = db_session
    s.add(Watchlist(fund_code="000001", fund_name="人工智能主题混合"))
    s.add(FundWatchlistProfile(
            fund_code="000001",
            fund_name="人工智能主题混合",
            priority="watching",
            profile_status="ready",
        ))
    s.add(FundWatchlistProfile(
            fund_code="000002",
            fund_name="已移除基金",
            priority="watching",
            profile_status="ready",
        ))
    s.commit()

    result = refresh_fund_watchlist_profiles(session=s)

    assert result["profiles_deleted"] == 1
    assert s.get(FundWatchlistProfile, "000002") is None
