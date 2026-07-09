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
    date: str | None = Query(default=None, description="采集目标交易日 YYYY-MM-DD；缺省=今天"),
    session: Session = Depends(get_session),
):
    """手动触发市场情报采集（异步）。

    `date` 默认 = 今天(向后兼容)。
    **历史日刷新被拒绝**: akshare 的"涨跌家数/板块涨跌幅"接口是当日实时接口,
    没有"指定交易日"参数。强制采集会把今天的数据写进历史日行, 覆盖当时的真实数据。
    如需回填历史日, 应在当日采集时完成, 事后只能从备份恢复。
    """
    if _trigger is None:
        raise HTTPException(status_code=403, detail="Requires X-Local-Trigger header")
    from datetime import date as _date
    if date:
        try:
            td = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {date!r}")
        today = _date.today()
        if td < today:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot refresh historical date {td.isoformat()}: "
                    f"akshare breadth/sector APIs only return latest trading day, "
                    f"refreshing would overwrite {td.isoformat()} with today's data."
                ),
            )
    return market_intel_service.refresh_market_intel_async(trigger="manual", target_date=date)


@router.get("/evidence")
def get_market_evidence(
    date: str | None = Query(default=None, description="交易日 YYYY-MM-DD，默认今天"),
    category: str | None = Query(default=None, description="类别: policy/announcement/macro/sector 等"),
    limit: int = Query(default=20, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """按日期/类别查 market_evidence，按 category 分组返回。无证据返回 {count:0, groups:{}}。"""
    from backend.services import market_evidence_service
    try:
        rows = market_evidence_service.search_evidence(
            trade_date=date, category=category, limit=limit, session=session,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["category"], []).append(r)
    return {"count": len(rows), "groups": groups, "items": rows}


@router.post("/evidence/refresh")
def refresh_market_evidence(
    _trigger: str | None = Header(default=None, alias="X-Local-Trigger"),
    brief_type: str = Query(default="post_market"),
):
    """手动触发 evidence 采集（异步）。"""
    if _trigger is None:
        raise HTTPException(status_code=403, detail="Requires X-Local-Trigger header")
    from backend.services import market_evidence_service
    return market_evidence_service.refresh_market_evidence_async(
        brief_type=brief_type, trigger="manual",
    )


@router.get("/evidence/refresh/status")
def get_market_evidence_refresh_status(
    brief_type: str = Query(default="post_market"),
):
    """查询最近一次 evidence 采集状态,用于前端解释空态/失败原因。"""
    from backend.services import market_evidence_service
    return market_evidence_service.get_last_refresh_status(brief_type=brief_type)
