"use client";
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { WatchlistTable } from "@/components/WatchlistTable";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { filterWatchlistRows } from "@/lib/watchlist-filter";

export default function WatchlistPage() {
  const [q, setQ] = useState("");
  const { data, error, isLoading } = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  const filtered = useMemo(() => {
    if (!data) return [];
    return filterWatchlistRows(data, q);
  }, [data, q]);

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Watchlist"
        title="自选池"
        description="当前阶段只读展示本地自选池。搜索在前端完成，不会修改后端数据。"
      />

      <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full sm:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <Input
              className="pl-9"
              placeholder="搜索基金代码或备注..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <p className="text-xs text-gray-500">
            {data ? `显示 ${filtered.length} / ${data.length} 行` : "等待数据加载"}
          </p>
        </div>
      </section>

      <WatchlistTable
        rows={filtered}
        isLoading={isLoading}
        error={error}
        emptyMessage={q ? "没有匹配当前搜索条件的自选基金。" : undefined}
      />
    </main>
  );
}
