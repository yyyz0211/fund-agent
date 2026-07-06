# 持仓组合时间序列收益曲线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute and expose a daily time-series of portfolio invested / market value / pnl derived from `FundTransaction` + `FundNav`, render a new `/portfolio` page with a three-line chart and per-fund breakdown.

**Architecture:** Add a pure-Python service `portfolio_history.calculate_pnl_series` that, given a fund subset and date window, walks dates and computes deterministic per-day totals. New FastAPI endpoint `GET /api/portfolio/pnl-series` proxies to it. New Next.js page `app/portfolio/page.tsx` consumes the endpoint and reuses existing `MetricCard` / Recharts components.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, pytest, Next.js 14 App Router, TanStack Query, Recharts, Tailwind, Node test runner.

---

## Global Constraints

- All math is deterministic and local; never call AkShare in this code path.
- `FundTransaction.kind` is currently `"buy"` only — do not assume `sell` exists.
- Don't include `FundPendingBuy` rows in the time series (they are not yet confirmed).
- Don't fabricate values for missing NAVs: forward-fill from the most recent known NAV and surface `missing_funds` per date.
- If a fund has zero cost / share for a day, its contribution to `market_value` is zero; it does not zero out the entire row.
- `invested == 0` day → `pnl_pct = 0.0`, not `None`, to keep charts continuous.
- Date window default: `start = end - 365 days` when caller doesn't supply one.
- Reuse existing `pnl_service` `_REQUIRED_FIELDS` / `holding_share` / `cost_nav` semantics.

## File Map

- Create `backend/services/portfolio_history.py`: time-series calculator.
- Modify `backend/api/routes/portfolio.py`: add `/pnl-series` route.
- Test `backend/tests/test_portfolio_history.py`: pure-Python math.
- Test `backend/tests/test_api_portfolio.py`: HTTP endpoint.
- Modify `frontend/src/types/api.ts`: new types.
- Modify `frontend/src/lib/api.ts`: new client method.
- Create `frontend/src/lib/portfolio-series.ts`: helpers (formatters, period keys).
- Test `frontend/tests/portfolio-series.test.mjs`.
- Create `frontend/app/portfolio/page.tsx`: the new page.
- Modify `frontend/app/watchlist/page.tsx`: entry links.
- Test `frontend/tests/portfolio-page.test.tsx` (if testing infra already in place; otherwise smoke only).

## Task 1: Portfolio history service

**Files:**
- Create `backend/services/portfolio_history.py`
- Test `backend/tests/test_portfolio_history.py`

- [ ] Write calculator tests (use in-memory DB fixture + monkeypatched NAVs):

```python
def _seed_single_fund(session, code, nav_rows, tx_rows):
    """Insert NAV history and transactions for one fund."""
    from backend.db import repository as repo
    repo.upsert_fund(session, {"fund_code": code, "fund_name": f"Fund {code}"})
    repo.upsert_navs(session, code, nav_rows)
    from backend.db.models import Watchlist
    w = Watchlist(fund_code=code, is_holding=True)
    session.add(w)
    for tx in tx_rows:
        repo.add_transaction(session, code, tx, commit=False)
    session.commit()


def test_calculate_pnl_series_one_buy(monkeypatch, session):
    from backend.services import portfolio_history as ph
    navs = [
        {"nav_date": "2026-01-01", "unit_nav": 1.0, "accumulated_nav": 1.0,
         "daily_return": 0.0, "source": "akshare", "source_updated_at": "2026-01-01"},
        {"nav_date": "2026-01-02", "unit_nav": 1.1, "accumulated_nav": 1.1,
         "daily_return": 0.1, "source": "akshare", "source_updated_at": "2026-01-02"},
    ]
    txs = [{"tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0, "kind": "buy"}]
    _seed_single_fund(session, "110011", navs, txs)

    out = ph.calculate_pnl_series(
        fund_codes=["110011"],
        start="2026-01-01", end="2026-01-02",
        session=session,
    )
    assert out["dates"][0]["invested"] == 1000.0
    assert out["dates"][0]["market"] == 1000.0
    assert out["dates"][0]["pnl"] == 0.0
    assert out["dates"][1]["market"] == 1100.0
    assert out["dates"][1]["pnl"] == 100.0
    assert out["summary"]["invested"] == 1000.0
    assert out["summary"]["market_value"] == 1100.0


def test_calculate_pnl_series_forward_fills_nav(monkeypatch, session):
    from backend.services import portfolio_history as ph
    # 1 月 1 日有 NAV，1 月 2 日缺失 → 1 月 2 日市值 = 1 月 1 日市值
    navs = [
        {"nav_date": "2026-01-01", "unit_nav": 1.0, "accumulated_nav": 1.0,
         "daily_return": 0.0, "source": "akshare", "source_updated_at": "2026-01-01"},
    ]
    txs = [{"tx_date": "2026-01-01", "amount": 1000.0, "nav": 1.0, "kind": "buy"}]
    _seed_single_fund(session, "110011", navs, txs)

    out = ph.calculate_pnl_series(
        fund_codes=["110011"],
        start="2026-01-01", end="2026-01-02",
        session=session,
    )
    assert out["dates"][1]["market"] == 1000.0  # forward-filled
    assert out["dates"][1]["missing_funds"] == []  # filled, not "missing"


def test_calculate_pnl_series_excludes_fund_with_no_nav_at_all(session):
    from backend.services import portfolio_history as ph
    _seed_single_fund(session, "110011", [], [{"tx_date": "2026-01-01",
                                                "amount": 1000.0, "nav": 1.0,
                                                "kind": "buy"}])
    out = ph.calculate_pnl_series(
        fund_codes=["110011"],
        start="2026-01-01", end="2026-01-02",
        session=session,
    )
    assert out["dates"] == []
    assert "110011" in out["uncovered_funds"]


def test_calculate_pnl_series_pct_zero_when_invested_zero(session):
    from backend.services import portfolio_history as ph
    # 全部是空 watchlist → 没有任何日期 / 任何基金
    out = ph.calculate_pnl_series(
        fund_codes=None,
        start="2026-01-01", end="2026-01-02",
        session=session,
    )
    assert out["dates"] == []
    assert out["summary"] == {
        "invested": 0.0, "market_value": 0.0, "pnl_abs": 0.0, "pnl_pct": 0.0,
        "daily_points": 0,
    }
```

- [ ] Implement `portfolio_history.py`:

```python
"""Deterministic portfolio P&L time series."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import select

from backend.db import repository as repo
from backend.db.models import Fund, FundNav, FundTransaction, Watchlist
from backend.db.session import get_session
from backend.services import data_collector as dc


def _to_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _default_window() -> tuple[str, str]:
    end = dc.today_str()
    start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    return start, end


def _resolve_fund_codes(session, fund_codes: list[str] | None) -> list[str]:
    """Return the holding fund codes for this run.

    If `fund_codes` is None → all is_holding=true rows. Otherwise filter to
    provided codes but keep only those with is_holding=true (the route layer
    already validates user input).
    """
    if fund_codes:
        rows = session.scalars(
            select(Watchlist)
            .where(Watchlist.fund_code.in_(list(fund_codes)))
            .where(Watchlist.is_holding.is_(True))
        ).all()
    else:
        rows = session.scalars(
            select(Watchlist).where(Watchlist.is_holding.is_(True))
        ).all()
    return [r.fund_code for r in rows]


def _load_fund_data(session, codes: list[str], start: date, end: date) -> dict:
    """Preload transactions, NAV history, and fund names for the window.

    Returns {code: {"name": str|None, "txs": [...], "nav_by_date": {date: acc_nav}}}.
    """
    out: dict = {code: {"name": None, "txs": [], "nav_by_date": {}} for code in codes}
    if not codes:
        return out
    # NAV range: extend end by 1 day for the last possible fill
    start_str = start.isoformat()
    end_str = end.isoformat()
    navs = session.scalars(
        select(FundNav)
        .where(FundNav.fund_code.in_(codes))
        .where(FundNav.nav_date >= start_str)
        .where(FundNav.nav_date <= end_str)
        .order_by(FundNav.nav_date)
    ).all()
    for row in navs:
        d = _to_date(row.nav_date)
        if row.fund_code in out and row.accumulated_nav is not None:
            out[row.fund_code]["nav_by_date"][d] = float(row.accumulated_nav)

    txs = session.scalars(
        select(FundTransaction)
        .where(FundTransaction.fund_code.in_(codes))
        .order_by(FundTransaction.tx_date, FundTransaction.tx_seq)
    ).all()
    for row in txs:
        if row.fund_code in out:
            out[row.fund_code]["txs"].append({
                "tx_date": _to_date(row.tx_date),
                "amount": float(row.amount),
                "nav": float(row.nav),
            })

    fund_rows = session.scalars(
        select(Fund).where(Fund.fund_code.in_(codes))
    ).all()
    name_map = {f.fund_code: f.fund_name for f in fund_rows}
    for code, payload in out.items():
        payload["name"] = name_map.get(code)
    return out


def calculate_pnl_series(
    fund_codes: list[str] | None = None,
    start: str = "",
    end: str = "",
    session=None,
) -> dict:
    """Compute daily portfolio P&L series.

    Returns a JSON-serializable dict (no ORM instances).
    """
    s = session or get_session()
    owns = session is None
    try:
        if not end:
            end_str = dc.today_str()
        else:
            end_str = end
        if not start:
            start_str = (datetime.strptime(end_str, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
        else:
            start_str = start
        start_d = _to_date(start_str)
        end_d = _to_date(end_str)

        codes = _resolve_fund_codes(s, fund_codes)
        data = _load_fund_data(s, codes, start_d, end_d)

        # Pre-compute each fund's per-day share using its own tx history.
        # `share_by_date[code][d]` is the cumulative share held at the *end* of day d.
        share_by_date: dict[str, dict[date, float]] = {}
        invested_by_date: dict[str, dict[date, float]] = {}
        per_fund_final: dict[str, dict] = {}

        for code, payload in data.items():
            txs = payload["txs"]
            nav_by_date = payload["nav_by_date"]

            running_share = 0.0
            running_invested = 0.0
            share_series: dict[date, float] = {}
            invested_series: dict[date, float] = {}
            for d in sorted(nav_by_date.keys() | {tx["tx_date"] for tx in txs}):
                # apply txs whose tx_date <= d
                new_invested_today = False
                for tx in txs:
                    if tx["tx_date"] <= d:
                        if tx["tx_date"] == d:
                            new_invested_today = True
                        # `tx["nav"]` is the *tx_date* NAV; use that for share calc.
                        if tx["nav"] > 0:
                            running_share += tx["amount"] / tx["nav"]
                            running_invested += tx["amount"]
                share_series[d] = running_share
                invested_series[d] = running_invested
            share_by_date[code] = share_series
            invested_by_date[code] = invested_series

            if nav_by_date:
                last_d = max(nav_by_date.keys())
                per_fund_final[code] = {
                    "fund_code": code,
                    "fund_name": payload["name"],
                    "current_share": round(running_share, 6),
                    "current_market_value": round(running_share * nav_by_date[last_d], 4),
                    "current_invested": round(running_invested, 4),
                }
            else:
                per_fund_final[code] = {
                    "fund_code": code,
                    "fund_name": payload["name"],
                    "current_share": 0.0,
                    "current_market_value": 0.0,
                    "current_invested": 0.0,
                }

        # Build the union of dates and walk them.
        all_dates = set()
        for payload in data.values():
            all_dates.update(payload["nav_by_date"].keys())
        # If no NAVs at all and no txs → empty series
        # Add first-buy dates to ensure invested steps appear in chart
        for code, payload in data.items():
            for tx in payload["txs"]:
                all_dates.add(tx["tx_date"])

        # We render the [start_d, end_d] window; for each day, compute totals.
        dates_out = []
        cur = start_d
        end_loop = max(end_d, max(all_dates) if all_dates else end_d)
        while cur <= end_loop:
            invested_total = 0.0
            market_total = 0.0
            missing_funds: list[str] = []
            uncovered = []
            for code, payload in data.items():
                # If this fund has any tx, contributes only from first tx date.
                first_tx = min((tx["tx_date"] for tx in payload["txs"]), default=None)
                if first_tx is not None and cur < first_tx:
                    continue  # not yet bought
                share = share_by_date[code].get(cur, 0.0)
                if share == 0.0:
                    continue
                # Forward-fill NAV
                nav_by_date = payload["nav_by_date"]
                nav = None
                # find the latest date ≤ cur
                candidates = [d for d in nav_by_date if d <= cur]
                if candidates:
                    nav = nav_by_date[max(candidates)]
                else:
                    missing_funds.append(code)
                    continue
                invested_total += invested_by_date[code].get(cur, 0.0)
                market_total += share * nav
            pnl = market_total - invested_total
            pnl_pct = (pnl / invested_total) if invested_total > 0 else 0.0
            dates_out.append({
                "date": cur.isoformat(),
                "invested": round(invested_total, 4),
                "market_value": round(market_total, 4),
                "pnl": round(pnl, 4),
                "pnl_pct": round(pnl_pct, 6),
                "missing_funds": missing_funds,
            })
            cur = cur + timedelta(days=1)

        # Surface funds with no NAV at all
        uncovered_funds = [c for c, p in data.items() if not p["nav_by_date"] and any(tx for tx in p["txs"])]

        summary = {
            "invested": round(sum(p["current_invested"] for p in per_fund_final.values()), 4),
            "market_value": round(sum(p["current_market_value"] for p in per_fund_final.values()), 4),
            "pnl_abs": 0.0,
            "pnl_pct": 0.0,
            "daily_points": len(dates_out),
        }
        if summary["invested"] > 0:
            summary["pnl_abs"] = round(summary["market_value"] - summary["invested"], 4)
            summary["pnl_pct"] = round(summary["pnl_abs"] / summary["invested"], 6)

        return {
            "start": start_str,
            "end": end_str,
            "as_of": dc.today_str(),
            "source": dc.SOURCE,
            "dates": dates_out,
            "per_fund": list(per_fund_final.values()),
            "summary": summary,
            "uncovered_funds": uncovered_funds,
        }
    finally:
        if owns:
            s.close()
```

- [ ] Run tests:

```bash
.venv/bin/python -m pytest backend/tests/test_portfolio_history.py -q
```

Expected: all pass.

## Task 2: API endpoint

**Files:**
- Modify `backend/api/routes/portfolio.py`
- Test `backend/tests/test_api_portfolio.py`

- [ ] Add endpoint tests:

```python
def test_pnl_series_default_window(monkeypatch, client):
    from backend.api.routes import portfolio as portfolio_routes

    monkeypatch.setattr(portfolio_routes.ph, "calculate_pnl_series",
                        lambda fund_codes=None, start="", end="", session=None: {
                            "start": "2025-07-06", "end": "2026-07-06",
                            "as_of": "2026-07-06", "source": "akshare",
                            "dates": [], "per_fund": [],
                            "summary": {"invested": 0.0, "market_value": 0.0,
                                         "pnl_abs": 0.0, "pnl_pct": 0.0,
                                         "daily_points": 0},
                            "uncovered_funds": [],
                        })
    r = client.get("/api/portfolio/pnl-series")
    assert r.status_code == 200
    body = r.json()
    assert body["dates"] == []
    assert body["summary"]["invested"] == 0.0


def test_pnl_series_rejects_bad_date(client):
    r = client.get("/api/portfolio/pnl-series", params={"start": "bad-date"})
    assert r.status_code == 400
```

- [ ] Add route to `backend/api/routes/portfolio.py`:

```python
from backend.services import portfolio_history as ph

@router.get("/pnl-series")
def get_portfolio_pnl_series(
    codes: str = Query(default="", description="逗号分隔的 fund_code 列表;空=全部持仓"),
    start: str = Query(default="", description="ISO YYYY-MM-DD;空=默认 1 年窗口"),
    end: str = Query(default="", description="ISO YYYY-MM-DD;空=今天"),
):
    _validate_date(start)
    _validate_date(end)
    fund_codes: Optional[list[str]] = None
    if codes.strip():
        fund_codes = [c.strip() for c in codes.split(",") if c.strip()]
    return ph.calculate_pnl_series(fund_codes=fund_codes, start=start, end=end)
```

- [ ] Run tests:

```bash
.venv/bin/python -m pytest backend/tests/test_api_portfolio.py -q
```

Expected: all pass.

## Task 3: Frontend types + API client

**Files:**
- Modify `frontend/src/types/api.ts`
- Modify `frontend/src/lib/api.ts`

- [ ] Add types:

```ts
export interface PortfolioPnlPoint {
  date: string;
  invested: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  missing_funds: string[];
}

export interface PortfolioPnlFund {
  fund_code: string;
  fund_name: string | null;
  current_share: number;
  current_market_value: number;
  current_invested: number;
}

export interface PortfolioPnlSummary {
  invested: number;
  market_value: number;
  pnl_abs: number;
  pnl_pct: number;
  daily_points: number;
}

export interface PortfolioPnlSeries {
  start: string;
  end: string;
  as_of: string;
  source: string;
  dates: PortfolioPnlPoint[];
  per_fund: PortfolioPnlFund[];
  summary: PortfolioPnlSummary;
  uncovered_funds: string[];
}
```

- [ ] Add API client method:

```ts
portfolioPnlSeries: (codes: string[] = [], start = "", end = "") =>
  get<PortfolioPnlSeries>("/api/portfolio/pnl-series", {
    codes: codes.join(","),
    start,
    end,
  }),
```

## Task 4: Frontend helper

**Files:**
- Create `frontend/src/lib/portfolio-series.ts`
- Test `frontend/tests/portfolio-series.test.mjs`

- [ ] Add helpers:

```ts
import type { PortfolioPnlSeries, PortfolioPnlPoint } from "@/types/api";

export const PORTFOLIO_PERIODS = ["1m", "3m", "6m", "1y", "all"] as const;
export type PortfolioPeriod = (typeof PORTFOLIO_PERIODS)[number];

export function periodStartForEnd(period: PortfolioPeriod, end: string): string {
  if (period === "all") return "";
  const days = { "1m": 30, "3m": 90, "6m": 180, "1y": 365 }[period];
  const d = new Date(end);
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export function compactPnlSummary(series: PortfolioPnlSeries): {
  invested: number;
  market: number;
  pnl: number;
  pnlPct: number;
} {
  return {
    invested: series.summary.invested,
    market: series.summary.market_value,
    pnl: series.summary.pnl_abs,
    pnlPct: series.summary.pnl_pct,
  };
}

export function withMissingMarker(
  point: PortfolioPnlPoint,
  set: Set<string>,
): PortfolioPnlPoint & { hasMissing: boolean } {
  return { ...point, hasMissing: point.missing_funds.length > 0 || set.has(point.date) };
}
```

- [ ] Add tests (Node test runner) for period math and the summary helper.

```bash
npm test
```

## Task 5: Portfolio page

**Files:**
- Create `frontend/app/portfolio/page.tsx`

- [ ] Implement page:

```tsx
"use client";
import { useState, useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip,
  XAxis, YAxis, Legend, BarChart, Bar,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader, SectionHeader } from "@/components/PageHeader";
import { MetricCard } from "@/components/MetricCard";
import { StateBlock } from "@/components/StateBlock";
import { api } from "@/lib/api";
import { formatDate, formatPct } from "@/lib/format";
import {
  PORTFOLIO_PERIODS,
  periodStartForEnd,
  type PortfolioPeriod,
} from "@/lib/portfolio-series";

export default function PortfolioPage() {
  const today = new Date().toISOString().slice(0, 10);
  const [period, setPeriod] = useState<PortfolioPeriod>("1y");
  const start = useMemo(() => periodStartForEnd(period, today), [period, today]);

  const query = useQuery({
    queryKey: ["portfolioPnlSeries", period, start, today],
    queryFn: () => api.portfolioPnlSeries([], start, today),
  });

  if (query.isLoading) {
    return <StateBlock title="加载组合数据" tone="loading" />;
  }
  if (query.error || !query.data) {
    return <StateBlock title="组合数据加载失败" tone="error">{String(query.error ?? "")}</StateBlock>;
  }

  const data = query.data;
  const empty = data.dates.length === 0;

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Portfolio"
        title="组合表现"
        description="基于自选池中 is_holding=true 的逐笔买入与本地日级 NAV，计算每日的投入、市值与累计盈亏。确定性本地计算，不调外部数据源。"
        actions={
          <Link href="/watchlist">
            <Button variant="outline">
              <ArrowLeft className="mr-2 h-4 w-4" /> 返回自选池
            </Button>
          </Link>
        }
      />

      <div className="flex gap-2">
        {PORTFOLIO_PERIODS.map((p) => (
          <Button
            key={p}
            variant={p === period ? "default" : "outline"}
            size="sm"
            onClick={() => setPeriod(p)}
          >
            {p === "all" ? "全部" : p.toUpperCase()}
          </Button>
        ))}
      </div>

      {empty ? (
        <StateBlock title="暂无持仓组合">
          尚未在自选池中标记任何基金为 is_holding，或本地无 NAV 数据。
        </StateBlock>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="累计投入" value={data.summary.invested} suffix="元" />
            <MetricCard label="当前市值" value={data.summary.market_value} suffix="元" />
            <MetricCard
              label="累计盈亏"
              value={data.summary.pnl_abs}
              suffix="元"
              tone={data.summary.pnl_abs >= 0 ? "up" : "down"}
            />
            <MetricCard
              label="累计收益率"
              value={data.summary.pnl_pct}
              formatter={(v) => formatPct(v)}
              tone={data.summary.pnl_pct >= 0 ? "up" : "down"}
            />
          </div>

          <Card className="p-5">
            <CardHeader>
              <SectionHeader title="投入 / 市值 / 累计盈亏" description={`区间 ${formatDate(data.start)} — ${formatDate(data.end)}`} />
            </CardHeader>
            <CardContent>
              <div className="h-[400px]">
                <ResponsiveContainer>
                  <LineChart data={data.dates} margin={{ top: 12, right: 16, bottom: 8, left: 0 }}>
                    <CartesianGrid stroke="#eef2f7" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="date" minTickGap={32} tick={{ fill: "#6b7280", fontSize: 11 }} />
                    <YAxis yAxisId="left" tick={{ fill: "#6b7280", fontSize: 11 }} width={60} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fill: "#6b7280", fontSize: 11 }} width={60} />
                    <Tooltip
                      formatter={(v: number, n: string) => [v.toFixed(2), n]}
                      labelFormatter={(l) => `日期 ${l}`}
                    />
                    <Legend />
                    <Line yAxisId="left" dataKey="invested" name="累计投入" stroke="#2563eb" dot={false} />
                    <Line yAxisId="left" dataKey="market_value" name="当前市值" stroke="#059669" dot={false} />
                    <Line yAxisId="right" dataKey="pnl" name="累计盈亏" stroke="#dc2626" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          <Card className="p-5">
            <CardHeader>
              <SectionHeader title="各基金当前贡献" description="按当前市值与累计盈亏拆分" />
            </CardHeader>
            <CardContent>
              <div className="h-[320px]">
                <ResponsiveContainer>
                  <BarChart data={data.per_fund.map((f) => ({
                    name: f.fund_name ?? f.fund_code,
                    code: f.fund_code,
                    market: f.current_market_value,
                    invested: f.current_invested,
                    pnl: f.current_market_value - f.current_invested,
                  }))}>
                    <CartesianGrid stroke="#eef2f7" strokeDasharray="3 3" />
                    <XAxis dataKey="name" tick={{ fill: "#6b7280", fontSize: 11 }} />
                    <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} width={60} />
                    <Tooltip formatter={(v: number) => v.toFixed(2)} />
                    <Legend />
                    <Bar dataKey="invested" name="投入" fill="#2563eb" />
                    <Bar dataKey="market" name="市值" fill="#059669" />
                    <Bar dataKey="pnl" name="盈亏" fill="#dc2626" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </main>
  );
}
```

> `MetricCard` 的 `tone` / `formatter` 字段以现有组件实际 prop 为准。
> 实施前先看 [MetricCard.tsx](frontend/src/components/MetricCard.tsx) 调整。

## Task 6: Watchlist entry links

**Files:**
- Modify `frontend/app/watchlist/page.tsx`

- [ ] Add a "查看组合" link per row (or a top-level CTA "查看组合表现"):

```tsx
<Link href={`/portfolio?codes=${row.fund_code}`} className="...">
  在组合中查看
</Link>
```

Adjust to fit the existing watchlist table component. The simplest version: add a
top-of-page "查看组合表现" link button next to the existing KPI cards.

## Task 7: Full verification

- [ ] Run all backend tests:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: all pass.

- [ ] Run frontend tests:

```bash
npm test
```

Expected: all pass.

- [ ] Typecheck:

```bash
npx tsc --noEmit
```

Expected: exit 0.

- [ ] Build:

```bash
npm run build
```

Expected: success.

- [ ] Manual smoke:

1. Open `/portfolio` with no holdings → empty state.
2. Add a holding via watchlist + add a buy transaction.
3. Refresh `/portfolio` → see curve with one step on buy date.

## Commit Plan

```bash
git add backend/services/portfolio_history.py backend/tests/test_portfolio_history.py
git commit -m "feat(portfolio): deterministic pnl time series service"
git add backend/api/routes/portfolio.py backend/tests/test_api_portfolio.py
git commit -m "feat(portfolio): pnl-series endpoint"
git add frontend/src/types/api.ts frontend/src/lib/api.ts frontend/src/lib/portfolio-series.ts frontend/tests/portfolio-series.test.mjs
git commit -m "feat(portfolio): types + client + helpers"
git add frontend/app/portfolio/page.tsx frontend/app/watchlist/page.tsx
git commit -m "feat(portfolio): /portfolio page with three-line chart"
```

## Out of Scope

- 真实 sell 业务路径（`FundTransaction.kind` 仍只支持 `"buy"`）。
- 风险归因 / Brinson / 行业暴露贡献。
- 多币种 / 跨境结算。
- 自动报税 / 记账工具对接。
- 日级快照持久化表（v1 仅在内存 / 即时计算）。
