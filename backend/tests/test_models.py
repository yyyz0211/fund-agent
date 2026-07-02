from sqlalchemy import inspect, text

from backend.db.session import Base, make_engine
from backend.db.init_db import init_db
import backend.db.models  # noqa: F401  (register models on Base)


def test_tables_created():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    names = set(inspect(engine).get_table_names())
    assert {"funds", "watchlist", "fund_nav", "market_data"} <= names


def test_fund_nav_unique_constraint():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("fund_nav")}
    assert {"fund_code", "nav_date", "unit_nav", "accumulated_nav",
            "daily_return", "source", "source_updated_at"} <= cols


def test_watchlist_does_not_include_peer_category():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("watchlist")}
    assert "peer_category" not in cols


def test_init_db_drops_obsolete_watchlist_peer_category():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE watchlist ADD COLUMN peer_category VARCHAR"))
    assert "peer_category" in {c["name"] for c in inspect(engine).get_columns("watchlist")}

    init_db(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("watchlist")}
    assert "peer_category" not in cols
