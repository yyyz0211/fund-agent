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
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.services import watchlist_service as ws

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


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
    return ws.list_watchlist()


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