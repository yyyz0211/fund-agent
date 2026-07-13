"use client";
import { useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertCircle,
  Building2,
  RefreshCw,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { MarketSnapshot, useRefreshMarket, isMarketDateToday } from "@/lib/market";
import { Sparkline } from "./Sparkline";
import { trendTextClass, formatPctWithSign } from "@/lib/market-format";
import { cn } from "@/lib/cn";

type TabKey = "industry" | "concept";
type SectorRow = MarketSnapshot["industry_sectors"][number];

const TABS: Array<{
  key: TabKey;
  label: string;
  icon: LucideIcon;
  field: keyof NonNullable<MarketSnapshot["stale_fields"]>;
}> = [
  { key: "industry", label: "行业板块", icon: Building2, field: "industry_sectors" },
  { key: "concept", label: "概念板块", icon: Sparkles, field: "concept_sectors" },
];

export function SectorTabbedTable({ snap }: { snap: MarketSnapshot }) {
  const [tab, setTab] = useState<TabKey>("industry");
  // 用 snap 自身的 trade_date,确保"昨日 + 重新抓取"抓的是昨天而不是今天
  const refresh = useRefreshMarket(snap.trade_date);
  const rows = rowsForTab(snap, tab);
  const sorted = sortSectorRows(rows);
  const strongest = sorted[0];
  const weakest = sorted[sorted.length - 1];

  return (
    <div className="flex h-[520px] flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      {/* 同一行: 板块强弱 | tabs | 领涨/领跌 chips | 重新抓取 */}
      <div className="flex min-w-0 flex-wrap items-center gap-2 border-b border-gray-100 px-3 py-2">
        <h2 className="mr-1 shrink-0 text-sm font-semibold text-gray-950">板块强弱</h2>

        <div className="flex items-center gap-1 rounded-lg bg-gray-50 p-0.5">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            const stale = snap.stale_fields?.[t.field];
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold transition",
                  active ? "bg-white text-gray-950 shadow-sm" : "text-gray-600 hover:text-gray-950",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {t.label}
                {stale ? <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-label="数据可能不可用" /> : null}
              </button>
            );
          })}
        </div>

        <SectorMoverChips strongest={strongest} weakest={weakest} />

        <div className="ml-auto shrink-0">
          <button
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending || !isMarketDateToday(snap.trade_date)}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-600 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            title={isMarketDateToday(snap.trade_date) ? "重新抓取外网板块数据" : "历史日不支持刷新,只能抓今日数据"}
          >
            <RefreshCw className={cn("h-3 w-3", refresh.isPending && "animate-spin")} />
            {refresh.isPending ? "抓取中…" : "重新抓取"}
          </button>
        </div>
      </div>

      <SectorBody snap={snap} tab={tab} sorted={sorted} />
    </div>
  );
}

function rowsForTab(snap: MarketSnapshot, tab: TabKey): SectorRow[] {
  return tab === "industry" ? snap.industry_sectors : snap.concept_sectors;
}

function sortSectorRows(rows: SectorRow[]): SectorRow[] {
  return [...rows]
    .sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct))
    .slice(0, 15);
}

function SectorMoverChips({ strongest, weakest }: { strongest?: SectorRow; weakest?: SectorRow }) {
  if (!strongest) return null;
  return (
    <>
      <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700">
        <TrendingUp className="h-3 w-3" />
        领涨 {strongest.name}
      </span>
      {weakest && weakest !== strongest ? (
        <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-700">
          <TrendingDown className="h-3 w-3" />
          领跌 {weakest.name}
        </span>
      ) : null}
    </>
  );
}

function SectorBody({ snap, tab, sorted }: { snap: MarketSnapshot; tab: TabKey; sorted: SectorRow[] }) {
  const field = tab === "industry" ? "industry_sectors" : "concept_sectors";
  const rows = tab === "industry" ? snap.industry_sectors : snap.concept_sectors;
  const flows = tab === "industry" ? snap.industry_flows : snap.concept_flows;
  const isStale = snap.stale_fields?.[field] === true;
  const label = tab === "industry" ? "行业" : "概念";

  if (isStale) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-4 py-12 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-50 text-amber-600">
          <AlertCircle className="h-5 w-5" />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-semibold text-gray-950">暂无法获取{label}板块数据</p>
          <p className="text-xs text-gray-500">
            可能是外网接口超时 / 列名变化,或非交易日。可点击右上角"重新抓取"重试。
          </p>
        </div>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-4 py-10 text-center text-sm text-gray-400">
        暂无{label}板块数据(可能非交易日)
      </div>
    );
  }

  const flowMap = new Map(flows.map((f) => [f.name, f.net_flow]));
  const hasHistory = sorted.some((s) => s.history && s.history.length >= 2);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-auto px-1 pb-1">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10">
            <tr className="bg-gray-50 text-xs text-gray-500">
              <th className="px-3 py-2 text-left font-medium">名称</th>
              {hasHistory ? (
                <th className="px-3 py-2 text-left font-medium">趋势</th>
              ) : null}
              <th className="px-3 py-2 text-right font-medium">涨跌幅</th>
              <th className="px-3 py-2 text-right font-medium">净流入</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s) => {
              const nf = flowMap.get(s.name) ?? null;
              const flowY = nf == null ? null : nf;
              const flowText = flowY == null ? "—" : `${flowY > 0 ? "+" : ""}${flowY.toFixed(2)}亿`;
              const flowColor =
                flowY == null ? "text-gray-400"
                : flowY > 0 ? "text-red-700"
                : flowY < 0 ? "text-green-700"
                : "text-gray-500";
              const positive = s.change_pct > 0;
              return (
                <tr key={s.name} className="border-t border-gray-100 transition hover:bg-gray-50/70">
                  <td className="whitespace-nowrap px-3 py-2 font-medium text-gray-950">{s.name}</td>
                  {hasHistory ? (
                    <td className="px-3 py-2">
                      {s.history && s.history.length >= 2 ? (
                        <Sparkline
                          points={s.history}
                          width={80}
                          height={24}
                          toneClass={positive ? "text-red-400" : "text-green-400"}
                          area={false}
                        />
                      ) : null}
                    </td>
                  ) : null}
                  <td className={`whitespace-nowrap px-3 py-2 text-right font-semibold tabular-nums ${trendTextClass(s.change_pct)}`}>
                    {formatPctWithSign(s.change_pct)}
                  </td>
                  <td className={`whitespace-nowrap px-3 py-2 text-right font-mono text-xs tabular-nums ${flowColor}`}>
                    {flowText}
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
