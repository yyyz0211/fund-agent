"use client";
import { useState } from "react";
import { resolveMarketDate, useMarketSnapshot, useMarketEvidence } from "@/lib/market";
import { MarketBreadthBanner } from "@/components/market/MarketBreadthBanner";
import { MarketOverviewCards } from "@/components/market/MarketOverviewCards";
import { IndustrySectorTable } from "@/components/market/IndustrySectorTable";
import { ConceptSectorTable } from "@/components/market/ConceptSectorTable";
import { ThemeBoards } from "@/components/market/ThemeBoards";
import { OverseasMarkets } from "@/components/market/OverseasMarkets";
import { AnnouncementList } from "@/components/market/AnnouncementList";
import { MarketEvidencePanel } from "@/components/market/MarketEvidencePanel";
import { SnapshotRefreshButton } from "@/components/market/SnapshotRefreshButton";
import { SectionHeader } from "@/components/PageHeader";
import { AlertTriangle } from "lucide-react";

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
              收盘后快照，集中查看指数、市场宽度、行业/概念板块、外围市场与公告。
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
        <div className="flex min-h-[360px] items-center justify-center rounded-2xl border border-gray-200 bg-white text-gray-400 shadow-sm">
          <div className="flex flex-col items-center gap-2">
            <div className="h-8 w-8 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
            <span>加载市场数据…</span>
          </div>
        </div>
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
          <section className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
            <MarketBreadthBanner snap={snap} />
            <MarketOverviewCards snap={snap} />
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="板块强弱"
              description="按涨跌幅绝对值排序，红涨绿跌，条形以 0 为中心。"
            />
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <IndustrySectorTable snap={snap} />
              <ConceptSectorTable snap={snap} />
            </div>
          </section>

          <section className="space-y-3">
            <SectionHeader
              title="证据面板"
              description="按类别分组的可追溯政策/公告/宏观证据 — 来自 market_evidence 本地表"
            />
            <MarketEvidencePanel date={date} />
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
