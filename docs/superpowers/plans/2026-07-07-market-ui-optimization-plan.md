# Market UI 优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化市场情报页信息层次——把涨跌情绪做成横幅、板块数据加颜色条、按优先度分组。

**Architecture:** 引入 2 个新组件（MarketBreadthBanner、SectorTable），调整 4 个现有组件的样式；不改数据流、不加依赖。

**Tech Stack:** React + Tailwind CSS + 现有 UI 元件 (Card/Button)

## Global Constraints

- **不使用新依赖**——只用 Tailwind + 现有 `Card`/`Button`/`MetricCard`
- **保持现有数据流**：组件仍接收 `snap: MarketSnapshot`，useMarketSnapshot 钩子不改动
- **保持现有导出**：被 `app/market/page.tsx` 引入的组件名不删，新组件走新文件
- **中文文案沿用现有风格**
- **单一 commit 收尾**

## File Structure

**新增文件（components/market/）：**
- `MarketBreadthBanner.tsx` — 大字涨跌情绪横幅（独立卡片，绿色块+红色块直观对照，涨停/跌停作为副数据）
- `SectorTable.tsx` — 通用板块表格，涨跌幅列嵌入颜色条形；接受 `rows` + `flows` 两个数组，内部做排序与限 15 条

**修改文件（components/market/）：**
- `MarketOverviewCards.tsx` — 改成 2 列响应式、指数卡补强颜色背景，仅留指数维度（涨跌家数已搬到 banner）
- `IndustrySectorTable.tsx` — 改为薄壳包装 `SectorTable`，保留 export 以让 `MarketSectorRow` 测试/后续可换
- `ConceptSectorTable.tsx` — 同上
- `OverseasMarkets.tsx` — 给港股/美股区域加不同边框色调
- `ThemeBoards.tsx` — 加涨跌幅 badge，显示题材对应的板块涨跌
- `AnnouncementList.tsx` — 微调，更紧致
- `SnapshotRefreshButton.tsx` — 改 ghost 样式 + spinner 图标
- `MarketTableUtils.tsx` — 加 `ChangeBar` 工具组件

**修改页面（app/market/page.tsx）：**
- 调整 section 顺序，按设计文档的层次排布
- 删除页面级的涨跌家数（已下放到 banner）

---

### Task 1: 新建 SectorTable 共用组件（带涨跌幅条形）

**Files:**
- Create: `frontend/src/components/market/SectorTable.tsx`
- Modify: `frontend/src/components/market/MarketTableUtils.tsx`
- Modify: `frontend/src/components/market/IndustrySectorTable.tsx`
- Modify: `frontend/src/components/market/ConceptSectorTable.tsx`

**Interfaces:**
- SectorTable receives: `{ title: string; rows: Array<{name: string; change_pct: number}>; flows: Array<{name: string; net_flow: number}> }`
- ChangeBar receives: `{ pct: number }` (渲染颜色条，并显示文字值)
- IndustrySectorTable / ConceptSectorTable 继续导出同名组件，内部薄壳转发到 SectorTable

**步骤：**

- [ ] **Step 1: 在 MarketTableUtils.tsx 追加 ChangeBar 工具组件**

```tsx
/** Shared market table utilities */
export function ChangeCell({ pct }: { pct: number }) {
  const color = pct > 0 ? "text-green-600" : pct < 0 ? "text-red-600" : "text-gray-500";
  const sign = pct > 0 ? "+" : "";
  return <span className={color}>{sign}{pct.toFixed(2)}%</span>;
}

const BAR_MAX = 5; // |pct| <= BAR_MAX 时填满，之外只填半条提示

export function ChangeBar({ pct }: { pct: number }) {
  const fillPct = Math.min(Math.abs(pct), BAR_MAX) / BAR_MAX * 100;
  const positive = pct >= 0;
  const bar = positive ? "bg-green-500" : "bg-red-500";
  const lightBar = positive ? "bg-green-100" : "bg-red-100";
  const textColor = positive ? "text-green-700" : pct < 0 ? "text-red-700" : "text-gray-500";
  const sign = positive ? "+" : "";
  return (
    <div className="flex items-center gap-2">
      <div className={`relative h-2 w-24 rounded-full ${lightBar} overflow-hidden`}>
        <div
          className={`absolute inset-y-0 left-0 ${bar} rounded-full`}
          style={{ width: `${fillPct}%` }}
        />
      </div>
      <span className={`font-mono text-xs tabular-nums ${textColor} w-14 text-right`}>
        {sign}{pct.toFixed(2)}%
      </span>
    </div>
  );
}
```

- [ ] **Step 2: 新建 SectorTable 组件**

`frontend/src/components/market/SectorTable.tsx`：

```tsx
"use client";
import { ChangeBar } from "./MarketTableUtils";

interface Row { name: string; change_pct: number; }
interface Flow { name: string; net_flow: number; }

export function SectorTable({
  title,
  rows,
  flows,
}: {
  title: string;
  rows: Row[];
  flows: Flow[];
}) {
  const flowMap = new Map(flows.map(f => [f.name, f.net_flow]));
  const sorted = [...rows]
    .sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct))
    .slice(0, 15);
  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-950">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-xs text-gray-500">
              <th className="text-left font-medium px-4 py-2">名称</th>
              <th className="text-left font-medium px-4 py-2">涨跌幅</th>
              <th className="text-right font-medium px-4 py-2">净流入(亿)</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s) => {
              const nf = flowMap.get(s.name) ?? 0;
              const flowY = nf / 10000;
              const flowColor =
                flowY > 0 ? "text-green-700" : flowY < 0 ? "text-red-700" : "text-gray-500";
              return (
                <tr key={s.name} className="border-t border-gray-100 hover:bg-gray-50/60">
                  <td className="px-4 py-2 text-gray-950">{s.name}</td>
                  <td className="px-4 py-2">
                    <ChangeBar pct={s.change_pct} />
                  </td>
                  <td className={`px-4 py-2 text-right font-mono tabular-nums text-xs ${flowColor}`}>
                    {flowY > 0 ? "+" : ""}{flowY.toFixed(2)}亿
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 让 IndustrySectorTable 转发到 SectorTable**

整个文件替换为：

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";
import { SectorTable } from "./SectorTable";

export function IndustrySectorTable({ snap }: { snap: MarketSnapshot }) {
  return (
    <SectorTable
      title="行业板块"
      rows={snap.industry_sectors || []}
      flows={snap.industry_flows || []}
    />
  );
}
```

- [ ] **Step 4: 让 ConceptSectorTable 转发到 SectorTable**

整个文件替换为：

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";
import { SectorTable } from "./SectorTable";

export function ConceptSectorTable({ snap }: { snap: MarketSnapshot }) {
  return (
    <SectorTable
      title="概念板块"
      rows={snap.concept_sectors || []}
      flows={snap.concept_flows || []}
    />
  );
}
```

- [ ] **Step 5: 跑类型检查 + 构建 sanity**

```bash
cd frontend && npx tsc --noEmit
```
预期：无错误。如果报错（如 SectorTable 引用的 ChangeBar 路径、类型不匹配），回到对应步骤排查。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/market
git commit -m "feat(market): add SectorTable with ChangeBar; route industry/concept through it"
```

---

### Task 2: 新建 MarketBreadthBanner 横幅

**Files:**
- Create: `frontend/src/components/market/MarketBreadthBanner.tsx`

**Interfaces:**
- 接受 `{ snap: MarketSnapshot }`，从 `breadth` 字段读取 up/down/limit_up/limit_down

**步骤：**

- [ ] **Step 1: 写组件**

`frontend/src/components/market/MarketBreadthBanner.tsx`：

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";

export function MarketBreadthBanner({ snap }: { snap: MarketSnapshot }) {
  const { up, down, limit_up, limit_down } = snap.breadth;
  const total = up + down || 1;
  const upRatio = (up / total) * 100;
  const downRatio = (down / total) * 100;
  const sentiment =
    up > down * 1.3 ? { label: "偏暖", tone: "green" as const } :
    down > up * 1.3 ? { label: "偏弱", tone: "red" as const } :
    { label: "震荡", tone: "gray" as const };
  const toneCls =
    sentiment.tone === "green"
      ? { bg: "bg-green-50", border: "border-green-200", text: "text-green-700", bar: "bg-green-500" } :
    sentiment.tone === "red"
      ? { bg: "bg-red-50", border: "border-red-200", text: "text-red-700", bar: "bg-red-500" } :
    { bg: "bg-gray-50", border: "border-gray-200", text: "text-gray-700", bar: "bg-gray-400" };

  return (
    <div className={`rounded-lg border ${toneCls.border} ${toneCls.bg} p-5 shadow-sm`}>
      <div className="flex items-baseline gap-6 flex-wrap">
        <div>
          <div className="text-xs text-gray-500">市场情绪</div>
          <div className={`mt-1 text-2xl font-semibold ${toneCls.text}`}>{sentiment.label}</div>
        </div>
        <div className="flex items-baseline gap-3">
          <span className="text-3xl font-semibold tracking-tight text-green-700 tabular-nums">{up}</span>
          <span className="text-sm text-gray-500">上涨</span>
        </div>
        <div className="flex items-baseline gap-3">
          <span className="text-3xl font-semibold tracking-tight text-red-700 tabular-nums">{down}</span>
          <span className="text-sm text-gray-500">下跌</span>
        </div>
        <div className="ml-auto flex gap-6 text-sm">
          <div>
            <div className="text-xs text-gray-500">涨停</div>
            <div className="font-semibold text-green-700 tabular-nums">{limit_up}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500">跌停</div>
            <div className="font-semibold text-red-700 tabular-nums">{limit_down}</div>
          </div>
        </div>
      </div>
      {/* 对比条 */}
      <div className="mt-4 flex h-3 w-full overflow-hidden rounded-full bg-gray-200">
        <div className={`${toneCls.tone === "red" ? "bg-red-500" : "bg-green-500"}`} style={{ width: `${upRatio}%` }} />
        <div className="bg-red-500" style={{ width: `${downRatio}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-xs text-gray-500">
        <span>上涨 {upRatio.toFixed(1)}%</span>
        <span>下跌 {downRatio.toFixed(1)}%</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

```bash
cd frontend && npx tsc --noEmit
```
预期：无错误。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/market/MarketBreadthBanner.tsx
git commit -m "feat(market): add MarketBreadthBanner for sentiment hero"
```

---

### Task 3: 调整 MarketOverviewCards（去掉涨跌家数，改用 MetricCard + 颜色背景）

**Files:**
- Modify: `frontend/src/components/market/MarketOverviewCards.tsx`

**步骤：**

- [ ] **Step 1: 重写为只显示指数 + 颜色背景**

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";

function IndexCard({ name, close, changePct }: { name: string; close: number; changePct: number }) {
  const positive = changePct >= 0;
  const bg = positive ? "bg-green-50" : "bg-red-50";
  const border = positive ? "border-green-200" : "border-red-200";
  const valueColor = positive ? "text-green-700" : "text-red-700";
  const subColor = positive ? "text-green-600" : "text-red-600";
  return (
    <div className={`rounded-lg border ${border} ${bg} p-4 shadow-sm`}>
      <div className="text-xs text-gray-500">{name}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${valueColor}`}>
        {close.toFixed(2)}
      </div>
      <div className={`mt-1 text-xs font-medium tabular-nums ${subColor}`}>
        {positive ? "+" : ""}{changePct.toFixed(2)}%
      </div>
    </div>
  );
}

export function MarketOverviewCards({ snap }: { snap: MarketSnapshot }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {snap.indices.map((idx) => (
        <IndexCard key={idx.symbol} name={idx.name} close={idx.close} changePct={idx.change_pct} />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

```bash
cd frontend && npx tsc --noEmit
```
预期：无错误。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/market/MarketOverviewCards.tsx
git commit -m "refactor(market): slim MarketOverviewCards to indices only with tinted bg"
```

---

### Task 4: 调整 OverseasMarkets（港股/美股边框色）+ ThemeBoards（涨幅 badge）

**Files:**
- Modify: `frontend/src/components/market/OverseasMarkets.tsx`
- Modify: `frontend/src/components/market/ThemeBoards.tsx`

**Interfaces:**
- MarketSnapshot 中 overseas 字段含 `market` 字符串（"us"/"hk"/其他），用作边框色判断

**步骤：**

- [ ] **Step 1: 更新 OverseasMarkets 给港股/美股边框色**

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";

function regionStyle(market?: string) {
  if (market === "us") return { border: "border-amber-300", badge: "bg-amber-50 text-amber-700" };
  if (market === "hk") return { border: "border-blue-300", badge: "bg-blue-50 text-blue-700" };
  return { border: "border-gray-200", badge: "bg-gray-100 text-gray-600" };
}

export function OverseasMarkets({ snap }: { snap: MarketSnapshot }) {
  const markets = snap.overseas || [];
  if (!markets.length) return <p className="text-gray-400 text-sm">暂无外围市场数据</p>;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {markets.map((m) => {
        const rs = regionStyle(m.market);
        const sign = (m.change_pct ?? 0) >= 0 ? "+" : "";
        const changeColor = (m.change_pct ?? 0) >= 0 ? "text-green-700" : "text-red-700";
        return (
          <div key={m.symbol} className={`rounded-lg border ${rs.border} bg-white p-3 shadow-sm`}>
            <div className="flex items-center justify-between">
              <div className="text-xs text-gray-500">{m.name}</div>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${rs.badge}`}>
                {(m.market || "其他").toUpperCase()}
              </span>
            </div>
            <div className="mt-1 text-lg font-semibold tabular-nums">{m.close?.toFixed(2) ?? "—"}</div>
            <div className={`text-xs mt-0.5 tabular-nums ${changeColor}`}>
              {m.change_pct != null ? `${sign}${m.change_pct.toFixed(2)}%` : "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: 更新 ThemeBoards 加题材涨跌幅 badge**

由于 `MarketSnapshot.themes` 不含涨跌幅字段，我们仅展示题材 + 龙头股数量，保持不变（涨幅信息将通过 SectorTable 已有的概念数据交叉）。为了让 badge 有用，改用题材对应股票的计数作徽章样式。

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";

export function ThemeBoards({ snap }: { snap: MarketSnapshot }) {
  const themes = snap.themes || [];
  if (!themes.length) return <p className="text-gray-400 text-sm">暂无题材数据（收盘后更新）</p>;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {themes.slice(0, 10).map((t, i) => (
        <div key={i} className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium text-sm text-gray-950 truncate">{t.theme}</span>
            <span className="text-xs text-blue-700 bg-blue-50 border border-blue-100 rounded px-2 py-0.5 whitespace-nowrap">
              {t.count}只
            </span>
          </div>
          {t.stocks?.length > 0 && (
            <div className="mt-2 text-xs text-gray-500 line-clamp-2">
              {t.stocks.map((s) => s.name).join("、")}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: 类型检查**

```bash
cd frontend && npx tsc --noEmit
```
预期：无错误。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/market/OverseasMarkets.tsx frontend/src/components/market/ThemeBoards.tsx
git commit -m "refactor(market): tint overseas regions; tighten theme boards grid"
```

---

### Task 5: 调整 AnnouncementList 微调样式

**Files:**
- Modify: `frontend/src/components/market/AnnouncementList.tsx`

**步骤：**

- [ ] **Step 1: 重写为更紧致的列表样式**

```tsx
"use client";
import { MarketSnapshot } from "@/lib/market";

export function AnnouncementList({ snap }: { snap: MarketSnapshot }) {
  const anns = (snap.announcements || []).slice(0, 10);
  if (!anns.length) return <p className="text-gray-400 text-sm">暂无最新公告</p>;
  return (
    <div className="space-y-3">
      {anns.map((a, i) => (
        <div key={i} className="relative pl-4 py-1">
          <span className="absolute left-0 top-2 h-3 w-0.5 rounded-full bg-blue-500" />
          <div className="text-sm leading-snug text-gray-950">{a.title}</div>
          <div className="text-xs text-gray-500 mt-0.5">
            {a.ann_date}
            {a.fund_code && (
              <>
                <span className="mx-1.5">·</span>
                <span className="text-gray-700">{a.fund_name || a.fund_code}</span>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/market/AnnouncementList.tsx
git commit -m "refactor(market): tighten announcement list spacing"
```

---

### Task 6: 调整 SnapshotRefreshButton 为 ghost 样式 + spinner

**Files:**
- Modify: `frontend/src/components/market/SnapshotRefreshButton.tsx`

**步骤：**

- [ ] **Step 1: 重写为带 spinner 的 ghost 按钮**

```tsx
"use client";
import { useRefreshMarket } from "@/lib/market";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

export function SnapshotRefreshButton() {
  const { mutate, isPending } = useRefreshMarket();
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => mutate()}
      disabled={isPending}
      className="gap-2"
    >
      <RefreshCw className={`h-4 w-4 ${isPending ? "animate-spin" : ""}`} />
      {isPending ? "采集中…" : "刷新数据"}
    </Button>
  );
}
```

- [ ] **Step 2: 类型检查**

```bash
cd frontend && npx tsc --noEmit
```
预期：无错误（按钮组件已有 variant="outline" 类型）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/market/SnapshotRefreshButton.tsx
git commit -m "refactor(market): ghost-style refresh button with spinner"
```

---

### Task 7: 重组市场页 layout

**Files:**
- Modify: `frontend/app/market/page.tsx`

**步骤：**

- [ ] **Step 1: 重写 page.tsx**

```tsx
"use client";
import { useState } from "react";
import { useMarketSnapshot } from "@/lib/market";
import { MarketBreadthBanner } from "@/components/market/MarketBreadthBanner";
import { MarketOverviewCards } from "@/components/market/MarketOverviewCards";
import { IndustrySectorTable } from "@/components/market/IndustrySectorTable";
import { ConceptSectorTable } from "@/components/market/ConceptSectorTable";
import { ThemeBoards } from "@/components/market/ThemeBoards";
import { OverseasMarkets } from "@/components/market/OverseasMarkets";
import { AnnouncementList } from "@/components/market/AnnouncementList";
import { SnapshotRefreshButton } from "@/components/market/SnapshotRefreshButton";
import { SectionHeader } from "@/components/PageHeader";

const DATE_OPTIONS = [
  { label: "今日", value: "today" },
  { label: "昨日", value: "yesterday" },
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
    <div className="space-y-8">
      {/* 页头：标题 + 日期切换 + 刷新按钮 */}
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-gray-950">市场情报</h1>
          <p className="mt-1 text-sm text-gray-500">
            收盘后快照 · 涵盖指数、涨跌家数、行业/概念板块、资金流向、外围市场与公告
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border border-gray-200 bg-white p-0.5">
            {DATE_OPTIONS.map((o) => (
              <button
                key={o.value}
                onClick={() => setDateOpt(o.value)}
                className={`px-3 py-1.5 rounded text-xs font-medium transition ${
                  dateOpt === o.value
                    ? "bg-gray-900 text-white"
                    : "text-gray-600 hover:bg-gray-50"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
          <SnapshotRefreshButton />
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <div className="flex flex-col items-center gap-2">
            <div className="h-8 w-8 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
            <span>加载市场数据…</span>
          </div>
        </div>
      )}

      {error && !isLoading && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          加载失败：{String(error)}
        </div>
      )}

      {snap && !isLoading && (
        <div className="space-y-10">
          {/* 第一层：情绪 + 指数 */}
          <section className="space-y-4">
            <MarketBreadthBanner snap={snap} />
            <MarketOverviewCards snap={snap} />
          </section>

          {/* 第二层：板块 */}
          <section className="space-y-3">
            <SectionHeader title="板块数据" description="按涨跌幅绝对值排序" />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <IndustrySectorTable snap={snap} />
              <ConceptSectorTable snap={snap} />
            </div>
          </section>

          {/* 第三层：外围 + 公告 */}
          <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="space-y-3">
              <SectionHeader title="外围市场" description="美股/港股收盘快览" />
              <OverseasMarkets snap={snap} />
            </div>
            <div className="space-y-3">
              <SectionHeader title="重要公告" description="基金相关最新公告" />
              <AnnouncementList snap={snap} />
            </div>
          </section>

          {/* 题材 */}
          <section className="space-y-3">
            <SectionHeader title="热门题材" description="题材概念龙头股汇总" />
            <ThemeBoards snap={snap} />
          </section>

          <p className="text-xs text-gray-400">
            数据来源：{snap.source} · 截止：{snap.as_of}
          </p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

```bash
cd frontend && npx tsc --noEmit
```
预期：无错误。

- [ ] **Step 3: 全量 lint**

```bash
cd frontend && npx next lint --max-warnings 0
```
预期：无错误、无 warning。如果有现有规则挑战（如未使用变量），回到对应组件修正。

- [ ] **Step 4: 本地构建 sanity**

```bash
cd frontend && npx next build
```
预期：编译成功，无新增警告。如果有"Module not found"，回到对应任务检查 import 路径。

- [ ] **Step 5: Commit**

```bash
git add frontend/app/market/page.tsx
git commit -m "feat(market): reorganize page hierarchy around breadth banner"
```

---

### Task 8: 端到端验证 + 最终 commit

**Files:**
- 无文件改动，仅 sanity 验证

- [ ] **Step 1: 启动 dev server，访问 /market，肉眼检查布局**

```bash
cd frontend && npm run dev
```
手动检查：
1. 情绪横幅在最顶部，颜色对比与对比条正确
2. 指数卡 4 个一排（桌面），涨跌幅背景色与文字色一致
3. 行业/概念板块采用新表格样式，颜色条形正确
4. 外围市场卡片有色边区分
5. 题材卡片变网格
6. 公告列表竖线设计生效

- [ ] **Step 2: git status 确认所有改动已 commit**

```bash
git status
```
预期：工作区干净。如果有新变更，触发额外 commit。

- [ ] **Step 3: 最终总结**

输出所有 commit hash 列表 + 确认实现与设计文档一致。
