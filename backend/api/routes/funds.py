"""基金基础信息 / 净值 / 净值历史 / 指标 路由。

仅做参数校验与服务层映射。所有业务逻辑在 `fund_service`。
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from backend.services import fund_service as fs
from backend.services.metric_service import _PERIOD_ROWS  # noqa: PLC2701

router = APIRouter(prefix="/api/funds", tags=["funds"])


def _http_from_service(result: dict, default: int = 200) -> tuple[int, dict]:
    """若 service 返回 error，把 error 文案包装进 HTTPException。

    区分 400 vs 404：404 用于「本地无数据」的语义；400 用于「参数无效」。
    关键字符串：`本地无`、`no nav data`、`insufficient nav data` —— 都说明
    "这条数据本地没有，请先 refresh"，归 404。其他错误（含用户传入坏参数）
    归 400。
    """
    if "error" in result:
        msg = result["error"]
        not_found_markers = ("本地无", "no nav data", "insufficient nav data")
        code = 404 if any(m in msg for m in not_found_markers) else 400
        raise HTTPException(status_code=code, detail=msg)
    return default, result


def _validate_date(s: str) -> None:
    if not s:
        return
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid date: {s}")


@router.get("/{code}")
def get_fund(code: str):
    body = fs.get_basic_info(code)
    _http_from_service(body)
    return body


@router.get("/{code}/nav")
def get_nav(code: str):
    body = fs.get_latest_nav(code)
    _http_from_service(body)
    return body


@router.get("/{code}/nav-history")
def get_nav_history(code: str,
                     start: str = Query(default=""),
                     end: str = Query(default="")):
    _validate_date(start)
    _validate_date(end)
    body = fs.get_nav_history(code, start_date=start, end_date=end)
    _http_from_service(body)
    return body


@router.get("/{code}/metrics")
def get_metrics(code: str,
                period: str = Query(default="1m")):
    if period not in _PERIOD_ROWS:
        raise HTTPException(status_code=400, detail=f"unsupported period: {period}")
    body = fs.get_metrics(code, period=period)
    _http_from_service(body)
    return body
