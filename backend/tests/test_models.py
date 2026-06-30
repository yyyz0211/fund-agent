from sqlalchemy import inspect

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
