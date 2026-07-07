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
