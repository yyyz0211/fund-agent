"""市场指数路由。

只读，依赖 `market_service.get_indices` 已存在的数据；本地无数据时
返回 404 让前端引导用户先运行 `refresh_market`。
"""
from fastapi import APIRouter, HTTPException

from backend.services import market_service as ms

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/latest")
def latest():
    body = ms.get_indices()
    if "error" in body:
        raise HTTPException(status_code=404, detail=body["error"])
    rows = [{"symbol": i["symbol"], "name": i["name"],
             "close": i["close"], "change_pct": i["change_pct"],
             "market_date": i["market_date"]} for i in body["indices"]]
    return {"rows": rows, "source": body["source"], "as_of": body["as_of"]}
