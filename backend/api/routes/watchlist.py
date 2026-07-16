"""自选池路由：CRUD 全套（GET / POST / PATCH / DELETE）。

设计要点:
- `POST /api/watchlist` 用 `WatchlistUpsert` 接受完整字段集合,
  入参缺省字段交给 DB 默认值;重复 `fund_code` 由 service 层幂等
  返回现有行,HTTP 仍返回 200。
- `PATCH /api/watchlist/{fund_code}` 用 `WatchlistPatch`,只
  包含可选字段;未传字段不会被改。service 返回 None 时路由层
  抛 404。
- `DELETE /api/watchlist/{fund_code}` 复用 service.remove。
- 写路径走 service 层统一的事务管理,route 层只做参数校验。
"""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.services.watchlist import watchlist_preload_jobs as preload_jobs
from backend.services.watchlist import watchlist_service as ws

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class TransactionUpsert(BaseModel):
    """POST /api/watchlist/{code}/transactions 入参。

    数值字段 `ge=0` 与 Watchlist 现有校验保持一致;`nav=0` 会导致
    share 反算失败,route 层额外拦截。
    """

    model_config = ConfigDict(extra="forbid")

    tx_date: str
    amount: float = Field(ge=0)
    nav: float = Field(ge=0)
    fee: Optional[float] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=2000)
    kind: Literal["buy"] = "buy"

    @field_validator("tx_date")
    @classmethod
    def _validate_tx_date(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            raise ValueError("tx_date 不能为空")
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"tx_date must be ISO YYYY-MM-DD, got {v!r}") from exc
        return v


class InitialHoldingUpsert(TransactionUpsert):
    """POST /api/watchlist/{code}/initial-holding 入参。

    在一笔请求里完成创建/转持仓和首笔 buy 交易;`watchlist_note` 写入
    自选行备注,`note` 写入交易备注。
    """

    is_focus: Optional[bool] = None
    watchlist_note: Optional[str] = Field(default=None, max_length=2000)


class TransactionDeleteResponse(BaseModel):
    """DELETE 响应 —— 顺手把 recalc 后的 watchlist 也回传,前端无需
    额外再发一次 PnL 请求即可更新持仓卡。"""

    removed: bool
    transaction: dict
    watchlist: dict | None = None


class InvestmentPlanUpsert(BaseModel):
    """定投计划规则入参。v1 只保存规则,不自动生成交易。"""

    model_config = ConfigDict(extra="forbid")

    amount: float = Field(gt=0)
    frequency: Literal["daily", "weekly", "monthly"]
    day_rule: str = Field(min_length=1, max_length=32)
    start_date: str
    end_date: Optional[str] = None
    status: Literal["active", "paused"] = "active"
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_plan_date(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"date must be ISO YYYY-MM-DD, got {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _validate_range(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date")
        return self


class InvestmentPlanPatch(BaseModel):
    """定投计划局部更新入参。"""

    model_config = ConfigDict(extra="forbid")

    amount: Optional[float] = Field(default=None, gt=0)
    frequency: Optional[Literal["daily", "weekly", "monthly"]] = None
    day_rule: Optional[str] = Field(default=None, min_length=1, max_length=32)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[Literal["active", "paused"]] = None
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_plan_date(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"date must be ISO YYYY-MM-DD, got {v!r}") from exc
        return v


class PendingBuyUpsert(BaseModel):
    """待确认申购入参。不会直接计入市值。"""

    model_config = ConfigDict(extra="forbid")

    request_date: str
    amount: float = Field(gt=0)
    fee: Optional[float] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("request_date")
    @classmethod
    def _validate_request_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"request_date must be ISO YYYY-MM-DD, got {v!r}") from exc
        return v


class PendingBuyConfirm(BaseModel):
    """确认待申购时只传确认日期,NAV 由后端本地库精确读取。"""

    model_config = ConfigDict(extra="forbid")

    tx_date: str

    @field_validator("tx_date")
    @classmethod
    def _validate_tx_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"tx_date must be ISO YYYY-MM-DD, got {v!r}") from exc
        return v


def _tx_payload(payload: TransactionUpsert) -> dict:
    return {
        "tx_date": payload.tx_date,
        "amount": payload.amount,
        "nav": payload.nav,
        "fee": payload.fee,
        "note": payload.note,
        "kind": payload.kind or "buy",
    }


def _initial_holding_payload(payload: InitialHoldingUpsert) -> dict:
    data = _tx_payload(payload)
    data["is_focus"] = payload.is_focus
    data["watchlist_note"] = payload.watchlist_note
    return data


def _investment_plan_payload(payload: InvestmentPlanUpsert) -> dict:
    return {
        "amount": payload.amount,
        "frequency": payload.frequency,
        "day_rule": payload.day_rule,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "status": payload.status,
        "note": payload.note,
    }


def _investment_plan_patch(payload: InvestmentPlanPatch) -> dict:
    return payload.model_dump(exclude_unset=True)


def _raise_nav_mismatch(exc: ws.TransactionNavMismatch) -> None:
    raise HTTPException(
        status_code=400,
        detail=(
            f"{exc.fund_code} {exc.tx_date} NAV mismatch: "
            f"expected {exc.expected}, got {exc.got}"
        ),
    ) from exc


def _pending_buy_payload(payload: PendingBuyUpsert) -> dict:
    return {
        "request_date": payload.request_date,
        "amount": payload.amount,
        "fee": payload.fee,
        "note": payload.note,
    }


@router.get("/{fund_code}/transactions")
def list_transactions(fund_code: str) -> list[dict]:
    """列出一只基金的全部买入记录。基金不在自选里时返回空列表(不报错),
    以便前端在新建自选后能直接查得到。"""
    return ws.list_transactions(fund_code)


@router.post("/{fund_code}/transactions", status_code=200)
def add_transaction(fund_code: str, payload: TransactionUpsert) -> dict:
    """新增一笔买入。`amount > 0` 且 `nav > 0` 都会在 Pydantic 层校验;
    基金不在自选里 → 404。"""
    if payload.amount == 0 or payload.nav == 0:
        raise HTTPException(
            status_code=422,
            detail="amount 和 nav 必须都大于 0,否则无法反算份额",
        )
    try:
        result = ws.add_transaction(fund_code, _tx_payload(payload))
    except ws.TransactionNavMismatch as exc:
        _raise_nav_mismatch(exc)
    if result is None:
        raise HTTPException(status_code=404, detail=f"{fund_code} 不在自选池中")
    return result


@router.post("/{fund_code}/initial-holding", status_code=200)
def set_initial_holding(fund_code: str, payload: InitialHoldingUpsert) -> dict:
    """原子化创建/转持仓 + 首笔 buy 交易 + recalc。"""
    if payload.amount == 0 or payload.nav == 0:
        raise HTTPException(
            status_code=422,
            detail="amount 和 nav 必须都大于 0,否则无法反算份额",
        )
    try:
        result = ws.set_initial_holding(fund_code, _initial_holding_payload(payload))
        job = preload_jobs.start_preload_job(fund_code)
        if job:
            result["preload_job"] = job
            result["watchlist"]["preload_status"] = job.get("status")
        return result
    except ws.InitialHoldingConflict as e:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{e.fund_code} 已有 {e.existing_tx_count} 笔交易记录,"
                "不能再次走 initial-holding;请改用 /transactions 端点加仓"
            ),
        ) from e
    except ws.TransactionNavMismatch as exc:
        _raise_nav_mismatch(exc)


@router.delete("/{fund_code}/transactions/{tx_id}")
def delete_transaction(fund_code: str, tx_id: int) -> dict:
    """按 id 删除一笔买入,删除后用剩余交易重算并回写 Watchlist。"""
    result = ws.remove_transaction(fund_code, tx_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"transaction {tx_id} 不存在")
    if result.get("error") == "fund_mismatch":
        raise HTTPException(
            status_code=400,
            detail=f"transaction {tx_id} 不属于 {fund_code}",
        )
    return result


@router.get("/{fund_code}/preload/{job_id}")
def get_preload_job(fund_code: str, job_id: str) -> dict:
    """查询自选池新增后的后台数据预热任务。"""
    return preload_jobs.get_preload_job(fund_code, job_id)


@router.get("/{fund_code}/investment-plans")
def list_investment_plans(fund_code: str) -> list[dict]:
    plans = ws.list_investment_plans(fund_code)
    if plans is None:
        raise HTTPException(status_code=404, detail=f"{fund_code} 不在自选池中")
    return plans


@router.post("/{fund_code}/investment-plans", status_code=200)
def add_investment_plan(fund_code: str, payload: InvestmentPlanUpsert) -> dict:
    plan = ws.add_investment_plan(fund_code, _investment_plan_payload(payload))
    if plan is None:
        raise HTTPException(status_code=404, detail=f"{fund_code} 不在自选池中")
    return plan


@router.patch("/{fund_code}/investment-plans/{plan_id}")
def patch_investment_plan(
    fund_code: str,
    plan_id: int,
    payload: InvestmentPlanPatch,
) -> dict:
    plan = ws.update_investment_plan(fund_code, plan_id, _investment_plan_patch(payload))
    if plan is None:
        raise HTTPException(status_code=404, detail=f"investment plan {plan_id} 不存在")
    return plan


@router.delete("/{fund_code}/investment-plans/{plan_id}")
def delete_investment_plan(fund_code: str, plan_id: int) -> dict:
    result = ws.remove_investment_plan(fund_code, plan_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"investment plan {plan_id} 不存在")
    return result


@router.get("/{fund_code}/pending-buys")
def list_pending_buys(fund_code: str) -> list[dict]:
    rows = ws.list_pending_buys(fund_code)
    if rows is None:
        raise HTTPException(status_code=404, detail=f"{fund_code} 不在自选池中")
    return rows


@router.post("/{fund_code}/pending-buys", status_code=200)
def add_pending_buy(fund_code: str, payload: PendingBuyUpsert) -> dict:
    row = ws.add_pending_buy(fund_code, _pending_buy_payload(payload))
    if row is None:
        raise HTTPException(status_code=404, detail=f"{fund_code} 不在自选池中")
    return row


@router.post("/{fund_code}/pending-buys/{pending_id}/confirm", status_code=200)
def confirm_pending_buy(fund_code: str, pending_id: int,
                        payload: PendingBuyConfirm) -> dict:
    try:
        result = ws.confirm_pending_buy(fund_code, pending_id, payload.tx_date)
    except ws.PendingBuyNavMissing as exc:
        raise HTTPException(
            status_code=404,
            detail=f"{exc.fund_code} {exc.tx_date} 本地无确认 NAV",
        ) from exc
    except ws.PendingBuyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=f"pending buy {exc.pending_id} 当前状态为 {exc.status},不能确认",
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"pending buy {pending_id} 不存在")
    return result


@router.post("/{fund_code}/pending-buys/{pending_id}/cancel", status_code=200)
def cancel_pending_buy(fund_code: str, pending_id: int) -> dict:
    row = ws.cancel_pending_buy(fund_code, pending_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"pending buy {pending_id} 不存在")
    return row


class WatchlistUpsert(BaseModel):
    """POST 入参。`fund_code` 必填,其它字段全部 Optional。

    数值字段带 `ge=0`,防止负的持仓金额被落库。
    """

    model_config = ConfigDict(extra="forbid")

    fund_code: str = Field(min_length=1, max_length=32)
    note: Optional[str] = Field(default=None, max_length=2000)
    is_holding: Optional[bool] = None
    is_focus: Optional[bool] = None
    holding_amount: Optional[float] = Field(default=None, ge=0)
    holding_share: Optional[float] = Field(default=None, ge=0)
    cost_nav: Optional[float] = Field(default=None, ge=0)
    buy_date: Optional[str] = None

    @field_validator("buy_date")
    @classmethod
    def _validate_buy_date(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"buy_date must be ISO YYYY-MM-DD, got {v!r}") from exc
        return v


class WatchlistPatch(BaseModel):
    """PATCH 入参。全部字段 Optional —— 未传字段保持原值。"""

    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(default=None, max_length=2000)
    is_holding: Optional[bool] = None
    is_focus: Optional[bool] = None
    holding_amount: Optional[float] = Field(default=None, ge=0)
    holding_share: Optional[float] = Field(default=None, ge=0)
    cost_nav: Optional[float] = Field(default=None, ge=0)
    buy_date: Optional[str] = None

    @field_validator("buy_date")
    @classmethod
    def _validate_buy_date(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"buy_date must be ISO YYYY-MM-DD, got {v!r}") from exc
        return v


def _add_payload(payload: WatchlistUpsert) -> dict:
    """把 Pydantic 模型转成 service.add 接受的 dict。"""
    return {
        "note": payload.note,
        "is_holding": payload.is_holding,
        "is_focus": payload.is_focus,
        "holding_amount": payload.holding_amount,
        "holding_share": payload.holding_share,
        "cost_nav": payload.cost_nav,
        "buy_date": payload.buy_date,
    }


def _patch_payload(payload: WatchlistPatch) -> dict:
    """只挑出 Pydantic 中被显式设置的字段,丢弃 None(避免把 None 写进库)。"""
    data = payload.model_dump(exclude_unset=True)
    return {k: v for k, v in data.items() if v is not None}


@router.get("")
def list_watchlist(session: Session = Depends(get_db_session)) -> list[dict]:
    """列出全部自选行,批量附带展示字段,避免前端逐行补数据。"""
    from backend.db.repositories import fund as fund_repo
    from backend.db.models import Fund

    rows = ws.list_watchlist(session=session)
    if not rows:
        return rows
    codes = [r["fund_code"] for r in rows]
    counts = fund_repo.count_transactions_for_funds(session, codes)
    latest_navs = fund_repo.get_latest_navs_for_funds(session, codes)
    fund_rows = session.scalars(select(Fund).where(Fund.fund_code.in_(codes))).all()
    fund_names = {fund.fund_code: fund.fund_name for fund in fund_rows}
    for r in rows:
        code = r["fund_code"]
        latest_nav = latest_navs.get(code) or {}
        accumulated_nav = latest_nav.get("accumulated_nav")
        daily_return = latest_nav.get("daily_return")

        r["fund_name"] = fund_names.get(code)
        r["transaction_count"] = counts.get(code, 0)
        r["latest_nav"] = accumulated_nav
        r["nav_date"] = latest_nav.get("nav_date")
        r["daily_return"] = daily_return
        r["daily_pnl_pct"] = daily_return
        r["daily_pnl_abs"] = _daily_pnl_abs(
            holding_share=r.get("holding_share") if r.get("is_holding") else None,
            current_nav=accumulated_nav,
            daily_return=daily_return,
        )
    return rows


def _daily_pnl_abs(
    *,
    holding_share: float | None,
    current_nav: float | None,
    daily_return: float | None,
) -> float | None:
    """按最新日涨跌估算持仓当日盈亏金额。

    daily_return 是 (current - previous) / previous,所以前一日净值为
    current / (1 + daily_return)。没有持仓份额或日涨跌时返回 None。
    """
    if holding_share is None or current_nav is None or daily_return is None:
        return None
    share = float(holding_share)
    nav = float(current_nav)
    ret = float(daily_return)
    if share <= 0 or nav <= 0 or ret <= -1:
        return None
    previous_nav = nav / (1 + ret)
    return round(share * (nav - previous_nav), 4)


@router.post("", status_code=200)
def add_watchlist(payload: WatchlistUpsert) -> dict:
    """幂等添加。已存在的 fund_code 直接返回现有行,不会用 payload 覆盖。"""
    existing = ws.get_one(payload.fund_code)
    row = ws.add_full(payload.fund_code, _add_payload(payload))
    if existing is None:
        job = preload_jobs.start_preload_job(payload.fund_code)
        if job:
            row["preload_job"] = job
            row["preload_status"] = job.get("status")
    return row


@router.patch("/{fund_code}")
def patch_watchlist(fund_code: str, payload: WatchlistPatch) -> dict:
    """局部更新;不在池中返回 404。"""
    row = ws.update(fund_code, _patch_payload(payload))
    if row is None:
        raise HTTPException(status_code=404, detail=f"{fund_code} 不在自选池中")
    return row


@router.delete("/{fund_code}")
def delete_watchlist(fund_code: str) -> dict:
    """删除一条;不在池中返回 404。"""
    result = ws.remove(fund_code)
    if not result.get("removed"):
        raise HTTPException(status_code=404, detail=f"{fund_code} 不在自选池中")
    return result
