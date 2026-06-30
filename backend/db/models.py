"""ORM 表定义。

Schema 要点:
- `Fund` 以 `fund_code` 为主键(上游基金代码本身就是稳定标识,
  不再额外加 surrogate id)。
- `Watchlist` / `FundNav` 用 surrogate `id`,但在业务键上加了
  DB 级别的唯一约束,以保证 upsert 在并发场景下也安全。
- 日期列统一存 `String`(ISO-8601),避免 SQLite 与其他方言之间
  出现时区漂移。
- `created_at` / `updated_at` 用 `server_default=func.now()`,
  时间戳取自数据库本地时钟,而不是 Python 进程。
"""
from datetime import datetime

from sqlalchemy import (DateTime, Float, Integer, String, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.session import Base


class Fund(Base):
    """基金主信息表。`fund_code` 即主键。"""
    __tablename__ = "funds"
    fund_code: Mapped[str] = mapped_column(String, primary_key=True)
    fund_name: Mapped[str | None] = mapped_column(String)
    fund_type: Mapped[str | None] = mapped_column(String)
    manager: Mapped[str | None] = mapped_column(String)
    company: Mapped[str | None] = mapped_column(String)
    inception_date: Mapped[str | None] = mapped_column(String)
    risk_level: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Watchlist(Base):
    """用户自选条目(持有 / 关注)。

    `fund_code` 唯一 —— 一只基金在自选里最多出现一次。持有相关
    字段(cost_nav、holding_share …)都允许为空,以便"关注"行
    不必填写持仓信息。
    """
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("fund_code", name="uq_watchlist_fund"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String, index=True)
    is_holding: Mapped[bool] = mapped_column(default=False)
    is_focus: Mapped[bool] = mapped_column(default=False)
    holding_amount: Mapped[float | None] = mapped_column(Float)
    holding_share: Mapped[float | None] = mapped_column(Float)
    cost_nav: Mapped[float | None] = mapped_column(Float)
    buy_date: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FundNav(Base):
    """基金日级净值快照。

    `(fund_code, nav_date)` 的唯一约束是 `repository.upsert_navs`
    幂等性的基础 —— 同一天重复拉取不会重复入库。
    """
    __tablename__ = "fund_nav"
    __table_args__ = (UniqueConstraint("fund_code", "nav_date", name="uq_nav_fund_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String, index=True)
    nav_date: Mapped[str] = mapped_column(String, index=True)
    unit_nav: Mapped[float | None] = mapped_column(Float)
    accumulated_nav: Mapped[float | None] = mapped_column(Float)
    daily_return: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String)
    source_updated_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MarketData(Base):
    """市场指数的日级快照(如沪深 300 收盘价)。"""
    __tablename__ = "market_data"
    __table_args__ = (UniqueConstraint("symbol", "market_date", name="uq_market_symbol_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_date: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    close: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())