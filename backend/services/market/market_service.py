"""市场数据领域服务。

目前只有一个操作:刷新主要指数当日行情入本地库。

写入路径分两段:`_fetch_market_rows` 完成 akshare 网络拉取,refresh_market 在
`session_scope()` 短事务里完成去重 + upsert,避免等待 akshare 时持有事务。
读取接口 `get_indices` 沿用 `session=None` 时自行 `session_scope()` 的模式,
以保持与 fund_service 等其他子域一致的接口契约。
"""
from sqlalchemy import select

from backend.db.models import MarketData
from backend.db.session_scope import session_scope
from backend.services.market import data_collector as dc


def _fetch_market_rows() -> dict | list:
    """拉取当日主要指数行情。无 DB 调用,可在事务外执行。

    返回 dc.fetch_market_indices 的原始结果(dict 含 error 或 list[dict])。
    """
    return dc.fetch_market_indices()


def refresh_market() -> dict:
    """拉取主要指数当日行情,upsert 到 `market_data` 表。

    去重以 `(symbol, market_date)` 为单位 —— 同一交易日重复调用
    是 no-op。返回 `{inserted, source, as_of}` 或错误字典。

    事务边界:先完成所有网络拉取(无事务),再开 `session_scope()`
    短事务完成去重 + 写库,避免等待 akshare 时长事务持有锁。
    """
    rows = _fetch_market_rows()
    if isinstance(rows, dict) and "error" in rows:
        return rows

    with session_scope() as s:
        existing = {(r.symbol, r.market_date) for r in
                    s.scalars(select(MarketData)).all()}
        inserted = 0
        for r in rows:
            if (r["symbol"], r["market_date"]) in existing:
                continue
            s.add(MarketData(**r))
            inserted += 1
        s.flush()

    return {"inserted": inserted, "source": dc.SOURCE, "as_of": dc.today_str()}


def get_indices(session=None) -> dict:
    """从本地库读最新一个交易日的全部指数行。无数据返回可读 error dict。"""
    if session is None:
        with session_scope() as s:
            return get_indices(session=s)

    latest = session.scalar(select(MarketData.market_date)
                            .order_by(MarketData.market_date.desc()))
    if latest is None:
        return {"error": "本地无市场数据，请先 refresh_market", "source": dc.SOURCE}
    rows = session.scalars(select(MarketData)
                           .where(MarketData.market_date == latest)
                           .order_by(MarketData.symbol)).all()
    indices = [{"symbol": r.symbol, "name": r.name, "close": r.close,
                "change_pct": r.change_pct, "market_date": r.market_date}
               for r in rows]
    return {"indices": indices, "source": dc.SOURCE, "as_of": dc.today_str()}