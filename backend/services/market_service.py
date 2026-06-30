"""市场数据领域服务。

目前只有一个操作:刷新主要指数当日行情入本地库。
"""
from backend.db.session import get_session
from backend.db.models import MarketData
from backend.services import data_collector as dc
from sqlalchemy import select


def refresh_market(session=None) -> dict:
    """拉取主要指数当日行情,upsert 到 `market_data` 表。

    去重以 `(symbol, market_date)` 为单位 —— 同一交易日重复调用
    是 no-op。返回 `{inserted, source, as_of}` 或错误字典。
    """
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


def get_indices(session=None) -> dict:
    """从本地库读最新一个交易日的全部指数行。无数据返回可读 error dict。"""
    s = session or get_session()
    owns = session is None
    try:
        latest = s.scalar(select(MarketData.market_date)
                          .order_by(MarketData.market_date.desc()))
        if latest is None:
            return {"error": "本地无市场数据，请先 refresh_market", "source": dc.SOURCE}
        rows = s.scalars(select(MarketData)
                         .where(MarketData.market_date == latest)
                         .order_by(MarketData.symbol)).all()
        indices = [{"symbol": r.symbol, "name": r.name, "close": r.close,
                    "change_pct": r.change_pct, "market_date": r.market_date}
                   for r in rows]
        return {"indices": indices, "source": dc.SOURCE, "as_of": dc.today_str()}
    finally:
        if owns:
            s.close()