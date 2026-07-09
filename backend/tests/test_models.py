from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

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


def test_init_db_migrates_briefing_unique_constraint_to_date_and_type():
    """旧库只有 UNIQUE(briefing_date) 时,init_db 后应允许同日不同 brief_type。"""
    from backend.db import repository as repo

    engine = make_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                briefing_date VARCHAR,
                title VARCHAR,
                markdown VARCHAR,
                sections_json VARCHAR,
                source VARCHAR,
                as_of VARCHAR,
                data_quality VARCHAR,
                confidence VARCHAR,
                missing_data_json VARCHAR,
                evidence_count INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE(briefing_date)
            )
        """))
        conn.execute(text("""
            INSERT INTO briefings (
                briefing_date, title, markdown, sections_json, source, as_of
            ) VALUES (
                '2026-07-09', '旧盘后', 'old', '{}', 'test', '2026-07-09'
            )
        """))

    init_db(engine)

    session = Session(engine)
    try:
        payload = {"title": "t", "markdown": "m", "sections_json": "{}"}
        repo.upsert_briefing(session, "2026-07-09", payload, brief_type="pre_market")
        repo.upsert_briefing(session, "2026-07-09", payload | {"title": "盘后"}, brief_type="post_market")
        session.commit()

        rows = session.execute(
            text("SELECT briefing_date, brief_type, title FROM briefings ORDER BY brief_type")
        ).all()
    finally:
        session.close()

    assert [row.brief_type for row in rows] == ["post_market", "pre_market"]
