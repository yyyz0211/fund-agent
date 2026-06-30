from backend.db.session import get_session
from backend.db.models import MarketData
from backend.services import data_collector as dc
from sqlalchemy import select


def refresh_market(session=None) -> dict:
    s = session or get_session()
    owns = session is None
    try:
        rows = dc.fetch_market_indices()
        if isinstance(rows, dict) and "error" in rows:
            return rows
        existing = {(r.symbol, r.market_date) for r in
                    s.scalars(select(MarketData)).all()}
        inserted = 0
        for r in rows:
            if (r["symbol"], r["market_date"]) in existing:
                continue
            s.add(MarketData(**r))
            inserted += 1
        s.commit()
        return {"inserted": inserted, "source": dc.SOURCE, "as_of": dc.today_str()}
    finally:
        if owns:
            s.close()
