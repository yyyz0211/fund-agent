"""基金基础信息 / 净值 / 净值历史 / 指标 路由。

仅做参数校验与服务层映射。所有业务逻辑在 `fund_service`。
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from backend.services.shared import diagnosis_refresh_jobs as refresh_jobs
from backend.services.shared import diagnosis_service as ds
from backend.services.fund import fund_service as fs
from backend.services.shared import metric_service
from backend.services.shared.metric_service import _PERIOD_ROWS  # noqa: PLC2701

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


@router.get("/{code}/summary")
def get_summary(code: str,
                period: str = Query(default="1m"),
                start: str = Query(default="")):
    _validate_date(start)
    if period not in _PERIOD_ROWS:
        raise HTTPException(status_code=400, detail=f"unsupported period: {period}")
    return fs.get_summary(code, period=period, start_date=start)


@router.get("/{code}/diagnosis")
def get_diagnosis(code: str, period: str = Query(default="1y")):
    if period not in _PERIOD_ROWS:
        raise HTTPException(status_code=400, detail=f"unsupported period: {period}")
    return ds.diagnose_fund(code, period=period)


@router.get("/{code}/peers")
def get_peers(code: str,
              limit: int = Query(default=5, ge=1, le=10),
              period: str = Query(default="1y")):
    if period not in _PERIOD_ROWS:
        raise HTTPException(status_code=400, detail=f"unsupported period: {period}")
    return {"fund_code": code, "peers": ds.get_peers(code, limit=limit, period=period)}


@router.post("/{code}/diagnosis/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh_diagnosis(code: str, force: bool = Query(default=False)):
    return refresh_jobs.start_refresh_job(code, force=force)


@router.get("/{code}/diagnosis/refresh/{job_id}")
def get_refresh_diagnosis_job(code: str, job_id: str):
    return refresh_jobs.get_refresh_job(code, job_id)


@router.get("/{code}")
def get_fund(code: str):
    body = fs.get_basic_info(code)
    _http_from_service(body)
    return body


@router.get("/{code}/nav")
def get_nav(code: str, nav_date: str = Query(default="", alias="date")):
    _validate_date(nav_date)
    body = fs.get_nav_by_date(code, nav_date) if nav_date else fs.get_latest_nav(code)
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


@router.post("/{code}/refresh")
def post_refresh(code: str):
    """拉取一只基金的基础信息和净值并写入本地库。

    用途:用户从自选池点击进入详情页,但本地还没 `refresh_fund` 过这只基金,
    详情页 404。此时前端给个"立即拉取"按钮,触发本端点把数据补齐。

    返回 `fs.refresh_fund(code)` 的原始 dict,字段含义:
      - `fund_code`: 基金代码
      - `navs_inserted`: 本次实际新增的 NAV 行数
      - `already_up_to_date`: True 表示本地已是最新
      - `source` / `as_of`: 数据来源与拉取日期

    抓取失败(网络/AKShare 报错)时返回 502,detail 含原始 error 文本。
    """
    result = fs.refresh_fund(code)
    if isinstance(result, dict) and "error" in result:
        # 区分"本地无基础信息/净值" vs 上游抓取失败 — refresh 不存在基金代码时
        # fetch_fund_info 会返回 error, 归 502(上游失败)。
        raise HTTPException(status_code=502, detail=result["error"])
    return result
