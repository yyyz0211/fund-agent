# Market Page UI 优化 + Sparkline 真接入 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **执行模式：** 所有 task 完成后由 reviewer 一次性 commit，task 内部的 commit 步骤只是代码操作描述，不真实执行 `git commit`。

**Goal:** 重构 `/market` 页面（信息架构重组 + 视觉统一 + sparkline 真接入），让指数卡和板块强弱行内显示真实历史走势。

**Architecture:** 双侧改动：
- **后端**：在 `MarketSnapshot` 索引/板块 JSON 中注入 `history: number[]`（指数近 30 日收盘价；板块近 10 日涨跌幅）。
- **前端**：5 区布局（Hero → 证据 → 板块 → 外围+公告 → 题材），零依赖 `Sparkline` SVG 组件，指数卡 + 板块行渲染真历史折线。

**Tech Stack:** Next.js 14 + React 18 + TypeScript + Tailwind 3.4 + lucide-react + FastAPI + akshare + SQLAlchemy。

## Global Constraints

- **不引入新依赖**（前端无新增 npm 包；后端仅复用已装的 akshare）。
- **向后兼容**：`MarketSnapshot` 现有 JSON 字段全部保留；`history` 为 optional，无历史数据时前端降级为「不画线」。
- **中国 A 股配色**保留：红涨绿跌。
- **风格统一**：所有卡片 `rounded-xl border border-gray-200 bg-white shadow-sm`；空/错/加载态用 `StateBlock`。
- **可访问性**：装饰性图标 `aria-hidden`；颜色不作为唯一信息载体。
- **API 单测** 不被破坏；新增函数有单测。
- **commit 模式**：所有任务在 reviewer 确认前 **不真实 commit**；task 内部出现的 `git commit` 描述只是代码组织提示，最后一个 task 末尾由 reviewer 一次性 commit。

---

## 文件结构总览

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/services/data_collector.py` | 修改 | 新增 `fetch_index_history` / `fetch_sector_history` |
| `backend/services/market_intel_service.py` | 修改 | `collect_market_intel` 注入 history |
| `backend/tests/test_data_collector.py` | 修改（追加） | 单测两个新函数（mock akshare） |
| `backend/tests/test_market_intel_service.py` | 修改（追加） | 单测 payload 包含 history |
| `frontend/src/lib/market-format.ts` | 新建 | 涨跌色 / 相对时间 / 格式化 |
| `frontend/src/lib/market.ts` | 修改 | `MarketSnapshot` 类型加 optional `history` |
| `frontend/src/components/market/Sparkline.tsx` | 新建 | 零依赖 SVG sparkline |
| `frontend/src/components/market/MarketIndexCard.tsx` | 新建 | 指数卡（含 sparkline） |
| `frontend/src/components/market/MarketHero.tsx` | 新建 | Hero 区（指数+宽度合一） |
| `frontend/src/components/market/SectorTabbedTable.tsx` | 新建 | 板块强弱 tab + 行 sparkline |
| `frontend/src/components/market/MarketEvidencePanel.tsx` | 修改 | 视觉升级：category 图标 + 数量 chip + 相对时间 |
| `frontend/src/components/market/MarketTableUtils.tsx` | 修改 | 复用 `trendTextClass` |
| `frontend/app/market/page.tsx` | 重写 | 5 区布局 |

---

## Task 1: 后端 — 新增 `fetch_index_history`

**Files:**
- Modify: `backend/services/data_collector.py:175-204`（紧跟 `fetch_market_indices` 之后）

**Interfaces:**
- Produces: `fetch_index_history(symbol: str, days: int = 30) -> list[dict] | dict`
  - 成功: `[{"date": "YYYY-MM-DD", "close": float}, ...]` 升序，最长 `days` 条
  - 失败: `{"error": str, "source": str}`

- [ ] **Step 1: 写单测（先失败）**

创建 `backend/tests/test_data_collector_index_history.py`（追加到现有 `test_data_collector.py` 也可，新建更清晰）：

```python
"""fetch_index_history 的单测,mock akshare 避免外网依赖。"""
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from backend.services import data_collector as dc


def _fake_daily_df():
    # ak.stock_zh_index_daily 返回列: date, open, close, high, low, volume, ...
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19",
        ]),
        "close": [3000.0, 3010.5, 3005.2, 3020.0, 3030.0],
    })


def test_fetch_index_history_success():
    with patch.object(dc.ak, "stock_zh_index_daily", return_value=_fake_daily_df()):
        result = dc.fetch_index_history("000300", days=5)
    assert isinstance(result, list)
    assert len(result) == 5
    assert result[0]["date"] == "2026-06-15"
    assert result[-1]["close"] == 3030.0
    assert result[0]["source"] == dc.SOURCE


def test_fetch_index_history_truncates_to_days():
    df = _fake_daily_df()
    with patch.object(dc.ak, "stock_zh_index_daily", return_value=df):
        result = dc.fetch_index_history("000300", days=3)
    assert len(result) == 3
    assert result[-1]["date"] == "2026-06-19"


def test_fetch_index_history_returns_error_on_failure():
    with patch.object(dc.ak, "stock_zh_index_daily", side_effect=Exception("network down")):
        result = dc.fetch_index_history("000300", days=10)
    assert isinstance(result, dict)
    assert "error" in result
    assert "network down" in result["error"]
```

- [ ] **Step 2: 跑测试，确认失败（无此函数）**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_data_collector_index_history.py -v`
Expected: `ImportError` 或 `AttributeError: module 'backend.services.data_collector' has no attribute 'fetch_index_history'`

- [ ] **Step 3: 实现 `fetch_index_history`**

在 `backend/services/data_collector.py` 紧跟 `fetch_market_indices` 函数末尾后追加：

```python
@_akshare_serial
def fetch_index_history(symbol: str, days: int = 30) -> list[dict] | dict:
    """拉取某指数近 N 个交易日的收盘价序列(升序)。

    使用 ``ak.stock_zh_index_daily(symbol=...)``。结果只保留
    ``date`` / ``close`` 两列,便于前端 sparkline 直接消费。

    成功: ``[{"date": "YYYY-MM-DD", "close": float, "source": str}, ...]``
          按日期升序,长度 <= ``days``。
    失败: ``{"error": str, "source": str}``。
    """
    try:
        df = with_retry(ak.stock_zh_index_daily, symbol=symbol)
        if df is None or getattr(df, "empty", True):
            return {"error": f"fetch_index_history empty for {symbol}", "source": SOURCE}
        date_col = _find_col(df, "date", "日期")
        close_col = _find_col(df, "close", "收盘", "收盘价", "最新价")
        if date_col is None or close_col is None:
            return {"error": f"fetch_index_history cols miss for {symbol}: "
                              f"date={date_col} close={close_col}", "source": SOURCE}
        df = df[[date_col, close_col]].copy()
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col).tail(days)
        out: list[dict] = []
        for _, r in df.iterrows():
            close = _to_float(r[close_col])
            if close is None:
                continue
            out.append({
                "date": r[date_col].strftime("%Y-%m-%d"),
                "close": close,
                "source": SOURCE,
            })
        if not out:
            return {"error": f"fetch_index_history no rows for {symbol}", "source": SOURCE}
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_index_history failed for {symbol}: {e}", "source": SOURCE}
```

并在文件顶部 `import pandas as pd`（如果还没有；查 `data_collector.py` 顶部，按需追加）。

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_data_collector_index_history.py -v`
Expected: 3 passed

---

## Task 2: 后端 — 新增 `fetch_sector_history`

**Files:**
- Modify: `backend/services/data_collector.py`（紧跟 `fetch_concept_flows` 之后）

**Interfaces:**
- Produces: `fetch_sector_history(name: str, kind: str = "industry", days: int = 10) -> list[dict] | dict`
  - `kind: "industry"` 用 `ak.stock_board_industry_index_ths(symbol=板块名, period="日k")`
  - `kind: "concept"` 用 `ak.stock_board_concept_index_ths(symbol=板块名, period="日k")`
  - 成功: `[{"date": "YYYY-MM-DD", "change_pct": float}, ...]` 升序,长度 <= days
  - 失败: `{"error": str, "source": str}`

- [ ] **Step 1: 写单测（先失败）**

创建 `backend/tests/test_data_collector_sector_history.py`：

```python
"""fetch_sector_history 的单测。"""
from unittest.mock import patch
import pandas as pd
import pytest

from backend.services import data_collector as dc


def _fake_sector_df():
    # ak.stock_board_industry_index_ths 返回列: date, open, high, low, close, 涨跌幅, 涨跌额, 成交量, 成交额
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2026-06-12", "2026-06-13", "2026-06-16", "2026-06-17", "2026-06-18",
        ]),
        "涨跌幅": [0.5, -0.3, 1.2, 0.8, 2.1],
    })


def test_fetch_industry_history_success():
    with patch.object(dc.ak, "stock_board_industry_index_ths", return_value=_fake_sector_df()):
        result = dc.fetch_sector_history("电子", kind="industry", days=10)
    assert isinstance(result, list)
    assert len(result) == 5
    assert result[0]["date"] == "2026-06-12"
    assert result[-1]["change_pct"] == 2.1
    assert result[0]["source"] == dc.SOURCE


def test_fetch_concept_history_truncates_to_days():
    with patch.object(dc.ak, "stock_board_concept_index_ths", return_value=_fake_sector_df()):
        result = dc.fetch_sector_history("AI算力", kind="concept", days=3)
    assert len(result) == 3
    assert result[-1]["date"] == "2026-06-18"


def test_fetch_sector_history_returns_error_on_failure():
    with patch.object(dc.ak, "stock_board_industry_index_ths", side_effect=Exception("api down")):
        result = dc.fetch_sector_history("电子", kind="industry", days=10)
    assert isinstance(result, dict)
    assert "error" in result
    assert "api down" in result["error"]


def test_fetch_sector_history_invalid_kind():
    result = dc.fetch_sector_history("X", kind="bad", days=10)
    assert isinstance(result, dict)
    assert "error" in result
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_data_collector_sector_history.py -v`
Expected: ImportError / AttributeError

- [ ] **Step 3: 实现 `fetch_sector_history`**

在 `backend/services/data_collector.py` 末尾追加（`fetch_breadth_indicators` 之前或之后皆可）：

```python
@_akshare_serial
def fetch_sector_history(name: str, kind: str = "industry", days: int = 10) -> list[dict] | dict:
    """拉取某行业/概念板块近 N 个交易日的日涨跌幅序列(升序,百分比小数,如 0.0123 = +1.23%)。

    Args:
        name: 板块名,例如 "电子" / "AI算力"
        kind: ``"industry"`` 或 ``"concept"``
        days: 保留尾 N 条

    成功: ``[{"date": "YYYY-MM-DD", "change_pct": float, "source": str}, ...]``
    失败: ``{"error": str, "source": str}``
    """
    if kind not in ("industry", "concept"):
        return {"error": f"fetch_sector_history kind must be industry|concept, got {kind!r}", "source": SOURCE}
    fn = ak.stock_board_industry_index_ths if kind == "industry" else ak.stock_board_concept_index_ths
    try:
        df = with_retry(fn, symbol=name, period="日k")
        if df is None or getattr(df, "empty", True):
            return {"error": f"fetch_sector_history empty for {name} ({kind})", "source": SOURCE}
        date_col = _find_col(df, "date", "日期")
        change_col = _find_col(df, "涨跌幅", "change_pct", "涨跌幅(%)")
        if date_col is None or change_col is None:
            return {"error": f"fetch_sector_history cols miss for {name} ({kind}): "
                              f"date={date_col} change={change_col}", "source": SOURCE}
        df = df[[date_col, change_col]].copy()
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col).tail(days)
        out: list[dict] = []
        for _, r in df.iterrows():
            v = _to_float(r[change_col])
            # 百分比统一转换为小数 (1.23% -> 0.0123)
            if v is not None and abs(v) > 1:
                v = v / 100.0
            if v is None:
                continue
            out.append({
                "date": r[date_col].strftime("%Y-%m-%d"),
                "change_pct": v,
                "source": SOURCE,
            })
        if not out:
            return {"error": f"fetch_sector_history no rows for {name} ({kind})", "source": SOURCE}
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"fetch_sector_history failed for {name} ({kind}): {e}", "source": SOURCE}
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_data_collector_sector_history.py -v`
Expected: 4 passed

---

## Task 3: 后端 — `collect_market_intel` 注入 history 字段

**Files:**
- Modify: `backend/services/market_intel_service.py:36-114`

**Interfaces:**
- 现有 payload 不变；每个 `indices[i]` 增加 `history?: number[]`；每个 `industry_sectors[i]` / `concept_sectors[i]` 增加 `history?: number[]`。
- history 采集失败不影响整体（按 dict 错误处理，已存在的 errors 列表机制）。

- [ ] **Step 1: 写单测（先失败）**

创建 `backend/tests/test_market_intel_history.py`：

```python
"""collect_market_intel 把 history 注入 payload 的单测。"""
from unittest.mock import patch
from backend.services import market_intel_service as svc


def test_indices_have_history():
    with patch.object(svc.dc, "fetch_market_indices", return_value=[
        {"symbol": "000001", "name": "上证指数", "close": 3000.0, "change_pct": 0.5, "market_date": "2026-07-08", "source": "akshare"},
    ]), \
         patch.object(svc.dc, "fetch_market_breadth", return_value={"up": 1, "down": 0, "limit_up": 0, "limit_down": 0, "volume": 0, "amount": 0, "total": 1, "source": "akshare", "as_of": "2026-07-08"}), \
         patch.object(svc.dc, "fetch_sector_snapshot", return_value=[]), \
         patch.object(svc.dc, "fetch_industry_flows", return_value=[]), \
         patch.object(svc.dc, "fetch_concept_sectors", return_value=[]), \
         patch.object(svc.dc, "fetch_concept_flows", return_value=[]), \
         patch.object(svc.dc, "fetch_theme_boards", return_value=[]), \
         patch.object(svc.dc, "fetch_breadth_indicators", return_value={"board_height": [], "source": "akshare", "as_of": "2026-07-08"}), \
         patch.object(svc.dc, "fetch_overseas_markets", return_value=[]), \
         patch.object(svc.dc, "fetch_announcements", return_value=[]), \
         patch.object(svc.dc, "fetch_index_history", return_value=[
             {"date": "2026-07-07", "close": 2990.0, "source": "akshare"},
             {"date": "2026-07-08", "close": 3000.0, "source": "akshare"},
         ]):
        payload = svc.collect_market_intel(trade_date="2026-07-08", snapshot_type="post_market", session=None)
    assert len(payload["indices"]) == 1
    assert payload["indices"][0]["history"] == [2990.0, 3000.0]


def test_history_failure_does_not_block_payload():
    with patch.object(svc.dc, "fetch_market_indices", return_value=[
        {"symbol": "000001", "name": "上证指数", "close": 3000.0, "change_pct": 0.5, "market_date": "2026-07-08", "source": "akshare"},
    ]), \
         patch.object(svc.dc, "fetch_market_breadth", return_value={"up": 1, "down": 0, "limit_up": 0, "limit_down": 0, "volume": 0, "amount": 0, "total": 1, "source": "akshare", "as_of": "2026-07-08"}), \
         patch.object(svc.dc, "fetch_sector_snapshot", return_value=[]), \
         patch.object(svc.dc, "fetch_industry_flows", return_value=[]), \
         patch.object(svc.dc, "fetch_concept_sectors", return_value=[]), \
         patch.object(svc.dc, "fetch_concept_flows", return_value=[]), \
         patch.object(svc.dc, "fetch_theme_boards", return_value=[]), \
         patch.object(svc.dc, "fetch_breadth_indicators", return_value={"board_height": [], "source": "akshare", "as_of": "2026-07-08"}), \
         patch.object(svc.dc, "fetch_overseas_markets", return_value=[]), \
         patch.object(svc.dc, "fetch_announcements", return_value=[]), \
         patch.object(svc.dc, "fetch_index_history", return_value={"error": "boom", "source": "akshare"}):
        payload = svc.collect_market_intel(trade_date="2026-07-08", snapshot_type="post_market", session=None)
    assert payload["indices"][0].get("history") is None
    assert any(e["field"].startswith("index_history:") for e in payload["errors"])
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_market_intel_history.py -v`
Expected: KeyError 或 AssertionError（payload 中无 history 字段 / 有 history 但不像预期）

- [ ] **Step 3: 修改 `collect_market_intel` 注入 history**

在 `backend/services/market_intel_service.py` 中：

1. 紧跟 `indices = _collect_field("indices", ...)` 之后（约第 73 行后）追加：

```python
    # 给每个 index 注入近 30 日收盘价序列(history)。单项失败记录到 errors,不影响整体。
    if isinstance(indices, dict):
        indices_list = indices.get("indices", []) if "indices" in indices else []
    else:
        indices_list = indices or []
    for idx in indices_list:
        sym = idx.get("symbol")
        if not sym:
            continue
        hist = _collect_field(f"index_history:{sym}", dc.fetch_index_history, sym, 30)
        if isinstance(hist, list) and hist:
            idx["history"] = [float(p["close"]) for p in hist if p.get("close") is not None]
        else:
            idx["history"] = None
```

2. 给板块注入 history — 紧跟 `industry_sectors = ...` 之后：

```python
    for s in (industry_sectors or []):
        nm = s.get("name")
        if not nm:
            continue
        hist = _collect_field(f"industry_history:{nm}", dc.fetch_sector_history, nm, "industry", 10)
        if isinstance(hist, list) and hist:
            s["history"] = [float(p["change_pct"]) for p in hist if p.get("change_pct") is not None]
        else:
            s["history"] = None
```

3. 给概念注入 history — 紧跟 `concept_sectors = ...` 之后：

```python
    for s in (concept_sectors or []):
        nm = s.get("name")
        if not nm:
            continue
        hist = _collect_field(f"concept_history:{nm}", dc.fetch_sector_history, nm, "concept", 10)
        if isinstance(hist, list) and hist:
            s["history"] = [float(p["change_pct"]) for p in hist if p.get("change_pct") is not None]
        else:
            s["history"] = None
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests/test_market_intel_history.py -v`
Expected: 2 passed

- [ ] **Step 5: 跑后端全部测试，确保无回归**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests -q`
Expected: 既有测试全过；新增 3 个文件共 9 个新测试全过。

---

## Task 4: 前端 — `market-format.ts` 工具库

**Files:**
- Create: `frontend/src/lib/market-format.ts`

**Interfaces:**
- Produces: `trendTextClass(v)`, `trendBgClass(v)`, `formatPctWithSign(v)`, `relativeTime(iso, now?)`

- [ ] **Step 1: 新建文件**

```ts
/** A 股配色：红涨绿跌 */
export function trendTextClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-gray-500";
  if (v > 0) return "text-red-700";
  if (v < 0) return "text-green-700";
  return "text-gray-500";
}

export function trendBgClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "bg-gray-100 text-gray-600";
  if (v > 0) return "bg-red-50 text-red-700";
  if (v < 0) return "bg-green-50 text-green-700";
  return "bg-gray-100 text-gray-600";
}

/** 把 0.0123 -> "+1.23%";--/null -> "—" */
export function formatPctWithSign(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

/** "3 分钟前" / "2 小时前" / "昨天" / "07-08 14:30" */
export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return iso.slice(0, 16).replace("T", " ");
  const diffMs = now.getTime() - t.getTime();
  const min = Math.round(diffMs / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.round(hr / 24);
  if (day === 1) return "昨天";
  if (day < 7) return `${day} 天前`;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(t.getMonth() + 1)}-${pad(t.getDate())} ${pad(t.getHours())}:${pad(t.getMinutes())}`;
}
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`
Expected: 无新错误。

---

## Task 5: 前端 — 零依赖 `Sparkline` 组件

**Files:**
- Create: `frontend/src/components/market/Sparkline.tsx`

**Interfaces:**
- Produces: `<Sparkline points={number[]} ... />` 内联 SVG，<2 个点时画细灰线占位。

- [ ] **Step 1: 新建文件**

```tsx
"use client";
import { useMemo } from "react";

interface SparklineProps {
  points: number[];
  width?: number;
  height?: number;
  toneClass?: string;
  color?: string;
  className?: string;
  area?: boolean;
  ariaLabel?: string;
}

export function Sparkline({
  points,
  width = 96,
  height = 28,
  toneClass = "text-blue-500",
  color,
  className,
  area = true,
  ariaLabel,
}: SparklineProps) {
  const path = useMemo(() => {
    if (!points || points.length < 2) return null;
    const min = Math.min(...points);
    const max = Math.max(...points);
    const range = max - min || 1;
    const dx = width / (points.length - 1);
    const ys = points.map((p) => {
      const norm = (p - min) / range;
      return height - norm * (height - 4) - 2;
    });
    const line = ys.map((y, i) => `${i === 0 ? "M" : "L"}${i * dx.toFixed(2)} ${y.toFixed(2)}`).join(" ");
    const fill = `${line} L${width.toFixed(2)} ${height} L0 ${height} Z`;
    return { line, fill };
  }, [points, width, height]);

  if (!path) {
    return (
      <svg width={width} height={height} className={className} aria-hidden="true">
        <line x1={0} y1={height / 2} x2={width} y2={height / 2} className="stroke-gray-200" strokeWidth={1} />
      </svg>
    );
  }

  const stroke = color ?? "currentColor";
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={["block", color ? undefined : toneClass, className].filter(Boolean).join(" ")}
      role={ariaLabel ? "img" : undefined}
      aria-label={ariaLabel}
    >
      {area ? <path d={path.fill} fill={stroke} fillOpacity={0.12} stroke="none" /> : null}
      <path d={path.line} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

---

## Task 6: 前端 — `MarketIndexCard` 含真 sparkline

**Files:**
- Create: `frontend/src/components/market/MarketIndexCard.tsx`

**Interfaces:**
- Produces: `<MarketIndexCard name close changePct history? weight? />`，`history` 为可选数组。

- [ ] **Step 1: 新建文件**

```tsx
"use client";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { Sparkline } from "./Sparkline";
import { trendTextClass, trendBgClass, formatPctWithSign } from "@/lib/market-format";

export interface MarketIndexCardProps {
  name: string;
  close: number;
  changePct: number;
  history?: number[] | null;
  weight?: "lead" | "normal";
}

export function MarketIndexCard({ name, close, changePct, history, weight = "normal" }: MarketIndexCardProps) {
  const positive = changePct > 0;
  const flat = changePct === 0;
  const Icon = positive ? ArrowUpRight : flat ? null : ArrowDownRight;

  const padding = weight === "lead" ? "p-5" : "p-4";
  const closeSize = weight === "lead" ? "text-3xl" : "text-2xl";

  return (
    <div className={`rounded-xl border border-gray-200 bg-white ${padding} shadow-sm transition hover:shadow-md`}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium text-gray-600">{name}</div>
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums ${trendBgClass(changePct)}`}>
          {Icon ? <Icon className="h-3 w-3" /> : null}
          {formatPctWithSign(changePct)}
        </span>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div className={`${closeSize} font-semibold tracking-tight tabular-nums ${trendTextClass(changePct)}`}>
          {close.toFixed(2)}
        </div>
        {history && history.length >= 2 ? (
          <div className="opacity-90">
            <Sparkline
              points={history}
              width={weight === "lead" ? 110 : 80}
              height={weight === "lead" ? 36 : 28}
              toneClass={positive ? "text-red-500" : "text-green-500"}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

---

## Task 7: 前端 — `MarketSnapshot` 类型加 `history` 字段

**Files:**
- Modify: `frontend/src/lib/market.ts:17-32`

**Interfaces:**
- 现有类型不变；为 indices / industry_sectors / concept_sectors 元素增加 optional `history?: number[] | null`。

- [ ] **Step 1: 修改 `MarketSnapshot` interface**

把 `frontend/src/lib/market.ts` 第 17-32 行替换为：

```ts
export interface MarketSnapshot {
  trade_date: string;
  snapshot_type: string;
  indices: Array<{ symbol: string; name: string; close: number; change_pct: number; history?: number[] | null }>;
  breadth: Partial<MarketBreadth> & { error?: string; source?: string };
  industry_sectors: Array<{ name: string; change_pct: number; history?: number[] | null }>;
  concept_sectors: Array<{ name: string; change_pct: number; history?: number[] | null }>;
  industry_flows: Array<{ name: string; net_flow: number }>;
  concept_flows: Array<{ name: string; net_flow: number }>;
  themes: Array<{ theme: string; count: number; stocks: Array<{ name: string }> }>;
  breadth_indicators: { board_height: Array<{ name: string; boards: number }> };
  overseas: Array<{ market: string; name: string; symbol: string; close: number | null; change_pct: number | null }>;
  announcements: Array<{ title: string; ann_date: string; fund_code: string; fund_name: string }>;
  source: string;
  as_of: string;
}
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

---

## Task 8: 前端 — `MarketHero`

**Files:**
- Create: `frontend/src/components/market/MarketHero.tsx`

**Interfaces:**
- Produces: `<MarketHero snap />`，把核心指数 + 市场宽度合并展示。

- [ ] **Step 1: 新建文件**

```tsx
"use client";
import { MarketSnapshot, normalizeMarketBreadth } from "@/lib/market";
import { MarketIndexCard } from "./MarketIndexCard";
import { trendBgClass, formatPctWithSign, trendTextClass } from "@/lib/market-format";

const LEAD_INDEX_NAMES = new Set(["上证指数", "深证成指", "创业板指", "科创50"]);

export function MarketHero({ snap }: { snap: MarketSnapshot }) {
  const breadth = normalizeMarketBreadth(snap.breadth);
  const { up, down, limit_up, limit_down } = breadth;
  const total = up + down;
  const upRatio = total > 0 ? (up / total) * 100 : 0;
  const downRatio = total > 0 ? (down / total) * 100 : 0;
  const hasError = Boolean(breadth.error);
  const sentiment = hasError
    ? { label: "缺失", note: "市场宽度暂不可用" }
    : up > down * 1.3
    ? { label: "偏暖", note: "上涨家数占优" }
    : down > up * 1.3
    ? { label: "偏弱", note: "下跌家数占优" }
    : { label: "震荡", note: "涨跌接近平衡" };

  const lead = snap.indices.filter((i) => LEAD_INDEX_NAMES.has(i.name));
  const rest = snap.indices.filter((i) => !LEAD_INDEX_NAMES.has(i.name));
  const shown = lead.length > 0 ? lead : snap.indices.slice(0, 4);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {shown.map((idx) => (
          <MarketIndexCard
            key={idx.symbol}
            name={idx.name}
            close={idx.close}
            changePct={idx.change_pct}
            history={idx.history}
            weight="lead"
          />
        ))}
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Market breadth · {snap.trade_date}
              </span>
              <span className={`rounded-full border border-gray-200 px-2 py-0.5 text-xs font-semibold ${trendBgClass(up - down)}`}>
                {sentiment.label}
              </span>
            </div>
            <p className="mt-1 text-sm text-gray-500">{sentiment.note}</p>
            {hasError ? (
              <p className="mt-1 text-xs text-amber-600">数据源返回错误：{breadth.error}</p>
            ) : null}
          </div>

          <div className="grid grid-cols-4 gap-2 lg:min-w-[420px]">
            <Stat label="上涨" value={up} toneClass="text-red-700" sub={`${upRatio.toFixed(1)}%`} />
            <Stat label="下跌" value={down} toneClass="text-green-700" sub={`${downRatio.toFixed(1)}%`} />
            <Stat label="涨停" value={limit_up} toneClass="text-red-700" />
            <Stat label="跌停" value={limit_down} toneClass="text-green-700" />
          </div>
        </div>

        <div className="mt-4 flex h-2.5 w-full overflow-hidden rounded-full bg-gray-100">
          <div className="bg-red-500" style={{ width: `${upRatio}%` }} />
          <div className="bg-green-500" style={{ width: `${downRatio}%` }} />
        </div>
      </div>

      {rest.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">其他指数</span>
          {rest.map((idx) => (
            <span
              key={idx.symbol}
              className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs"
            >
              <span className="font-medium text-gray-700">{idx.name}</span>
              <span className={`tabular-nums ${trendTextClass(idx.change_pct)}`}>
                {formatPctWithSign(idx.change_pct)}
              </span>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Stat({ label, value, toneClass, sub }: { label: string; value: number; toneClass: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-gray-50 px-3 py-2">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className={`mt-0.5 font-semibold tabular-nums ${toneClass}`}>{value}</div>
      {sub ? <div className="text-[10px] text-gray-500">{sub}</div> : null}
    </div>
  );
}
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

---

## Task 9: 前端 — `SectorTabbedTable` 含真 sparkline

**Files:**
- Create: `frontend/src/components/market/SectorTabbedTable.tsx`

**Interfaces:**
- Produces: `<SectorTabbedTable snap />`，单卡含「行业 / 概念」tab，行内用 `s.history` 渲染 sparkline。

- [ ] **Step 1: 新建文件**

```tsx
"use client";
import { useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Building2, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import { MarketSnapshot } from "@/lib/market";
import { Sparkline } from "./Sparkline";
import { trendTextClass, formatPctWithSign } from "@/lib/market-format";
import { cn } from "@/lib/cn";

type TabKey = "industry" | "concept";

const TABS: Array<{ key: TabKey; label: string; icon: LucideIcon }> = [
  { key: "industry", label: "行业板块", icon: Building2 },
  { key: "concept", label: "概念板块", icon: Sparkles },
];

export function SectorTabbedTable({ snap }: { snap: MarketSnapshot }) {
  const [tab, setTab] = useState<TabKey>("industry");
  const rows = tab === "industry" ? snap.industry_sectors : snap.concept_sectors;
  const flows = tab === "industry" ? snap.industry_flows : snap.concept_flows;
  const flowMap = new Map(flows.map((f) => [f.name, f.net_flow]));

  const sorted = [...rows]
    .sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct))
    .slice(0, 15);
  const strongest = sorted[0];
  const weakest = sorted[sorted.length - 1];

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
        <div className="flex items-center gap-1 rounded-lg bg-gray-50 p-1">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition",
                  active ? "bg-white text-gray-950 shadow-sm" : "text-gray-600 hover:text-gray-950",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {t.label}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2 text-xs">
          {strongest ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 font-semibold text-red-700">
              <TrendingUp className="h-3 w-3" />
              领涨 {strongest.name}
            </span>
          ) : null}
          {weakest && weakest !== strongest ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 font-semibold text-green-700">
              <TrendingDown className="h-3 w-3" />
              领跌 {weakest.name}
            </span>
          ) : null}
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-gray-400">暂无{tab === "industry" ? "行业" : "概念"}板块数据</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-xs text-gray-500">
                <th className="px-4 py-2.5 text-left font-medium">名称</th>
                <th className="px-4 py-2.5 text-left font-medium">趋势</th>
                <th className="px-4 py-2.5 text-right font-medium">涨跌幅</th>
                <th className="px-4 py-2.5 text-right font-medium">净流入</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => {
                const nf = flowMap.get(s.name) ?? null;
                const flowY = nf == null ? null : nf / 10000;
                const flowText = flowY == null ? "—" : `${flowY > 0 ? "+" : ""}${flowY.toFixed(2)}亿`;
                const flowColor =
                  flowY == null ? "text-gray-400"
                  : flowY > 0 ? "text-red-700"
                  : flowY < 0 ? "text-green-700"
                  : "text-gray-500";
                const positive = s.change_pct > 0;
                return (
                  <tr key={s.name} className="border-t border-gray-100 transition hover:bg-gray-50/70">
                    <td className="whitespace-nowrap px-4 py-3 font-medium text-gray-950">{s.name}</td>
                    <td className="px-4 py-3">
                      {s.history && s.history.length >= 2 ? (
                        <Sparkline
                          points={s.history}
                          width={80}
                          height={24}
                          toneClass={positive ? "text-red-400" : "text-green-400"}
                          area={false}
                        />
                      ) : (
                        <span className="text-xs text-gray-300">—</span>
                      )}
                    </td>
                    <td className={`whitespace-nowrap px-4 py-3 text-right font-semibold tabular-nums ${trendTextClass(s.change_pct)}`}>
                      {formatPctWithSign(s.change_pct)}
                    </td>
                    <td className={`whitespace-nowrap px-4 py-3 text-right font-mono text-xs tabular-nums ${flowColor}`}>
                      {flowText}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

---

## Task 10: 前端 — 升级 `MarketEvidencePanel`

**Files:**
- Modify: `frontend/src/components/market/MarketEvidencePanel.tsx`（完整重写）

- [ ] **Step 1: 用以下内容覆盖整个文件**

```tsx
"use client";
import { useMemo } from "react";
import { Building2, ExternalLink, Landmark, Megaphone, Newspaper, ShieldAlert, ShieldCheck, Tag, Globe2 } from "lucide-react";
import { useMarketEvidence } from "@/lib/market";
import type {
  EvidenceCategory,
  MarketEvidenceItem,
  EvidenceReliability,
} from "@/types/api";
import { StateBlock } from "@/components/StateBlock";
import { relativeTime } from "@/lib/market-format";

const CATEGORY_META: Record<EvidenceCategory, { label: string; icon: typeof Tag; tone: string }> = {
  policy: { label: "政策", icon: Landmark, tone: "bg-blue-50 text-blue-700" },
  announcement: { label: "公告", icon: Megaphone, tone: "bg-amber-50 text-amber-700" },
  overseas_disclosure: { label: "海外披露", icon: Globe2, tone: "bg-violet-50 text-violet-700" },
  macro: { label: "宏观", icon: Building2, tone: "bg-cyan-50 text-cyan-700" },
  sector: { label: "行业热点", icon: Tag, tone: "bg-emerald-50 text-emerald-700" },
  news: { label: "财联社快讯", icon: Newspaper, tone: "bg-rose-50 text-rose-700" },
};

const CATEGORY_ORDER: EvidenceCategory[] = [
  "policy",
  "announcement",
  "overseas_disclosure",
  "macro",
  "sector",
  "news",
];

const RELIABILITY_LABEL: Record<EvidenceReliability, string> = {
  official: "官方",
  wire: "聚合",
  rumor: "传闻",
};

const RELIABILITY_BADGE: Record<EvidenceReliability, string> = {
  official: "bg-blue-50 text-blue-700 ring-blue-100",
  wire: "bg-gray-100 text-gray-600 ring-gray-200",
  rumor: "bg-amber-50 text-amber-700 ring-amber-100",
};

interface MarketEvidencePanelProps {
  date: string;
}

export function MarketEvidencePanel({ date }: MarketEvidencePanelProps) {
  const { data, isLoading, error } = useMarketEvidence(date);
  const groups = data?.groups ?? {};
  const count = data?.count ?? 0;
  const hasAny = count > 0 && Object.keys(groups).length > 0;

  const presentCategories = useMemo(
    () => CATEGORY_ORDER.filter((c) => (groups[c]?.length ?? 0) > 0),
    [groups],
  );

  if (isLoading) return <StateBlock title="正在加载证据…" tone="loading" />;
  if (error) return <StateBlock title="证据加载失败" tone="error">{String(error)}</StateBlock>;
  if (!hasAny) {
    return (
      <StateBlock
        title="今日暂无证据"
        action={<span className="text-xs text-gray-400">来源：market_evidence 本地表</span>}
      >
        暂无可验证证据（政策 / 公告 / 宏观 / 行业 / 财联社快讯）。本地未采集到当日证据，证据面板留空并不代表市场没有事件。
      </StateBlock>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">分类概览</span>
        {presentCategories.map((cat) => {
          const meta = CATEGORY_META[cat];
          const Icon = meta.icon;
          const n = groups[cat]?.length ?? 0;
          return (
            <span
              key={cat}
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${meta.tone}`}
            >
              <Icon className="h-3 w-3" />
              {meta.label}
              <span className="rounded-full bg-white/70 px-1.5 text-[10px] tabular-nums">{n}</span>
            </span>
          );
        })}
        <span className="ml-auto text-xs text-gray-400">共 {count} 条</span>
      </div>

      {presentCategories.map((cat) => {
        const items = groups[cat] as MarketEvidenceItem[];
        const meta = CATEGORY_META[cat];
        const Icon = meta.icon;
        return (
          <section key={cat} className="rounded-xl border border-gray-200 bg-white shadow-sm" aria-label={meta.label}>
            <header className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
              <div className="flex items-center gap-2">
                <span className={`flex h-6 w-6 items-center justify-center rounded-md ${meta.tone}`}>
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <h3 className="text-sm font-semibold text-gray-950">{meta.label}</h3>
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                  {items.length} 条
                </span>
              </div>
            </header>
            <ul className="divide-y divide-gray-100">
              {items.map((item) => (
                <EvidenceRow key={item.id} item={item} />
              ))}
            </ul>
          </section>
        );
      })}

      <p className="px-1 text-[11px] text-gray-400">
        面板数据来源于本地 market_evidence 表,抓取自公开政策页 / 公开宏观数据 / 公开公告 / 财联社电报;仅供研究参考,不构成投资建议。
      </p>
    </div>
  );
}

function EvidenceRow({ item }: { item: MarketEvidenceItem }) {
  const reliability = (item.reliability || "wire") as EvidenceReliability;
  return (
    <li className="flex gap-3 px-4 py-3">
      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="block truncate text-sm font-medium text-gray-950 hover:text-blue-700"
            title={item.title}
          >
            {item.title}
            <ExternalLink className="ml-1 inline h-3 w-3 align-middle text-gray-400" />
          </a>
          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${RELIABILITY_BADGE[reliability]}`}
          >
            {reliability === "official" ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
            {RELIABILITY_LABEL[reliability]}
          </span>
        </div>
        {item.summary ? <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{item.summary}</p> : null}
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-gray-400">
          <span>来源 · {item.source}</span>
          {item.published_at ? <span>· {relativeTime(item.published_at)}</span> : null}
          {item.symbols && item.symbols.length > 0 ? (
            <span>· tag · {item.symbols.slice(0, 3).join(" / ")}</span>
          ) : null}
        </div>
      </div>
    </li>
  );
}
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

---

## Task 11: 前端 — `MarketTableUtils` 复用 `trendTextClass`

**Files:**
- Modify: `frontend/src/components/market/MarketTableUtils.tsx`

- [ ] **Step 1: 替换整个文件为**

```tsx
"use client";
import { trendTextClass } from "@/lib/market-format";

export { trendTextClass as ChangeCellClass };

export function ChangeCell({ pct }: { pct: number }) {
  const color = pct > 0 ? "text-red-600" : pct < 0 ? "text-green-600" : "text-gray-500";
  const sign = pct > 0 ? "+" : "";
  return <span className={color}>{sign}{pct.toFixed(2)}%</span>;
}

const BAR_MAX = 5;
const BAR_MAX_WIDTH = 56;

export function ChangeBar({ pct }: { pct: number }) {
  const width = Math.max(3, Math.round((Math.min(Math.abs(pct), BAR_MAX) / BAR_MAX) * BAR_MAX_WIDTH));
  const positive = pct > 0;
  const negative = pct < 0;
  const bar = positive ? "bg-red-500" : negative ? "bg-green-500" : "bg-gray-300";
  const textColor = pct > 0 ? "text-red-700" : pct < 0 ? "text-green-700" : "text-gray-500";
  const sign = positive ? "+" : "";
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-3 w-32 rounded-full bg-gray-100">
        <span className="absolute left-1/2 top-0 h-3 w-px translate-x-[1px] bg-gray-300" />
        <span
          className={`absolute left-1/2 top-1/2 h-2 -translate-y-1/2 rounded-full ${bar} ${
            negative ? "-translate-x-full" : ""
          }`}
          style={{ width }}
        />
      </div>
      <span className={`font-mono text-xs tabular-nums ${textColor} w-14 text-right`}>
        {sign}{pct.toFixed(2)}%
      </span>
    </div>
  );
}
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

---

## Task 12: 前端 — 重写 `app/market/page.tsx` 5 区布局

**Files:**
- Modify: `frontend/app/market/page.tsx`（完整重写）

- [ ] **Step 1: 用以下内容覆盖整个文件**

```tsx
"use client";
import { useState } from "react";
import { resolveMarketDate, useMarketSnapshot, useMarketEvidence } from "@/lib/market";
import { MarketHero } from "@/components/market/MarketHero";
import { MarketEvidencePanel } from "@/components/market/MarketEvidencePanel";
import { SectorTabbedTable } from "@/components/market/SectorTabbedTable";
import { OverseasMarkets } from "@/components/market/OverseasMarkets";
import { AnnouncementList } from "@/components/market/AnnouncementList";
import { ThemeBoards } from "@/components/market/ThemeBoards";
import { SnapshotRefreshButton } from "@/components/market/SnapshotRefreshButton";
import { SectionHeader } from "@/components/PageHeader";
import { AlertTriangle } from "lucide-react";
import { StateBlock } from "@/components/StateBlock";

const DATE_OPTIONS = [
  { label: "今日", value: "today" },
  { label: "昨日", value: "yesterday" },
];

export default function MarketPage() {
  const [dateOpt, setDateOpt] = useState("today");
  const date = resolveMarketDate(dateOpt);
  const { data: snap, isLoading, error } = useMarketSnapshot(date, "post_market");
  const evidence = useMarketEvidence(date);
  const evidenceCount = evidence.data?.count ?? 0;

  return (
    <div className="mx-auto max-w-7xl space-y-7 px-4 pb-10 sm:px-6 lg:px-8">
      <div className="rounded-2xl border border-gray-200 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
              Local market dashboard
            </p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-gray-950 sm:text-3xl">
              市场情报中心
            </h1>
            <p className="mt-2 text-sm leading-6 text-gray-600">
              收盘后快照，集中查看指数、市场宽度、证据面板、板块强弱、外围市场与公告。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-xl border border-gray-200 bg-gray-50 p-1">
              {DATE_OPTIONS.map((o) => (
                <button
                  key={o.value}
                  onClick={() => setDateOpt(o.value)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                    dateOpt === o.value
                      ? "bg-gray-950 text-white shadow-sm"
                      : "text-gray-600 hover:bg-white hover:text-gray-950"
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
            <SnapshotRefreshButton />
          </div>
        </div>
      </div>

      {isLoading && <StateBlock title="加载市场数据…" tone="loading" />}

      {error && !isLoading && (
        <div className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <div className="font-semibold">市场数据加载失败</div>
            <div className="mt-1 text-red-600">{String(error)}</div>
          </div>
        </div>
      )}

      {snap && !isLoading && (
        <div className="space-y-7">
          <section className="space-y-3">
            <SectionHeader
              title="今日市场"
              description={`as of ${snap.as_of} · 证据 ${evidenceCount} 条`}
            />
            <MarketHero snap={snap} />
          </section>

          <section className="space-y-3">
            <SectionHeader
              title="证据面板"
              description="按类别分组的可追溯政策/公告/宏观证据 — 来自 market_evidence 本地表"
            />
            <MarketEvidencePanel date={date} />
          </section>

          <section className="space-y-3">
            <SectionHeader
              title="板块强弱"
              description="按涨跌幅绝对值排序，行内 sparkline 展示近 10 日涨跌幅，净流入以亿为单位。"
            />
            <SectorTabbedTable snap={snap} />
          </section>

          <section className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(360px,0.7fr)]">
            <div className="space-y-3">
              <SectionHeader title="外围市场" description="隔夜市场和港美股快览" />
              <OverseasMarkets snap={snap} />
            </div>
            <div className="space-y-3">
              <SectionHeader title="重要公告" description="最新公开公告线索" />
              <AnnouncementList snap={snap} />
            </div>
          </section>

          <section className="space-y-3">
            <SectionHeader title="热门题材" description="题材概念与代表个股汇总" />
            <ThemeBoards snap={snap} />
          </section>

          <p className="rounded-xl border border-gray-200 bg-white px-4 py-3 text-xs text-gray-500 shadow-sm">
            数据来源：{snap.source} · 截止：{snap.as_of} · 本页仅整理公开市场数据，不构成投资建议。
          </p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 验证 TS + build**

Run:
```bash
cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit && pnpm build 2>&1 | tail -30
```

Expected: 编译成功，无 TS / lint 错误。

---

## Task 13: 全量回归（reviewer 检查点）

**Files:** 无改动

- [ ] **Step 1: 后端全量测试**

Run: `cd /Users/leon/fund-agent && python -m pytest backend/tests -q`
Expected: 所有既有 + 新增测试全过。

- [ ] **Step 2: 前端 typecheck + build**

Run:
```bash
cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit && pnpm build 2>&1 | tail -30
```

Expected: 成功。

- [ ] **Step 3: 启动 dev server，目视检查**

```bash
cd /Users/leon/fund-agent/frontend && pnpm dev
```

访问 `http://localhost:3000/market`，检查清单：
- [ ] Hero 区 4 个核心指数卡含真实 sparkline（如果数据已采集）
- [ ] 市场宽度条按上下家数比例显示
- [ ] 证据面板分类 chips 正常 + 相对时间显示
- [ ] 板块 tab 切换可点击
- [ ] 板块行 sparkline 显示真实曲线（如果 history 已采集）
- [ ] 外围市场 + 公告 横向并排
- [ ] 题材卡片正常
- [ ] 切换"今日/昨日"无控制台报错

- [ ] **Step 4: 把 `git status` / `git diff --stat` 报告给 reviewer**

执行:
```bash
cd /Users/leon/fund-agent && git status && echo "---" && git diff --stat
```

把输出贴给 reviewer 等待确认。

---

## 验收标准

1. 后端 `pytest backend/tests -q` 全过
2. 前端 `pnpm exec tsc --noEmit && pnpm build` 成功
3. 5 区顺序：Hero → 证据 → 板块 → 外围+公告 → 题材
4. Sparkline 接入**真数据**（指数近 30 日收盘 / 板块近 10 日涨跌幅）
5. 无历史数据时 sparkline 不渲染（不显示假线）
6. 视觉统一：所有卡片用 `rounded-xl border border-gray-200 bg-white shadow-sm`；空/错/加载态用 `StateBlock`
7. 中国 A 股配色保留：红涨绿跌
8. 不引入新依赖
9. `MarketSnapshot` 现有字段完全保留；`history` 仅为 optional

---

## 不在本次范围（明确 YAGNI）

- 不改后端 scheduler、数据库迁移工具
- 不改 AppShell / navigation / 主题
- 不做暗色模式
- 不做板块 tab 键盘快捷键
- 不动 `/api/market/series` 等新接口（history 直接注入 snapshot payload）
- 不重构 React Query 层
