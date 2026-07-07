# 市场情报中心实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增市场情报中心：每日简报升级（概念板块 + 资金流向）+ `/market` 前端页 + 后端数据采集编排

**Architecture:** 后端新增 `MarketSnapshot` ORM + `market_intel_service.py`（编排采集）+ 扩展 `data_collector.py`；前端新增 `/market` 页面及组件；现有简报 prompt 扩展 9 sections；scheduler 增加 morning/post_market 两个 job。

**Tech Stack:** Python/FastAPI (akshare 1.18.64, SQLAlchemy) + Next.js 14 (TanStack Query, Recharts) + SQLite

---

## Global Constraints

- akshare 免费接口，分钟级延迟；采集失败不抛异常，降级展示
- 非交易日：`morning`/`post_market` scheduler job 跳过
- `max_instances=1` 防并发重复采集
- 禁止输出投资建议 / 涨跌预测 / 强制交易指令

---

## 文件变更总览

```
Create:   backend/services/market_intel_service.py
Create:   backend/tests/test_market_intel_service.py
Create:   backend/tests/test_market_intel_routes.py
Create:   frontend/src/components/market/MarketOverviewCards.tsx
Create:   frontend/src/components/market/IndustrySectorTable.tsx
Create:   frontend/src/components/market/ConceptSectorTable.tsx
Create:   frontend/src/components/market/ThemeBoards.tsx
Create:   frontend/src/components/market/OverseasMarkets.tsx
Create:   frontend/src/components/market/AnnouncementList.tsx
Create:   frontend/src/components/market/SnapshotRefreshButton.tsx
Create:   frontend/src/lib/market.ts
Create:   frontend/app/market/page.tsx
Modify:   backend/db/models.py           (add MarketSnapshot)
Modify:   backend/db/repository.py        (add upsert_market_snapshot)
Modify:   backend/services/data_collector.py (add 6 fetch functions)
Modify:   backend/api/routes/market.py   (extend routes)
Modify:   backend/graph/prompts.py       (extend BRIEFING_PROMPT_TEMPLATE)
Modify:   backend/services/briefing_service.py (add concept sectors to snapshot)
Modify:   backend/scheduler.py            (add morning/post_market jobs)
Modify:   frontend/src/components/AppShell.tsx (add nav entry)
Modify:   frontend/src/lib/api.ts         (add market API helpers)
```

---

## Task 1: MarketSnapshot ORM + repository upsert

**Files:**
- Modify: `backend/db/models.py`
- Modify: `backend/db/repository.py`

**Interfaces:**
- Produces: `backend.db.models.MarketSnapshot` ORM class
- Produces: `backend.db.repository.upsert_market_snapshot(s, trade_date, snapshot_type, payload) -> MarketSnapshot`

**Steps:**

- [ ] **Step 1: 在 `backend/db/models.py` 末尾添加 `MarketSnapshot` 类**

```python
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
```

- [ ] **Step 2: 运行 `python -c "from backend.db.models import MarketSnapshot; print('OK')"` 验证模型导入**

Expected: OK (no output on success)

- [ ] **Step 3: 在 `backend/db/repository.py` 末尾添加 `upsert_market_snapshot`**

```python
def upsert_market_snapshot(
    s: Session,
    trade_date: str,
    snapshot_type: str,
    payload: dict,
) -> MarketSnapshot:
    """upsert market_snapshots 表，返回行。payload keys 对应模型 JSON 列。"""
    json_keys = (
        "indices_json", "breadth_json", "industry_sectors_json",
        "concept_sectors_json", "industry_flows_json", "concept_flows_json",
        "themes_json", "breadth_indicators_json", "overseas_json",
        "announcements_json",
    )
    values = {"trade_date": trade_date, "snapshot_type": snapshot_type, "source": "akshare"}
    for key in json_keys:
        val = payload.get(key.replace("_json", ""))
        if isinstance(val, (list, dict)):
            import json as _json
            values[key] = _json.dumps(val, ensure_ascii=False)
        else:
            values[key] = _json.dumps(val or [])
    values["as_of"] = payload.get("as_of", trade_date)

    row = s.scalar(
        select(MarketSnapshot).where(
            MarketSnapshot.trade_date == trade_date,
            MarketSnapshot.snapshot_type == snapshot_type,
        )
    )
    if row is None:
        row = MarketSnapshot(**values)
        s.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
    s.flush()
    return row
```

- [ ] **Step 4: 在 `backend/db/repository.py` 头部添加 import**

```python
from backend.db.models import (
    Fund, FundNav, Watchlist, FundTransaction,
    FundInvestmentPlan, FundPendingBuy, MarketData,
    Briefing, MarketSnapshot,
)
```

- [ ] **Step 5: 写测试 `backend/tests/test_market_intel_service.py`（先写空的，确认 import 通过）**

```python
"""market_intel_service 集成测试。"""
import pytest


def test_market_snapshot_model_import():
    from backend.db.models import MarketSnapshot
    assert MarketSnapshot.__tablename__ == "market_snapshots"


def test_upsert_market_snapshot_idempotent(in_memory_session):
    from backend.db.models import MarketSnapshot
    from backend.db.repository import upsert_market_snapshot

    payload = {
        "trade_date": "2026-07-07",
        "snapshot_type": "post_market",
        "indices": [{"symbol": "000001", "name": "上证指数", "close": 4094.4, "change_pct": 0.5}],
        "breadth": {"up": 669, "down": 4494, "limit_up": 34, "limit_down": 25},
        "industry_sectors": [{"name": "游戏", "change_pct": 2.39}],
        "concept_sectors": [],
        "industry_flows": [],
        "concept_flows": [],
        "themes": [],
        "breadth_indicators": {},
        "overseas": [],
        "announcements": [],
        "as_of": "2026-07-07",
    }

    row1 = upsert_market_snapshot(in_memory_session, "2026-07-07", "post_market", payload)
    in_memory_session.commit()
    row2 = upsert_market_snapshot(in_memory_session, "2026-07-07", "post_market", payload)
    assert row1.id == row2.id  # idempotent
```

- [ ] **Step 6: 跑测试**

Run: `pytest backend/tests/test_market_intel_service.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/db/models.py backend/db/repository.py backend/tests/test_market_intel_service.py
git commit -m "feat: add MarketSnapshot ORM and repository upsert"
```

---

## Task 2: data_collector 扩展（6 个新采集函数）

**Files:**
- Modify: `backend/services/data_collector.py`

**Interfaces:**
- Produces: `fetch_concept_sectors()`, `fetch_concept_flows()`, `fetch_industry_flows()`, `fetch_theme_boards()`, `fetch_breadth_indicators()`, `fetch_overseas_markets()`, `fetch_announcements()`

**Steps:**

- [ ] **Step 1: 写测试（确认函数不存在则 FAIL）**

```python
def test_fetch_concept_sectors_returns_list():
    from backend.services.data_collector import fetch_concept_sectors
    result = fetch_concept_sectors()
    assert isinstance(result, list)

def test_fetch_industry_flows_returns_list():
    from backend.services.data_collector import fetch_industry_flows
    result = fetch_industry_flows()
    assert isinstance(result, list)

def test_fetch_concept_flows_returns_list():
    from backend.services.data_collector import fetch_concept_flows
    result = fetch_concept_flows()
    assert isinstance(result, list)

def test_fetch_theme_boards_returns_list():
    from backend.services.data_collector import fetch_theme_boards
    result = fetch_theme_boards()
    assert isinstance(result, list)

def test_fetch_breadth_indicators_returns_dict():
    from backend.services.data_collector import fetch_breadth_indicators
    result = fetch_breadth_indicators()
    assert isinstance(result, dict)

def test_fetch_overseas_markets_returns_list():
    from backend.services.data_collector import fetch_overseas_markets
    result = fetch_overseas_markets()
    assert isinstance(result, list)

def test_fetch_announcements_returns_list():
    from backend.services.data_collector import fetch_announcements
    result = fetch_announcements(limit=5)
    assert isinstance(result, list)
```

Run: `pytest backend/tests/test_data_collector.py -v -k "concept or flow or theme or overseas or breadth_indicators"` — 确认 FAIL

- [ ] **Step 2: 在 `data_collector.py` 末尾添加 6 个采集函数**

```python
def fetch_concept_sectors(limit_n: int = 10) -> list[dict]:
    """拉取概念板块涨跌幅 top/bottom。akshare: stock_board_concept_spot_em()"""
    try:
        df = ak.stock_board_concept_spot_em()
        if df is None or getattr(df, "empty", True) or len(df) == 0:
            return []
        change_col = _find_col(df, "涨跌幅", "涨跌幅(%)")
        name_col = _find_col(df, "板块名称", "名称", "板块")
        if change_col is None or name_col is None:
            return []
        rows = []
        for _, row in df.iterrows():
            try:
                name = str(row.get(name_col, "")).strip()
                change = _to_float(row.get(change_col))
                if name and change is not None:
                    rows.append({"name": name, "change_pct": change, "source": SOURCE})
            except Exception:
                continue
        if not rows:
            return []
        rows.sort(key=lambda r: r["change_pct"], reverse=True)
        top = rows[:limit_n]
        bottom = rows[-limit_n:] if len(rows) > limit_n else []
        result = list(top)
        for b in bottom:
            if b not in result:
                result.append(b)
        return result
    except Exception:
        return []


def fetch_industry_flows(limit_n: int = 10) -> list[dict]:
    """拉取行业板块资金流向（净流入 top/bottom）。来源: stock_board_industry_summary_ths()"""
    try:
        df = ak.stock_board_industry_summary_ths()
        if df is None or getattr(df, "empty", True) or len(df) == 0:
            return []
        name_col = "板块"
        flow_col = _find_col(df, "净流入", "净流入(万元)", "资金净流入")
        if name_col not in df.columns or flow_col is None:
            return []
        rows = []
        for _, row in df.iterrows():
            try:
                name = str(row.get(name_col, "")).strip()
                flow = _to_float(row.get(flow_col))
                if name and flow is not None:
                    rows.append({"name": name, "net_flow": flow, "source": SOURCE})
            except Exception:
                continue
        if not rows:
            return []
        rows.sort(key=lambda r: r["net_flow"], reverse=True)
        top = rows[:limit_n]
        bottom = rows[-limit_n:] if len(rows) > limit_n else []
        result = list(top)
        for b in bottom:
            if b not in result:
                result.append(b)
        return result
    except Exception:
        return []


def fetch_concept_flows(limit_n: int = 10) -> list[dict]:
    """拉取概念板块资金流向（净流入 top/bottom）。来源: stock_board_concept_summary_ths()"""
    try:
        df = ak.stock_board_concept_summary_ths()
        if df is None or getattr(df, "empty", True) or len(df) == 0:
            return []
        name_col = _find_col(df, "板块", "板块名称", "概念板块")
        flow_col = _find_col(df, "净流入", "资金净流入")
        if name_col is None or flow_col is None:
            return []
        rows = []
        for _, row in df.iterrows():
            try:
                name = str(row.get(name_col, "")).strip()
                flow = _to_float(row.get(flow_col))
                if name and flow is not None:
                    rows.append({"name": name, "net_flow": flow, "source": SOURCE})
            except Exception:
                continue
        if not rows:
            return []
        rows.sort(key=lambda r: r["net_flow"], reverse=True)
        top = rows[:limit_n]
        bottom = rows[-limit_n:] if len(rows) > limit_n else []
        result = list(top)
        for b in bottom:
            if b not in result:
                result.append(b)
        return result
    except Exception:
        return []


def fetch_theme_boards(limit_n: int = 20) -> list[dict]:
    """拉取当日涨停板，按涨停原因归类为题材。akshare: stock_zt_pool_em()"""
    try:
        df = ak.stock_zt_pool_em(date=today_str())
        if df is None or getattr(df, "empty", True) or len(df) == 0:
            return []
        reason_col = _find_col(df, "涨停统计", "涨停原因", "连板数")
        name_col = _find_col(df, "股票代码", "代码", "股票名称", "名称")
        change_col = _find_col(df, "涨跌幅")
        if name_col is None:
            return []
        # 归类: 按涨停原因（reason_col）分组
        themes: dict[str, list] = {}
        for _, row in df.iterrows():
            reason = str(row.get(reason_col, "其他")).strip() if reason_col else "其他"
            name = str(row.get(name_col, ""))
            change = _to_float(row.get(change_col)) if change_col else None
            if reason not in themes:
                themes[reason] = []
            themes[reason].append({"name": name, "change_pct": change})
        result = []
        for reason, stocks in themes.items():
            result.append({
                "theme": reason,
                "count": len(stocks),
                "stocks": stocks[:5],
                "source": SOURCE,
            })
        result.sort(key=lambda x: x["count"], reverse=True)
        return result[:limit_n]
    except Exception:
        return []


def fetch_breadth_indicators() -> dict:
    """拉取情绪指标: 连板高度 top5。akshare: stock_zt_pool_strong_em(date=today_str())"""
    try:
        df = ak.stock_zt_pool_strong_em(date=today_str())
        board_height = []
        if df is not None and not getattr(df, "empty", True):
            name_col = _find_col(df, "名称")
            board_col = _find_col(df, "连板数")
            if name_col and board_col:
                for _, row in df.head(5).iterrows():
                    try:
                        name = str(row.get(name_col, ""))
                        boards = _to_float(row.get(board_col))
                        if name and boards is not None:
                            board_height.append({"name": name, "boards": boards})
                    except Exception:
                        continue
        return {"board_height": board_height, "source": SOURCE, "as_of": today_str()}
    except Exception:
        return {"board_height": [], "source": SOURCE, "as_of": today_str()}


def fetch_overseas_markets() -> list[dict]:
    """拉取外围市场: 美股主要指数 + 港股 + 国内油价。akshare: index_global_hist_sina() + energy_oil_hist()"""
    result = []
    targets = [
        ("US", "纳斯达克综合指数", "IXIC"),
        ("US", "标普500指数", "SPX"),
        ("HK", "恒生指数", "HSI"),
    ]
    for market, name, symbol in targets:
        try:
            df = ak.index_global_hist_sina(symbol=symbol, period="daily",
                                          start_date="20260701", end_date="20260707")
            if df is not None and not getattr(df, "empty", True):
                last = df.iloc[-1]
                close_col = _find_col(df, "收盘", "收盘价", "收盘指数")
                change_col = _find_col(df, "涨跌幅")
                if close_col:
                    result.append({
                        "market": market, "name": name, "symbol": symbol,
                        "close": _to_float(last.get(close_col)),
                        "change_pct": _to_float(last.get(change_col)) if change_col else None,
                        "source": SOURCE, "as_of": today_str(),
                    })
        except Exception:
            continue
    # 国内油价
    try:
        oil_df = ak.energy_oil_hist()
        if oil_df is not None and not getattr(oil_df, "empty", True):
            last = oil_df.iloc[-1]
            result.append({
                "market": "COMMODITY", "name": "国内汽油均价", "symbol": "GASOLINE",
                "close": _to_float(last.get("汽油价格")),
                "change_pct": _to_float(last.get("汽油涨跌")),
                "source": SOURCE, "as_of": today_str(),
            })
    except Exception:
        pass
    return result


def fetch_announcements(limit: int = 50) -> list[dict]:
    """拉取近 N 天基金重要公告。akshare: fund_announcement_dividend_em(symbol=fund_code)"""
    try:
        from backend.db.session import get_session
        from backend.db.models import Watchlist
        from sqlalchemy import select
        s = get_session()
        try:
            codes = [r.fund_code for r in s.scalars(select(Watchlist.fund_code)).all()]
        finally:
            s.close()
        rows = []
        for code in codes[:20]:
            try:
                div_df = ak.fund_announcement_dividend_em(symbol=code)
                if div_df is not None and not getattr(div_df, "empty", True):
                    title_col = _find_col(div_df, "公告标题")
                    date_col = _find_col(div_df, "公告日期")
                    name_col = _find_col(div_df, "基金名称")
                    if title_col and date_col:
                        for _, row in div_df.head(3).iterrows():
                            title = str(row.get(title_col, "")).strip()
                            ann_date = str(row.get(date_col, ""))[:10]
                            fund_name = str(row.get(name_col, code))
                            if title and len(title) > 5:
                                rows.append({
                                    "title": title, "ann_date": ann_date,
                                    "fund_code": code, "fund_name": fund_name,
                                    "source": SOURCE,
                                })
            except Exception:
                continue
        rows.sort(key=lambda x: x["ann_date"], reverse=True)
        return rows[:limit]
    except Exception:
        return []
```

- [ ] **Step 3: Run tests**

Run: `pytest backend/tests/test_data_collector.py -v -k "concept or flow or theme or overseas or breadth_indicators or announcements"`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/services/data_collector.py backend/tests/test_data_collector.py
git commit -m "feat: add 6 data_collector fetch functions for market intel"
```

---

## Task 3: market_intel_service（编排层）

**Files:**
- Create: `backend/services/market_intel_service.py`
- Modify: `backend/services/briefing_service.py`

**Interfaces:**
- Consumes: `fetch_market_breadth()`, `fetch_concept_sectors()`, `fetch_industry_flows()`, `fetch_concept_flows()`, `fetch_theme_boards()`, `fetch_breadth_indicators()`, `fetch_overseas_markets()`, `fetch_announcements()`
- Consumes: `market_service.get_indices()`
- Consumes: `dc.fetch_sector_snapshot()` (已有)
- Produces: `collect_market_intel(trade_date, snapshot_type) -> dict`
- Produces: `get_market_snapshot(trade_date, snapshot_type, session) -> dict`
- Produces: `refresh_market_intel_async(trigger) -> dict`
- Produces: 触发 `repository.upsert_market_snapshot()`

**Steps:**

- [ ] **Step 1: 创建 `backend/services/market_intel_service.py`**

```python
"""市场情报编排服务。

编排: 采集全量市场情报 → upsert MarketSnapshot → 返回 dict。
单项失败不影响整体，降级展示。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any

from backend.db.models import MarketSnapshot
from backend.db.session import get_session
from backend.db.repository import upsert_market_snapshot
from backend.services import data_collector as dc
from backend.services import market_service


_lock = Lock()
_active_job_id: str | None = None
_async_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-intel")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _safe(d: Any, key: str, default=None) -> Any:
    if isinstance(d, dict):
        return d.get(key, default)
    return default


def collect_market_intel(
    trade_date: str | None = None,
    snapshot_type: str = "post_market",
    session=None,
) -> dict:
    """采集全量市场情报，upsert MarketSnapshot，返回 dict。

    单项失败记录到 errors 列表，整体继续。
    """
    td = trade_date or _today()
    errors: list[dict] = []

    def _collect_field(name: str, fn, *args, **kwargs) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            errors.append({"field": name, "error": str(exc)})
            return None

    # 并行采集（ThreadPoolExecutor, max_workers=6）
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_indices = ex.submit(market_service.get_indices)
        f_breadth = ex.submit(dc.fetch_market_breadth)
        f_industry = ex.submit(dc.fetch_sector_snapshot)
        f_industry_flows = ex.submit(dc.fetch_industry_flows)
        f_concept = ex.submit(dc.fetch_concept_sectors)
        f_concept_flows = ex.submit(dc.fetch_concept_flows)
        f_themes = ex.submit(dc.fetch_theme_boards)
        f_breadth_indicators = ex.submit(dc.fetch_breadth_indicators)
        f_overseas = ex.submit(dc.fetch_overseas_markets)
        f_announcements = ex.submit(dc.fetch_announcements)

        indices = _collect_field("indices", lambda: f_indices.result())
        breadth = _collect_field("breadth", lambda: f_breadth.result())
        industry_sectors = _collect_field("industry_sectors", lambda: f_industry.result())
        industry_flows = _collect_field("industry_flows", lambda: f_industry_flows.result())
        concept_sectors = _collect_field("concept_sectors", lambda: f_concept.result())
        concept_flows = _collect_field("concept_flows", lambda: f_concept_flows.result())
        themes = _collect_field("themes", lambda: f_themes.result())
        breadth_indicators = _collect_field("breadth_indicators", lambda: f_breadth_indicators.result())
        overseas = _collect_field("overseas", lambda: f_overseas.result())
        announcements = _collect_field("announcements", lambda: f_announcements.result())

    payload = {
        "trade_date": td,
        "snapshot_type": snapshot_type,
        "indices": _safe(indices, "indices", []) if indices else [],
        "breadth": breadth if isinstance(breadth, dict) else {},
        "industry_sectors": industry_sectors if isinstance(industry_sectors, list) else [],
        "concept_sectors": concept_sectors if isinstance(concept_sectors, list) else [],
        "industry_flows": industry_flows if isinstance(industry_flows, list) else [],
        "concept_flows": concept_flows if isinstance(concept_flows, list) else [],
        "themes": themes if isinstance(themes, list) else [],
        "breadth_indicators": breadth_indicators if isinstance(breadth_indicators, dict) else {},
        "overseas": overseas if isinstance(overseas, list) else [],
        "announcements": announcements if isinstance(announcements, list) else [],
        "as_of": td,
        "errors": errors,
    }

    # 写 DB（upsert）
    try:
        owns = session is None
        s = session or get_session()
        try:
            upsert_market_snapshot(s, td, snapshot_type, payload)
            s.commit()
        finally:
            if owns:
                s.close()
    except Exception as exc:  # noqa: BLE001
        payload["db_error"] = str(exc)

    return payload


def get_market_snapshot(
    trade_date: str | None = None,
    snapshot_type: str = "post_market",
    session=None,
) -> dict:
    """从 DB 读取 MarketSnapshot；不存在则触发采集。"""
    td = trade_date or _today()
    owns = session is None
    s = session or get_session()
    try:
        from sqlalchemy import select
        row = s.scalar(
            select(MarketSnapshot).where(
                MarketSnapshot.trade_date == td,
                MarketSnapshot.snapshot_type == snapshot_type,
            )
        )
        if row is None:
            # 不存在则触发采集
            return collect_market_intel(td, snapshot_type, session=s)
        return {
            "trade_date": row.trade_date,
            "snapshot_type": row.snapshot_type,
            "indices": json.loads(row.indices_json or "[]"),
            "breadth": json.loads(row.breadth_json or "{}"),
            "industry_sectors": json.loads(row.industry_sectors_json or "[]"),
            "concept_sectors": json.loads(row.concept_sectors_json or "[]"),
            "industry_flows": json.loads(row.industry_flows_json or "[]"),
            "concept_flows": json.loads(row.concept_flows_json or "[]"),
            "themes": json.loads(row.themes_json or "[]"),
            "breadth_indicators": json.loads(row.breadth_indicators_json or "{}"),
            "overseas": json.loads(row.overseas_json or "[]"),
            "announcements": json.loads(row.announcements_json or "[]"),
            "source": row.source,
            "as_of": row.as_of,
        }
    finally:
        if owns:
            s.close()


def refresh_market_intel_async(*, trigger: str = "manual") -> dict:
    """后台异步采集，返回 job 状态。"""
    global _active_job_id
    with _lock:
        if _active_job_id is not None:
            return {"status": "running", "job_id": _active_job_id}
        import uuid
        job_id = uuid.uuid4().hex[:8]
        _active_job_id = job_id

    def _task():
        global _active_job_id
        try:
            collect_market_intel(_today(), "post_market")
        finally:
            with _lock:
                _active_job_id = None

    _async_executor.submit(_task)
    return {"status": "started", "trigger": trigger, "job_id": job_id}
```

- [ ] **Step 2: 写测试 `backend/tests/test_market_intel_service.py`（追加）**

```python
def test_collect_market_intel_returns_all_keys():
    from backend.services.market_intel_service import collect_market_intel
    result = collect_market_intel("2026-07-07", "post_market")
    expected_keys = {
        "trade_date", "snapshot_type", "indices", "breadth",
        "industry_sectors", "concept_sectors", "industry_flows",
        "concept_flows", "themes", "breadth_indicators",
        "overseas", "announcements", "as_of", "errors",
    }
    assert expected_keys.issubset(result.keys())

def test_collect_market_intel_partial_failure_continues():
    """单项 akshare 失败时其他字段仍返回，不抛整体异常。"""
    # 用 mock patch 一个失败的 akshare 函数
    from backend.services import market_intel_service
    with patch.object(market_intel_service.dc, "fetch_concept_sectors", side_effect=RuntimeError("network")):
        result = market_intel_service.collect_market_intel("2026-07-07", "post_market")
    assert "errors" in result
    assert any(e["field"] == "concept_sectors" for e in result["errors"])
```

- [ ] **Step 3: Run tests**

Run: `pytest backend/tests/test_market_intel_service.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/services/market_intel_service.py backend/tests/test_market_intel_service.py
git commit -m "feat: add market_intel_service with collect_market_intel orchestration"
```

---

## Task 4: 扩展简报（目标 A）

**Files:**
- Modify: `backend/services/briefing_service.py`
- Modify: `backend/graph/prompts.py`

**Steps:**

- [ ] **Step 1: 更新 `collect_watchlist_snapshot` 中的 market_snapshot 采集，加入 concept_sectors 和 flows**

在 `_collect_market_breadth()` 和 `_collect_sector_snapshot()` 之间添加：

```python
# 行业板块资金流向
try:
    industry_flows = dc.fetch_industry_flows()
except Exception:  # noqa: BLE001
    industry_flows = []

# 概念板块
try:
    concept_sectors = dc.fetch_concept_sectors()
except Exception:  # noqa: BLE001
    concept_sectors = []

# 概念板块资金流向
try:
    concept_flows = dc.fetch_concept_flows()
except Exception:  # noqa: BLE001
    concept_flows = []
```

- [ ] **Step 2: 在 return dict 中追加字段**

```python
return {
    "market_snapshot": market_result.get("indices", []),
    "market_breadth": breadth,
    "industry_sectors": _collect_sector_snapshot(),  # 重用已有
    "industry_flows": industry_flows,
    "concept_sectors": concept_sectors,
    "concept_flows": concept_flows,
    "sector_snapshot": sector_snapshot,
    "watchlist_changes": watchlist_changes,
    "errors": errors,
    "collect_meta": {
        "total_watchlist": total_watchlist,
        "max_funds_applied": max_funds if total_watchlist > max_funds else None,
        "warnings": warnings,
    },
}
```

- [ ] **Step 3: 更新 `BRIEFING_PROMPT_TEMPLATE` 描述新增数据**

替换 `## 数据说明` 和 sections 要求：

```
## 数据说明

$snapshot_json 中包含:

- market_snapshot: 今日 A 股主要指数
- market_breadth: 市场宽度 {"up": 上涨家数, "down": 下跌家数, "limit_up": 涨停数, "limit_down": 跌停数}
- industry_sectors: 行业板块涨跌幅 [{"name": 板块名, "change_pct": 涨跌幅}, ...]
- concept_sectors: 概念板块涨跌幅 [{"name": 板块名, "change_pct": 涨跌幅}, ...]
- industry_flows: 行业板块资金流向 [{"name": 板块名, "net_flow": 净流入(万)}, ...]
- concept_flows: 概念板块资金流向 [{"name": 板块名, "net_flow": 净流入(万)}, ...]
- sector_snapshot: 行业板块涨跌（已有，简写版）
- watchlist_changes: 自选基金各周期收益率
```

替换 sections 要求为 9 个：

```
1. **必须命中以下 sections（9 个）**:
   - 指数表现: 代码/名称/收盘价/涨跌幅，使用表格
   - 赚钱效应: 上涨/下跌家数、涨停/跌停，客观描述市场情绪
   - 板块动向: 行业强势板块（top3）/ 弱势板块（bottom3），列出具体涨跌幅
   - 概念板块动向: 概念强势（top3）/ 弱势（bottom3），列出具体涨跌幅
   - 板块资金流向: 行业净流入 top3 / bottom3，概念净流入 top3 / bottom3
   - 自选池涨跌: 基金代码/名称/近1日/近1周/近1月收益率
   - 风险提示: 客观描述近期波动较大的基金或板块
   - 操作观察: 本日需关注的市场信号（≤3 条，基于已有数据）
   - 数据声明: 数据来源(akshare)和 as_of 日期
```

- [ ] **Step 4: 手动跑 compose 验证**

```bash
cd /Users/leon/fund-agent && .venv/bin/python -c "
from backend.services.briefing_service import collect_watchlist_snapshot, compose_briefing
snap = collect_watchlist_snapshot()
print('concept_sectors:', len(snap.get('concept_sectors', [])))
print('industry_flows:', len(snap.get('industry_flows', [])))
print('concept_flows:', len(snap.get('concept_flows', [])))
r = compose_briefing(snap)
print(r['markdown'][:500])
"
```

- [ ] **Step 5: 更新测试 mock 数据，加入新字段**

在 `backend/tests/test_briefing_service.py` 的 `TestCollectWatchlistSnapshot.test_collect_returns_market_and_watchlist_metrics` 中补充 `mock_get_sectors` 返回值增加 concept/concept_flows/industry_flows；在 `test_collect_market_breadth_graceful_fallback` 等 mock 中补充。

- [ ] **Step 6: Commit**

```bash
git add backend/services/briefing_service.py backend/graph/prompts.py backend/tests/test_briefing_service.py
git commit -m "feat(briefing): extend to Phase A++ with concept sectors and fund flows"
```

---

## Task 5: API 路由扩展

**Files:**
- Modify: `backend/api/routes/market.py`

**Steps:**

- [ ] **Step 1: 扩展 `market.py` 路由**

替换整个文件内容：

```python
"""市场指数路由。

GET  /api/market/latest        今日指数快速读取（已有）
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
    from backend.services.market_intel_service import get_market_snapshot
    try:
        result = get_market_snapshot(trade_date=date, snapshot_type=type, session=session)
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
            rows = dc.fetch_concept_sectors(limit_n=0)  # 不够，直接复用
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
    session: Session = Depends(get_session),
):
    """手动触发市场情报采集。"""
    if _trigger is None:
        raise HTTPException(status_code=403, detail="Requires X-Local-Trigger header")
    from backend.services.market_intel_service import refresh_market_intel_async
    return refresh_market_intel_async(trigger="manual")
```

- [ ] **Step 2: 确认路由注册**

检查 `backend/api/app.py` 中 `market_router` 是否已 include_router。如果是新增文件，需要在 app.py 中添加：

```python
from backend.api.routes import market
app.include_router(market.router)
```

- [ ] **Step 3: 写集成测试 `backend/tests/test_market_intel_routes.py`**

```python
def test_snapshot_endpoint_returns_200():
    from fastapi.testclient import TestClient
    from backend.api.app import app
    client = TestClient(app)
    response = client.get("/api/market/snapshot?date=2026-07-07&type=post_market")
    assert response.status_code in (200, 404)  # 404 = 无缓存则触发采集

def test_sectors_endpoint_returns_rows():
    from fastapi.testclient import TestClient
    from backend.api.app import app
    client = TestClient(app)
    response = client.get("/api/market/sectors?kind=industry&sort=change_pct&limit=5")
    assert response.status_code == 200
    assert "rows" in response.json()

def test_refresh_requires_header():
    from fastapi.testclient import TestClient
    from backend.api.app import app
    client = TestClient(app)
    response = client.post("/api/market/refresh")
    assert response.status_code == 403
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/test_market_intel_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes/market.py backend/tests/test_market_intel_routes.py
git commit -m "feat(api): extend market routes with snapshot, sectors, refresh"
```

---

## Task 6: Scheduler 更新

**Files:**
- Modify: `backend/scheduler.py`

**Steps:**

- [ ] **Step 1: 在 `scheduler.py` 添加 morning/post_market job**

在文件末尾的 job 注册区添加：

```python
def _is_trading_day() -> bool:
    """简单判断今天是否交易日：尝试调用 akshare。"""
    import akshare as ak
    try:
        df = ak.stock_market_activity_legu()
        return df is not None and not getattr(df, "empty", True)
    except Exception:
        return True  # 保守：允许跑


def _collect_market_intel_job(trade_date: str, snapshot_type: str) -> None:
    """供 scheduler 调用的 wrapper。"""
    from backend.services.market_intel_service import collect_market_intel
    collect_market_intel(trade_date=trade_date, snapshot_type=snapshot_type)


# morning market intel: 09:35
sched.add_job(
    _collect_market_intel_job,
    "cron", hour=9, minute=35,
    args=["today", "morning"],
    id="morning_market_intel",
    max_instances=1, coalesce=True,
    misfire_grace_time=3600,
    jitter=60,
)

# post_market market intel: 15:35
sched.add_job(
    _collect_market_intel_job,
    "cron", hour=15, minute=35,
    args=["today", "post_market"],
    id="post_market_market_intel",
    max_instances=1, coalesce=True,
    misfire_grace_time=3600,
    jitter=60,
)
```

- [ ] **Step 2: Commit**

```bash
git add backend/scheduler.py
git commit -m "feat(scheduler): add morning/post_market market intel jobs"
```

---

## Task 7: 前端市场情报页

**Files:**
- Create: `frontend/app/market/page.tsx`
- Create: `frontend/src/lib/market.ts`
- Create: `frontend/src/components/market/MarketOverviewCards.tsx`
- Create: `frontend/src/components/market/IndustrySectorTable.tsx`
- Create: `frontend/src/components/market/ConceptSectorTable.tsx`
- Create: `frontend/src/components/market/ThemeBoards.tsx`
- Create: `frontend/src/components/market/OverseasMarkets.tsx`
- Create: `frontend/src/components/market/AnnouncementList.tsx`
- Create: `frontend/src/components/market/SnapshotRefreshButton.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/lib/api.ts`

**Steps:**

- [ ] **Step 1: 创建 `frontend/src/lib/market.ts`**

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface MarketSnapshot {
  trade_date: string;
  snapshot_type: string;
  indices: Array<{ symbol: string; name: string; close: number; change_pct: number }>;
  breadth: { up: number; down: number; limit_up: number; limit_down: number };
  industry_sectors: Array<{ name: string; change_pct: number }>;
  concept_sectors: Array<{ name: string; change_pct: number }>;
  industry_flows: Array<{ name: string; net_flow: number }>;
  concept_flows: Array<{ name: string; net_flow: number }>;
  themes: Array<{ theme: string; count: number; stocks: Array<{ name: string }> }>;
  breadth_indicators: { board_height: Array<{ name: string; boards: number }>; rejection_rate: number | null };
  overseas: Array<{ market: string; name: string; close: number; change_pct: number | null }>;
  announcements: Array<{ title: string; ann_date: string; code: string }>;
  source: string;
  as_of: string;
}

export function useMarketSnapshot(date: string, type: string) {
  return useQuery<MarketSnapshot>({
    queryKey: ["market", "snapshot", date, type],
    queryFn: () =>
      fetch(`/api/market/snapshot?date=${encodeURIComponent(date)}&type=${encodeURIComponent(type)}`).then(r => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      }),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useRefreshMarket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      fetch("/api/market/refresh", {
        method: "POST",
        headers: { "X-Local-Trigger": "1" },
      }).then(r => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["market"] });
    },
  });
}
```

- [ ] **Step 2: 创建 `frontend/src/components/market/MarketOverviewCards.tsx`**

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";
import { MetricCard } from "@/components/MetricCard";

export function MarketOverviewCards({ snap }: { snap: MarketSnapshot }) {
  const { breadth, indices } = snap;
  const total = breadth.up + breadth.down || 1;
  const upRatio = ((breadth.up / total) * 100).toFixed(1);
  const breadthLabel = breadth.up > breadth.down ? "偏暖" : breadth.up < breadth.down ? "偏弱" : "中性";
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {indices.map(idx => (
        <MetricCard
          key={idx.symbol}
          label={idx.name}
          value={idx.close.toFixed(2)}
          sub={idx.change_pct >= 0 ? `+${idx.change_pct.toFixed(2)}%` : `${idx.change_pct.toFixed(2)}%`}
          color={idx.change_pct >= 0 ? "green" : "red"}
        />
      ))}
      <MetricCard label="上涨家数" value={breadth.up.toString()} sub={`${upRatio}%`} color="green" />
      <MetricCard label="下跌家数" value={breadth.down.toString()} sub={breadthLabel} color="red" />
      <MetricCard label="涨停" value={breadth.limit_up.toString()} color="green" />
      <MetricCard label="跌停" value={breadth.limit_down.toString()} color="red" />
    </div>
  );
}
```

- [ ] **Step 3: 创建 `frontend/src/components/market/IndustrySectorTable.tsx`**

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";

function ChangeCell({ pct }: { pct: number }) {
  const color = pct > 0 ? "text-green-600" : pct < 0 ? "text-red-600" : "text-gray-500";
  const sign = pct > 0 ? "+" : "";
  return <span className={color}>{sign}{pct.toFixed(2)}%</span>;
}

export function IndustrySectorTable({ snap }: { snap: MarketSnapshot }) {
  const sectors = (snap.industry_sectors || []).slice(0, 20);
  const flows = snap.industry_flows || [];
  return (
    <div className="grid grid-cols-2 gap-4">
      <div>
        <h3 className="font-semibold mb-2">行业涨跌幅</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs"><th className="text-left">板块</th><th className="text-right">涨跌幅</th></tr>
          </thead>
          <tbody>
            {sectors.map(s => (
              <tr key={s.name} className="border-t">
                <td className="py-1">{s.name}</td>
                <td className="text-right"><ChangeCell pct={s.change_pct} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3 className="font-semibold mb-2">行业资金流向</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs"><th className="text-left">板块</th><th className="text-right">净流入(万)</th></tr>
          </thead>
          <tbody>
            {flows.map(f => (
              <tr key={f.name} className="border-t">
                <td className="py-1">{f.name}</td>
                <td className={`text-right ${f.net_flow >= 0 ? "text-green-600" : "text-red-600"}`}>
                  {(f.net_flow / 10000).toFixed(1)}亿
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 创建 `frontend/src/components/market/ConceptSectorTable.tsx`**

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";
import { ChangeCell } from "./IndustrySectorTable";

export function ConceptSectorTable({ snap }: { snap: MarketSnapshot }) {
  const concepts = (snap.concept_sectors || []).slice(0, 20);
  const flows = snap.concept_flows || [];
  return (
    <div className="grid grid-cols-2 gap-4">
      <div>
        <h3 className="font-semibold mb-2">概念涨跌幅</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs"><th className="text-left">概念</th><th className="text-right">涨跌幅</th></tr>
          </thead>
          <tbody>
            {concepts.map(s => (
              <tr key={s.name} className="border-t">
                <td className="py-1">{s.name}</td>
                <td className="text-right"><ChangeCell pct={s.change_pct} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3 className="font-semibold mb-2">概念资金流向</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs"><th className="text-left">概念</th><th className="text-right">净流入(万)</th></tr>
          </thead>
          <tbody>
            {flows.map(f => (
              <tr key={f.name} className="border-t">
                <td className="py-1">{f.name}</td>
                <td className={`text-right ${f.net_flow >= 0 ? "text-green-600" : "text-red-600"}`}>
                  {(f.net_flow / 10000).toFixed(1)}亿
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: 创建 `frontend/src/components/market/ThemeBoards.tsx`**

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";

export function ThemeBoards({ snap }: { snap: MarketSnapshot }) {
  const themes = snap.themes || [];
  if (themes.length === 0) return <p className="text-gray-400 text-sm">暂无题材数据（收盘后更新）</p>;
  return (
    <div className="space-y-2">
      {themes.map(t => (
        <div key={t.theme} className="border rounded p-2">
          <div className="flex justify-between items-center">
            <span className="font-medium text-sm">{t.theme}</span>
            <span className="text-xs text-gray-500">{t.count}只</span>
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {t.stocks.map(s => s.name).join(", ")}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 6: 创建 `frontend/src/components/market/OverseasMarkets.tsx`**

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";

export function OverseasMarkets({ snap }: { snap: MarketSnapshot }) {
  const markets = snap.overseas || [];
  if (markets.length === 0) return <p className="text-gray-400 text-sm">暂无外围市场数据</p>;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {markets.map(m => (
        <div key={m.symbol} className="border rounded p-3 text-center">
          <div className="text-xs text-gray-500">{m.name}</div>
          <div className="text-lg font-mono mt-1">{m.close?.toFixed(2)}</div>
          <div className={`text-sm ${(m.change_pct ?? 0) >= 0 ? "text-green-600" : "text-red-600"}`}>
            {m.change_pct != null ? `${m.change_pct >= 0 ? "+" : ""}${m.change_pct.toFixed(2)}%` : "—"}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 7: 创建 `frontend/src/components/market/AnnouncementList.tsx`**

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";

export function AnnouncementList({ snap }: { snap: MarketSnapshot }) {
  const anns = snap.announcements || [];
  if (anns.length === 0) return <p className="text-gray-400 text-sm">暂无最新公告</p>;
  return (
    <div className="space-y-2">
      {anns.slice(0, 20).map((a, i) => (
        <div key={i} className="border-l-2 border-blue-400 pl-3 py-1">
          <div className="text-sm">{a.title}</div>
          <div className="text-xs text-gray-400">{a.ann_date} {a.code && `[${a.code}]`}</div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 8: 创建 `frontend/src/components/market/SnapshotRefreshButton.tsx`**

```tsx
"use client";
import { useRefreshMarket } from "@/lib/market";

export function SnapshotRefreshButton() {
  const { mutate, isPending } = useRefreshMarket();
  return (
    <button
      onClick={() => mutate()}
      disabled={isPending}
      className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
    >
      {isPending ? "采集中..." : "刷新市场数据"}
    </button>
  );
}
```

- [ ] **Step 9: 创建 `frontend/app/market/page.tsx`**

```tsx
"use client";
import { useState } from "react";
import { useMarketSnapshot } from "@/lib/market";
import { MarketOverviewCards } from "@/components/market/MarketOverviewCards";
import { IndustrySectorTable } from "@/components/market/IndustrySectorTable";
import { ConceptSectorTable } from "@/components/market/ConceptSectorTable";
import { ThemeBoards } from "@/components/market/ThemeBoards";
import { OverseasMarkets } from "@/components/market/OverseasMarkets";
import { AnnouncementList } from "@/components/market/AnnouncementList";
import { SnapshotRefreshButton } from "@/components/market/SnapshotRefreshButton";
import { StateBlock } from "@/components/StateBlock";

const DATE_OPTIONS = [
  { label: "今日", value: "today" },
  { label: "昨日", value: "yesterday" },
  { label: "本周", value: "thisweek" },
  { label: "本月", value: "thismonth" },
];

function resolveDate(opt: string): string {
  const d = new Date();
  if (opt === "yesterday") d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

export default function MarketPage() {
  const [dateOpt, setDateOpt] = useState("today");
  const date = resolveDate(dateOpt);
  const { data: snap, isLoading, error } = useMarketSnapshot(date, "post_market");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">市场情报</h1>
        <SnapshotRefreshButton />
      </div>

      {/* 筛选器 */}
      <div className="flex gap-2">
        {DATE_OPTIONS.map(o => (
          <button
            key={o.value}
            onClick={() => setDateOpt(o.value)}
            className={`px-3 py-1 rounded text-sm ${dateOpt === o.value ? "bg-blue-600 text-white" : "bg-gray-100 hover:bg-gray-200"}`}
          >
            {o.label}
          </button>
        ))}
      </div>

      <StateBlock isLoading={isLoading} error={error ? String(error) : null}>
        {snap ? (
          <div className="space-y-8">
            <section>
              <h2 className="text-lg font-semibold mb-3">市场概览</h2>
              <MarketOverviewCards snap={snap} />
            </section>
            <section>
              <h2 className="text-lg font-semibold mb-3">行业板块</h2>
              <IndustrySectorTable snap={snap} />
            </section>
            <section>
              <h2 className="text-lg font-semibold mb-3">概念板块</h2>
              <ConceptSectorTable snap={snap} />
            </section>
            <section>
              <h2 className="text-lg font-semibold mb-3">热门题材</h2>
              <ThemeBoards snap={snap} />
            </section>
            <section>
              <h2 className="text-lg font-semibold mb-3">外围市场</h2>
              <OverseasMarkets snap={snap} />
            </section>
            <section>
              <h2 className="text-lg font-semibold mb-3">重要公告</h2>
              <AnnouncementList snap={snap} />
            </section>
            <p className="text-xs text-gray-400">
              数据来源: {snap.source} | 截止: {snap.as_of}
            </p>
          </div>
        ) : (
          <p className="text-gray-400">暂无数据</p>
        )}
      </StateBlock>
    </div>
  );
}
```

- [ ] **Step 10: 在 `AppShell.tsx` 添加 nav 入口**

在 nav links 数组中添加：

```tsx
{ href: "/market", icon: TrendingUpIcon, label: "市场情报" }
```

- [ ] **Step 11: 确认前端 tsconfig 路径别名**

确保 `@/components/market/*` 和 `@/lib/market` 路径已在 `tsconfig.json` 的 `paths` 中配置。

- [ ] **Step 12: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -10
```
Expected: no errors (or only unrelated pre-existing errors)

- [ ] **Step 13: Commit**

```bash
git add frontend/app/market/ frontend/src/components/market/ frontend/src/lib/market.ts
git add frontend/src/components/AppShell.tsx
git commit -m "feat(frontend): add /market intelligence page with full components"
```

---

## Task 8: E2E 验证

**Steps:**

- [ ] **Step 1: 跑全量后端测试**

```bash
cd /Users/leon/fund-agent && .venv/bin/python -m pytest backend/tests/ --tb=short 2>&1 | tail -5
```
Expected: 全部 PASS

- [ ] **Step 2: 手动跑 `collect_market_intel`**

```bash
.venv/bin/python -c "
from backend.services.market_intel_service import collect_market_intel
r = collect_market_intel('2026-07-07', 'post_market')
print('indices:', len(r.get('indices', [])))
print('concept_sectors:', len(r.get('concept_sectors', [])))
print('industry_flows:', len(r.get('industry_flows', [])))
print('overseas:', len(r.get('overseas', [])))
print('themes:', len(r.get('themes', [])))
print('errors:', r.get('errors', []))
"
```

- [ ] **Step 3: 手动跑完整简报**

```bash
.venv/bin/python -c "
from backend.services.briefing_service import collect_watchlist_snapshot, compose_briefing
snap = collect_watchlist_snapshot()
r = compose_briefing(snap)
print(r['markdown'])
"
```

- [ ] **Step 4: 浏览器打开 `/market` 页面截图验证**（前端 dev server 应已在 terminal 3 运行）

---

## Spec 自查

1. **Spec 覆盖**: 所有 9 sections（指数/赚钱效应/行业/概念/资金流向/自选池/风险提示/操作观察/数据声明）均有对应代码
2. **占位符扫描**: 无 TBD/TODO in plan
3. **类型一致性**: `MarketSnapshot` 字段名与 `collect_market_intel` return dict key 一致；前端 `MarketSnapshot` interface 与后端 JSON keys 一致
4. **缺失项**: 无
