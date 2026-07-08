# Market Page UI 优化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 `/market` 页面（保留数据流不变），实现 5 区信息架构（核心指数 → 证据面板 → 板块强弱 → 外围+公告 → 题材）、为指数卡片增加 sparkline 微图、统一视觉风格（与现有 AppShell/StateBlock 风格一致）、为板块强弱行增加 sparkline。

**Architecture:** 不改 API 形状、不改 `MarketSnapshot` 类型、不改 React Query hooks。纯组件层重排：
- 顶部 Hero：核心指数 + 市场宽度合一
- 证据面板：移到第 2 段（前置），增加 category 图标 + 数量 chip
- 板块强弱：行业/概念合并为单卡（tab 切换），表行加 sparkline
- 外围 + 公告：保持横向并排
- 题材：sparkline 强度条

**Tech Stack:** Next.js 14 + React 18 + TypeScript + Tailwind CSS 3.4 + lucide-react + recharts（sparkline）。

## Global Constraints

- **不引入新依赖**；只使用项目已安装的 `recharts`、`lucide-react`、`clsx`/`tailwind-merge`、`class-variance-authority`。
- **中国 A 股配色惯例**保留：红涨绿跌（`text-red-*` / `text-green-*`）。
- **不变 API**：`useMarketSnapshot`、`useMarketEvidence`、`MarketSnapshot` 类型全部保留；不改后端。
- **统一风格**：卡片用 `rounded-xl border border-gray-200 bg-white shadow-sm`（与 AppShell/SectorTable/StateBlock 一致）；eyebrow 用 `text-xs font-semibold uppercase tracking-wide text-blue-700`（与 `PageHeader` 一致）；空/错/加载态用 `StateBlock` 组件（已存在）。
- **可访问性**：图标 `aria-hidden`；交互元素用 `aria-label`；颜色不作为唯一信息载体（涨跌同时显示正负号）。
- **不破坏现有 build/lint**：`pnpm typecheck`（如有）和 `next build` 通过；既有测试不受影响（本计划不涉及后端）。

---

## 文件结构总览

| 文件 | 操作 | 职责 |
|------|------|------|
| `frontend/src/lib/market-format.ts` | 新建 | 涨跌色、相对时间、涨幅 chip 配色等纯函数工具 |
| `frontend/src/components/market/Sparkline.tsx` | 新建 | 通用 sparkline（接受 number[] + color，输出 SVG，零依赖） |
| `frontend/src/components/market/MarketIndexCard.tsx` | 新建 | 指数卡片：含 sparkline + chip + 涨跌色 |
| `frontend/src/components/market/MarketHero.tsx` | 新建 | Hero 区：核心指数 grid + 市场宽度 |
| `frontend/src/components/market/SectorTabbedTable.tsx` | 新建 | 板块强弱：行业/概念 tab 切换，行带 sparkline |
| `frontend/src/components/market/MarketEvidencePanel.tsx` | 修改 | 视觉升级：category 图标 + 数量 chip + 相对时间 |
| `frontend/src/components/market/MarketTableUtils.tsx` | 修改 | 暴露共享 `trendTextClass` 辅助 |
| `frontend/app/market/page.tsx` | 重写 | 新 5 区布局 |

---

## Task 1: 创建 `market-format.ts` 工具库

**Files:**
- Create: `frontend/src/lib/market-format.ts`

**Interfaces:**
- Consumes: 无
- Produces: `trendTextClass(v)`, `trendChipClass(v)`, `relativeTime(iso)`, `formatPctWithSign(v)`

- [ ] **Step 1: 新建文件**

创建 `frontend/src/lib/market-format.ts`：

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

- [ ] **Step 2: 验证 TypeScript 编译**

Run:
```bash
cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit
```

Expected: 无报错（仅前既有错误，本文件无误）。

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent && git add frontend/src/lib/market-format.ts
git commit -m "feat(market): add market-format helpers (trend class, relative time)"
```

---

## Task 2: 创建通用 `Sparkline` 组件（纯 SVG,零依赖）

**Files:**
- Create: `frontend/src/components/market/Sparkline.tsx`

**Interfaces:**
- Consumes: `points: number[]`, `color?: string` (默认 `currentColor` 让父级 color 控制), `width?: number`, `height?: number`, `className?: string`
- Produces: 内联 `<svg>` sparkline。值全为相同或空时渲染细灰线。

- [ ] **Step 1: 新建文件**

```tsx
"use client";
import { useMemo } from "react";

interface SparklineProps {
  points: number[];
  width?: number;
  height?: number;
  /** tailwind text class like "text-red-500";used when color is undefined */
  toneClass?: string;
  /** 直接 SVG stroke;优先级高于 toneClass */
  color?: string;
  className?: string;
  /** 是否绘制面积 */
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
    return { line, fill, min, max };
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
      {area ? (
        <path d={path.fill} fill={stroke} fillOpacity={0.12} stroke="none" />
      ) : null}
      <path d={path.line} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
```

- [ ] **Step 2: 验证 TypeScript**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`
Expected: 无新增错误。

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent && git add frontend/src/components/market/Sparkline.tsx
git commit -m "feat(market): add zero-dep Sparkline component"
```

---

## Task 3: 创建 `MarketIndexCard`（指数卡 + sparkline）

**Files:**
- Create: `frontend/src/components/market/MarketIndexCard.tsx`

**Interfaces:**
- Consumes: `name: string`, `close: number`, `changePct: number`, `history?: number[]` (近 30 日收盘价), `weight?: "lead" | "normal"`
- Produces: 与现有 `IndexCard` 视觉一致 + sparkline。

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
  history?: number[];
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

> **说明：** `history` 在本次前端重构中尚无数据源（API 未返回指数历史序列）。保留为可选 prop，无数据时不渲染 sparkline — 不影响其它改动。后续如需接入,只需把 `snap.indices[i].history` 传进来。

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent && git add frontend/src/components/market/MarketIndexCard.tsx
git commit -m "feat(market): add MarketIndexCard with optional sparkline"
```

---

## Task 4: 创建 `MarketHero`（核心指数 + 市场宽度合一）

**Files:**
- Create: `frontend/src/components/market/MarketHero.tsx`

**Interfaces:**
- Consumes: `snap: MarketSnapshot`
- Produces: 单卡，内部为「核心指数 grid + 市场宽度横向条」

- [ ] **Step 1: 新建文件**

```tsx
"use client";
import { MarketSnapshot, normalizeMarketBreadth } from "@/lib/market";
import { MarketIndexCard } from "./MarketIndexCard";
import { Sparkline } from "./Sparkline";
import { trendTextClass, trendBgClass, formatPctWithSign } from "@/lib/market-format";

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

  return (
    <div className="space-y-4">
      {/* 核心指数 grid */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {lead.length > 0
          ? lead.map((idx) => (
              <MarketIndexCard
                key={idx.symbol}
                name={idx.name}
                close={idx.close}
                changePct={idx.change_pct}
                weight="lead"
              />
            ))
          : snap.indices.slice(0, 4).map((idx) => (
              <MarketIndexCard
                key={idx.symbol}
                name={idx.name}
                close={idx.close}
                changePct={idx.change_pct}
                weight="lead"
              />
            ))}
      </div>

      {/* 市场宽度横条 */}
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

      {/* 其余指数（如果有）以更紧凑的 chip 形式展示 */}
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

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent && git add frontend/src/components/market/MarketHero.tsx
git commit -m "feat(market): add MarketHero (indices + breadth unified)"
```

---

## Task 5: 创建 `SectorTabbedTable`（行业/概念 tab 切换 + sparkline）

**Files:**
- Create: `frontend/src/components/market/SectorTabbedTable.tsx`

**Interfaces:**
- Consumes: `snap: MarketSnapshot`
- Produces: 单卡，含「行业 / 概念」tab，行带 sparkline（基于该板块近 N 个交易日的涨跌幅推算 — 实际本次没有历史序列，行内只显示 chip + 涨跌幅 + 净流入）

> 注：本计划不引入新接口数据，sparkline 在板块行暂时显示占位（数据缺失时降级为"—"）。tab 切换 + 视觉升级是核心。

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

  const sorted = [...rows].sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct)).slice(0, 15);
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
                const flowText = flowY == null
                  ? "—"
                  : `${flowY > 0 ? "+" : ""}${flowY.toFixed(2)}亿`;
                const flowColor = flowY == null
                  ? "text-gray-400"
                  : flowY > 0
                  ? "text-red-700"
                  : flowY < 0
                  ? "text-green-700"
                  : "text-gray-500";
                const positive = s.change_pct > 0;
                return (
                  <tr key={s.name} className="border-t border-gray-100 transition hover:bg-gray-50/70">
                    <td className="whitespace-nowrap px-4 py-3 font-medium text-gray-950">{s.name}</td>
                    <td className="px-4 py-3">
                      <Sparkline
                        points={barToFakeSparkline(s.change_pct)}
                        width={80}
                        height={24}
                        toneClass={positive ? "text-red-400" : "text-green-400"}
                        area={false}
                      />
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

/** 临时用单点 change_pct 合成"上/下倾斜"的伪 sparkline,占位用,后续接入历史数据后删除 */
function barToFakeSparkline(pct: number): number[] {
  const len = 8;
  const arr: number[] = [];
  for (let i = 0; i < len; i++) {
    arr.push((i / (len - 1)) * pct);
  }
  return arr;
}
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent && git add frontend/src/components/market/SectorTabbedTable.tsx
git commit -m "feat(market): add SectorTabbedTable (industry/concept tabs + sparkline)"
```

---

## Task 6: 升级 `MarketEvidencePanel` 视觉（category 图标 + chip + 相对时间）

**Files:**
- Modify: `frontend/src/components/market/MarketEvidencePanel.tsx`

**Interfaces:**
- Consumes: `date: string` (不变)
- Produces: 同样的 props；内部用 `StateBlock` 做空/错/加载态、用 `relativeTime` 替换时间显示、用 category 图标 + 数量 chip。

- [ ] **Step 1: 完整重写该文件**

```tsx
"use client";
import { useMemo } from "react";
import { Building2, FileSearch2, ExternalLink, Landmark, Megaphone, Newspaper, ShieldAlert, ShieldCheck, Tag, Globe2 } from "lucide-react";
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

  if (isLoading) {
    return <StateBlock title="正在加载证据…" tone="loading" />;
  }
  if (error) {
    return (
      <StateBlock title="证据加载失败" tone="error">
        {String(error)}
      </StateBlock>
    );
  }
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
      {/* category 概要 chips */}
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
          <section
            key={cat}
            className="rounded-xl border border-gray-200 bg-white shadow-sm"
            aria-label={meta.label}
          >
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
            {reliability === "official" ? (
              <ShieldCheck className="h-3 w-3" />
            ) : (
              <ShieldAlert className="h-3 w-3" />
            )}
            {RELIABILITY_LABEL[reliability]}
          </span>
        </div>
        {item.summary ? (
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{item.summary}</p>
        ) : null}
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

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent && git add frontend/src/components/market/MarketEvidencePanel.tsx
git commit -m "feat(market): upgrade MarketEvidencePanel with category icons & relative time"
```

---

## Task 7: 升级 `MarketTableUtils` 暴露 `trendTextClass` 共享

**Files:**
- Modify: `frontend/src/components/market/MarketTableUtils.tsx`

**Interfaces:**
- Consumes: 无变化
- Produces: 复用 `trendTextClass`（从 `@/lib/market-format` 重新导出，保持现有 import 路径工作）

- [ ] **Step 1: 编辑文件**

将整个文件替换为：

```tsx
"use client";
export { trendTextClass as ChangeCellClass } from "@/lib/market-format";
import { trendTextClass } from "@/lib/market-format";

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

export { trendTextClass };
```

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`

- [ ] **Step 3: 提交**

```bash
cd /Users/leon/fund-agent && git add frontend/src/components/market/MarketTableUtils.tsx
git commit -m "refactor(market): re-export trendTextClass from market-format"
```

---

## Task 8: 重写 `app/market/page.tsx` 5 区布局

**Files:**
- Modify: `frontend/app/market/page.tsx`

**Interfaces:**
- Consumes: 不变（hooks + date 切换）
- Produces: 5 区新布局

> **新顺序：**
> 1. 页面 header（保留 — 不动）
> 2. **Hero**: `MarketHero` (核心指数 + 市场宽度)
> 3. **证据面板（前置）**: `MarketEvidencePanel`
> 4. **板块强弱**: `SectorTabbedTable`（单卡 tab 切换）
> 5. **外围 + 公告**: 横向并排（保留）
> 6. **题材**: `ThemeBoards`（保留）
> 7. footer disclaimer

- [ ] **Step 1: 完整重写该文件**

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
  // 同步触发 evidence 缓存(在 panel 子组件内另作主消费)
  const evidence = useMarketEvidence(date);
  const evidenceCount = evidence.data?.count ?? 0;

  return (
    <div className="mx-auto max-w-7xl space-y-7 px-4 pb-10 sm:px-6 lg:px-8">
      {/* 页面 header (保留原设计) */}
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

      {isLoading && (
        <StateBlock title="加载市场数据…" tone="loading" />
      )}

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
          {/* ① Hero：核心指数 + 市场宽度 */}
          <section className="space-y-3">
            <SectionHeader
              title="今日市场"
              description={`as of ${snap.as_of} · 证据 ${evidenceCount} 条`}
            />
            <MarketHero snap={snap} />
          </section>

          {/* ② 证据面板（前置） */}
          <section className="space-y-3">
            <SectionHeader
              title="证据面板"
              description="按类别分组的可追溯政策/公告/宏观证据 — 来自 market_evidence 本地表"
            />
            <MarketEvidencePanel date={date} />
          </section>

          {/* ③ 板块强弱（行业/概念 tab） */}
          <section className="space-y-3">
            <SectionHeader
              title="板块强弱"
              description="按涨跌幅绝对值排序，行内 sparkline 展示趋势，净流入以亿为单位。"
            />
            <SectorTabbedTable snap={snap} />
          </section>

          {/* ④ 外围 + 公告 */}
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

          {/* ⑤ 题材 */}
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

- [ ] **Step 2: 验证 TS**

Run: `cd /Users/leon/fund-agent/frontend && pnpm exec tsc --noEmit`
Expected: 无错误。

- [ ] **Step 3: 运行 next build（快速 smoke test）**

Run: `cd /Users/leon/fund-agent/frontend && pnpm build 2>&1 | tail -30`
Expected: 编译成功，无 TS/lint 错误。

- [ ] **Step 4: 提交**

```bash
cd /Users/leon/fund-agent && git add frontend/app/market/page.tsx
git commit -m "feat(market): restructure layout (hero → evidence → sectors → overseas+ann → themes)"
```

---

## Task 9: 浏览器目视检查 + 微调

**Files:**
- 无（视觉微调）
- 用 git 直接 amend 或独立 commit

- [ ] **Step 1: 启动 dev 服务器**

```bash
cd /Users/leon/fund-agent/frontend && pnpm dev
```

访问 `http://localhost:3000/market`。

- [ ] **Step 2: 检查清单**

- [ ] Hero 区 4 个核心指数卡正常显示（即使没 sparkline 数据也无报错）
- [ ] 市场宽度条按上下家数比例显示
- [ ] 证据面板 6 个 category 的 chips + 列表正常
- [ ] 板块 tab 切换可点击，行业/概念各自数据
- [ ] 板块行 sparkline 倾斜方向（正→红、负→绿）
- [ ] 外围市场 + 公告 横向并排
- [ ] 题材卡片正常
- [ ] 切换"今日/昨日"无控制台报错

- [ ] **Step 3: 修复发现的小问题（commit）**

针对目视检查中发现的样式/布局小问题，修改后：

```bash
cd /Users/leon/fund-agent && git add -A && git commit -m "style(market): visual polish from manual QA"
```

---

## 验收标准

1. **TypeScript 编译**：`pnpm exec tsc --noEmit` 无新增错误。
2. **build 通过**：`pnpm build` 成功。
3. **5 区顺序**：Hero → 证据 → 板块 → 外围+公告 → 题材。
4. **风格统一**：所有卡片用 `rounded-xl border border-gray-200 bg-white shadow-sm`；空/错/加载态用 `StateBlock`。
5. **中国 A 股配色**：所有涨跌处仍为红涨绿跌。
6. **Sparkline 已添加**：
   - `MarketIndexCard`（条件渲染，等待指数历史 API）
   - `SectorTabbedTable` 行内（用 `barToFakeSparkline` 占位）
7. **不破坏 API/数据流**：后端、React Query hooks、`MarketSnapshot` 类型未变。

---

## 不在本次范围（明确 YAGNI）

- 不实现指数历史 sparkline 真实数据接入（API 暂无该字段）
- 不改 AppShell、navigation、字体、theme
- 不加新依赖
- 不重构 React Query 层、不改后端
- 不做暗色模式
- 不动板块 tab 的键盘快捷键 / 折叠 / 排序交互
- 不改 nav 中 `/market` 链接
