"""market_intel_service 集成测试。"""
import pytest

from backend.db.models import Briefing  # noqa: F401  注册入 Base.metadata


@pytest.fixture
def in_memory_session():
    """每次测试用独立 in-memory SQLite + 干净 schema。"""
    from backend.db.models import MarketSnapshot  # noqa: F401

    engine = pytest.importorskip("sqlalchemy").create_engine("sqlite:///:memory:", echo=False)
    Base = pytest.importorskip("backend.db.session").Base
    Base.metadata.create_all(engine)
    Session = pytest.importorskip("sqlalchemy.orm").sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_market_snapshot_model_import():
    from backend.db.models import MarketSnapshot
    assert MarketSnapshot.__tablename__ == "market_snapshots"


def test_upsert_market_snapshot_idempotent(in_memory_session):
    from backend.db.models import MarketSnapshot
    from backend.db.repository import upsert_market_snapshot

    payload = {
        "trade_date": "2026-07-07",
        "snapshot_type": "post_market",
        "indices": [{"symbol": "000001", "name": "上证指数", "close": 4094.4, "change_pct": 0.5}],
        "breadth": {"up": 669, "down": 4494, "limit_up": 34, "limit_down": 25},
        "industry_sectors": [{"name": "游戏", "change_pct": 2.39}],
        "concept_sectors": [],
        "industry_flows": [],
        "concept_flows": [],
        "themes": [],
        "breadth_indicators": {},
        "overseas": [],
        "announcements": [],
        "as_of": "2026-07-07",
    }

    row1 = upsert_market_snapshot(in_memory_session, "2026-07-07", "post_market", payload)
    in_memory_session.commit()
    row2 = upsert_market_snapshot(in_memory_session, "2026-07-07", "post_market", payload)
    assert row1.id == row2.id  # idempotent
