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


class FundProfile(Base):
    """基金体检用的扩展画像缓存。

    这里存放 AkShare 多接口采集后的低频字段,避免详情页/诊断接口每次
    都同步打外部数据源。JSON 结构先用字符串保存,由 service 层负责
    解析和容错。
    """
    __tablename__ = "fund_profiles"

    fund_code: Mapped[str] = mapped_column(String, primary_key=True)
    scale: Mapped[float | None] = mapped_column(Float)
    scale_date: Mapped[str | None] = mapped_column(String)
    peer_category: Mapped[str | None] = mapped_column(String)
    rank_total: Mapped[int | None] = mapped_column(Integer)
    rank_position: Mapped[int | None] = mapped_column(Integer)
    peer_candidates_json: Mapped[str | None] = mapped_column(String)
    top10_holding_pct: Mapped[float | None] = mapped_column(Float)
    top_industry_pct: Mapped[float | None] = mapped_column(Float)
    manager_summary: Mapped[str | None] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    as_of: Mapped[str | None] = mapped_column(String)
    raw_errors: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Watchlist(Base):
    """用户自选条目(持有 / 关注)。

    `fund_code` 唯一 —— 一只基金在自选里最多出现一次。持有相关
    字段(cost_nav、holding_share …)都允许为空,以便"关注"行
    不必填写持仓信息。

    `cost_nav_basis` 标记 `holding_share` / `cost_nav` 是不是由
    `FundTransaction` 表重算而来 —— `"legacy"` 表示手工录入(老
    行为),`"transactions"` 表示被交易表接管。前端据此切换"买入
    日期" vs "首次建仓 + 加仓 N 笔"的展示文案。
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
    preload_status: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    cost_nav_basis: Mapped[str | None] = mapped_column(String, default="legacy")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FundTransaction(Base):
    """买入/加仓明细。

    每条记录是一次买入行为;`holding_share` / `cost_nav` 在 service
    层按 **加权平均** 公式重算回写到 `Watchlist` 表(详见
    `services.transaction_service.recalc_holding`)。

    `kind` 字段为后续减仓/分红预留,当前只接受 `"buy"`。
    """
    __tablename__ = "fund_transactions"
    __table_args__ = (
        UniqueConstraint("fund_code", "tx_date", "tx_seq", name="uq_tx_fund_date_seq"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String, index=True)
    tx_date: Mapped[str] = mapped_column(String)
    tx_seq: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String, default="buy")
    amount: Mapped[float] = mapped_column(Float)
    nav: Mapped[float] = mapped_column(Float)
    share: Mapped[float | None] = mapped_column(Float)
    fee: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FundInvestmentPlan(Base):
    """定投计划规则。

    v1 只保存规则,不自动生成交易、不调度执行。实际买入仍然通过
    `FundTransaction` 的手动加仓路径落库。
    """
    __tablename__ = "fund_investment_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[float] = mapped_column(Float)
    frequency: Mapped[str] = mapped_column(String)
    day_rule: Mapped[str] = mapped_column(String)
    start_date: Mapped[str] = mapped_column(String)
    end_date: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")
    note: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FundPendingBuy(Base):
    """待确认申购记录。

    这类记录代表用户已经发起或计划记录了一笔买入,但还没有确认 NAV
    和份额。它不参与 Watchlist 持仓重算,确认后才转换成
    `FundTransaction`。
    """
    __tablename__ = "fund_pending_buys"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String, index=True)
    request_date: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    fee: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    nav_date: Mapped[str | None] = mapped_column(String)
    nav: Mapped[float | None] = mapped_column(Float)
    share: Mapped[float | None] = mapped_column(Float)
    transaction_id: Mapped[int | None] = mapped_column(Integer)
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


class Briefing(Base):
    """每日基金简报。

    `briefing_date` 唯一 —— 同日重复生成时 upsert 覆盖。
    `markdown` 供前端 ReactMarkdown 渲染；`sections_json` 存结构化数据
    (market_snapshot / watchlist_changes / errors / disclaimer)，用于程序消费。
    简报内容完全由本地数据(指数 + 自选池)驱动，不经过 policy 合规检查。
    """
    __tablename__ = "briefings"
    __table_args__ = (UniqueConstraint("briefing_date", name="uq_briefing_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    briefing_date: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    markdown: Mapped[str] = mapped_column(String)
    sections_json: Mapped[str] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    as_of: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class MarketSnapshot(Base):
    """市场快照：按交易日 + 类型（morning/post_market）存储当日市场全量快照。"""
    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("trade_date", "snapshot_type", name="uq_market_snapshot_date_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(16))  # "morning" | "post_market"
    indices_json: Mapped[str] = mapped_column(String)
    breadth_json: Mapped[str] = mapped_column(String)
    industry_sectors_json: Mapped[str] = mapped_column(String)
    concept_sectors_json: Mapped[str] = mapped_column(String)
    industry_flows_json: Mapped[str] = mapped_column(String)
    concept_flows_json: Mapped[str] = mapped_column(String)
    themes_json: Mapped[str] = mapped_column(String)
    breadth_indicators_json: Mapped[str] = mapped_column(String)
    overseas_json: Mapped[str] = mapped_column(String)
    announcements_json: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, default="akshare")
    as_of: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MarketEvidence(Base):
    """市场情报证据。

    保存可追溯的短证据,供简报和 QA 回答引用。这里不保存长篇新闻全文,
    只保存摘要、短摘录、来源 URL 和 hash。
    """
    __tablename__ = "market_evidence"
    __table_args__ = (UniqueConstraint("raw_hash", name="uq_market_evidence_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str | None] = mapped_column(String(10), index=True)
    brief_type: Mapped[str | None] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(String)
    symbols_json: Mapped[str | None] = mapped_column(String)
    metrics_json: Mapped[str | None] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    source_url: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[str | None] = mapped_column(String)
    collected_at: Mapped[str | None] = mapped_column(String)
    reliability: Mapped[str | None] = mapped_column(String)
    raw_excerpt: Mapped[str | None] = mapped_column(String)
    raw_hash: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
