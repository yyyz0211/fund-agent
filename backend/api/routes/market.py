"""市场指数与情报路由。

GET  /api/market/latest        今日指数快速读取
GET  /api/market/snapshot       市场情报快照（morning/post_market）
GET  /api/market/sectors        行业/概念板块数据（带排序筛选）
POST /api/market/refresh        手动触发采集（需 X-Local-Trigger header）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from backend.db.session import get_session
from backend.services import market_intel_service, market_service as ms


router = APIRouter(prefix="/api/market", tags=["market"])


# ---- 已有 ----

@router.get("/latest")
def latest():
    body = ms.get_indices()
    if "error" in body:
        raise HTTPException(status_code=404, detail=body["error"])
    rows = [{"symbol": i["symbol"], "name": i["name"],
             "close": i["close"], "change_pct": i["change_pct"],
             "market_date": i["market_date"]} for i in body["indices"]]
    return {"rows": rows, "source": body["source"], "as_of": body["as_of"]}


# ---- 新增 ----

@router.get("/snapshot")
def get_snapshot(
    date: str | None = Query(default=None, description="交易日 YYYY-MM-DD，默认今天"),
    type: str = Query(default="post_market", description="'morning' 或 'post_market'"),
    session: Session = Depends(get_session),
):
    """返回市场情报快照；不存在则触发采集。"""
    try:
        result = market_intel_service.get_market_snapshot(
            trade_date=date, snapshot_type=type, session=session
        )
        return result
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/sectors")
def get_sectors(
    kind: str = Query(default="industry", description="'industry' 或 'concept'"),
    sort: str = Query(default="change_pct", description="'change_pct' 或 'flow'"),
    limit: int = Query(default=10, ge=1, le=100),
):
    """返回行业或概念板块数据（涨跌幅 or 资金流向）。"""
    from backend.services import data_collector as dc

    if kind == "industry":
        if sort == "flow":
            rows = dc.fetch_industry_flows(limit_n=limit)
        else:
            rows = dc.fetch_sector_snapshot(limit_n=limit)
    else:
        if sort == "flow":
            rows = dc.fetch_concept_flows(limit_n=limit)
        else:
            rows = dc.fetch_concept_sectors(limit_n=limit)
    return {"rows": rows, "kind": kind, "sort": sort, "limit": limit}


@router.post("/refresh")
def refresh_market(
    _trigger: str | None = Header(default=None, alias="X-Local-Trigger"),
    session: Session = Depends(get_session),
):
    """手动触发市场情报采集（异步）。"""
    if _trigger is None:
        raise HTTPException(status_code=403, detail="Requires X-Local-Trigger header")
    return market_intel_service.refresh_market_intel_async(trigger="manual")
