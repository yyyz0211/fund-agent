"""持仓组合路由：PnL 总额 + 多基金对比系列。

- `GET /api/portfolio/pnl?codes=110011,000001` —— 计算持仓盈亏,
  `codes` 缺省时算全部 `is_holding=true` 行。
- `GET /api/portfolio/compare?codes=...&start=...&end=...` —— 拉多只
  基金的净值历史,给前端 Recharts 直接画图。

PnL 与 compare 都不写库,纯读 + 计算。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from backend.db.models import Fund, FundNav
from backend.db.session import get_session
from backend.services.market import data_collector as dc
from backend.services.fund import pnl_service as psvc
from backend.services.fund import portfolio_history as ph

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _http_from_service(result: dict, default: int = 200) -> tuple[int, dict]:
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return default, result


def _validate_date(s: str) -> None:
    if not s:
        return
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid date: {s}") from exc


@router.get("/pnl")
def get_portfolio_pnl(
    codes: str = Query(default="", description="逗号分隔的 fund_code 列表;空=全部持仓"),
):
    """返回自选池中持仓行的当前 PnL 总额 + 各项明细。"""
    fund_codes: Optional[list[str]] = None
    if codes.strip():
        fund_codes = [c.strip() for c in codes.split(",") if c.strip()]
    return psvc.calculate_pnl(fund_codes=fund_codes)


@router.get("/pnl-series")
def get_portfolio_pnl_series(
    codes: str = Query(default="", description="逗号分隔的 fund_code 列表;空=全部持仓"),
    start: str = Query(default="", description="ISO YYYY-MM-DD;空=默认 1 年窗口"),
    end: str = Query(default="", description="ISO YYYY-MM-DD;空=今天"),
):
    """返回持仓组合每日盈亏时间序列(投入 / 市值 / 累计盈亏)。

    确定性本地计算,不联网。`codes` 缺省时算全部 `is_holding=true` 行。
    """
    _validate_date(start)
    _validate_date(end)
    fund_codes: Optional[list[str]] = None
    if codes.strip():
        fund_codes = [c.strip() for c in codes.split(",") if c.strip()]
    return ph.calculate_pnl_series(fund_codes=fund_codes, start=start, end=end)


@router.get("/compare")
def get_compare_series(
    codes: str = Query(..., description="逗号分隔的 fund_code 列表;至少 1 个"),
    start: str = Query(default="", description="ISO YYYY-MM-DD,空=默认 1 年前"),
    end: str = Query(default="", description="ISO YYYY-MM-DD,空=今天"),
):
    """拉多只基金的同期 NAV 历史,给 `/compare` 页面画图用。

    返回结构: `{as_of, series: [{code, fund_name, points: [{nav_date, accumulated_nav}, ...]}, ...]}`。
    """
    _validate_date(start)
    _validate_date(end)
    raw = [c.strip() for c in codes.split(",") if c.strip()]
    if not raw:
        raise HTTPException(status_code=400, detail="codes 不能为空")

    s = get_session()
    try:
        # 一次性取基金名
        name_map: dict[str, str | None] = {
            f.fund_code: f.fund_name
            for f in s.scalars(select(Fund).where(Fund.fund_code.in_(raw))).all()
        }

        # 起止日期默认:start=今天-365 天, end=今天
        if not end:
            end = dc.today_str()
        if not start:
            try:
                start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"invalid end date: {end}") from exc

        series: list[dict] = []
        any_data = False
        for code in raw:
            stmt = (
                select(FundNav)
                .where(FundNav.fund_code == code)
                .where(FundNav.nav_date >= start)
                .where(FundNav.nav_date <= end)
                .order_by(FundNav.nav_date)
            )
            rows = s.scalars(stmt).all()
            points = [
                {"nav_date": str(r.nav_date), "accumulated_nav": r.accumulated_nav}
                for r in rows
            ]
            if points:
                any_data = True
            series.append({
                "code": code,
                "fund_name": name_map.get(code),
                "points": points,
            })

        if not any_data:
            raise HTTPException(
                status_code=404,
                detail=f"区间 [{start}, {end}] 内 {codes} 无任何 NAV 数据,请先 refresh_fund",
            )

        return {
            "as_of": end,
            "start": start,
            "end": end,
            "series": series,
            "source": dc.SOURCE,
        }
    finally:
        s.close()
