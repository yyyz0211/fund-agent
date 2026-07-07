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
            className={`px-3 py-1.5 rounded text-sm font-medium transition ${
              dateOpt === o.value
                ? "bg-blue-600 text-white"
                : "bg-gray-100 hover:bg-gray-200 text-gray-600"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>

      {/* 加载状态 */}
      {isLoading && (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <div className="animate-pulse flex flex-col items-center gap-2">
            <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <span>加载市场数据...</span>
          </div>
        </div>
      )}

      {/* 错误状态 */}
      {error && !isLoading && (
        <div className="bg-red-50 border border-red-200 rounded p-4 text-red-700 text-sm">
          加载失败：{String(error)}
        </div>
      )}

      {/* 数据 */}
      {snap && !isLoading && (
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
      )}
    </div>
  );
}
