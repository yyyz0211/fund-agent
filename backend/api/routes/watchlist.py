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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.services import watchlist_service as ws

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
    result = ws.add_transaction(fund_code, _tx_payload(payload))
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
        return ws.set_initial_holding(fund_code, _initial_holding_payload(payload))
    except ws.InitialHoldingConflict as e:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{e.fund_code} 已有 {e.existing_tx_count} 笔交易记录,"
                "不能再次走 initial-holding;请改用 /transactions 端点加仓"
            ),
        ) from e


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
def list_watchlist() -> list[dict]:
    """列出全部自选行,每行附带 transaction_count(避免前端再发 N 次请求)。"""
    from backend.db import repository as repo
    from backend.db.session import get_session

    rows = ws.list_watchlist()
    if not rows:
        return rows
    # 一次性把每只基金的交易笔数取出来,避免 N+1
    s = get_session()
    try:
        counts = repo.count_transactions_for_funds(
            s,
            [r["fund_code"] for r in rows],
        )
    finally:
        s.close()
    for r in rows:
        r["transaction_count"] = counts.get(r["fund_code"], 0)
    return rows


@router.post("", status_code=200)
def add_watchlist(payload: WatchlistUpsert) -> dict:
    """幂等添加。已存在的 fund_code 直接返回现有行,不会用 payload 覆盖。"""
    return ws.add_full(payload.fund_code, _add_payload(payload))


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
