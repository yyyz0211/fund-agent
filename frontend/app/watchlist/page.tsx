"use client";
import { useMemo, useState } from "react";
import { Plus, Search } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/PageHeader";
import { WatchlistDrawer } from "@/components/WatchlistDrawer";
import { WatchlistTable } from "@/components/WatchlistTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { filterWatchlistRows } from "@/lib/watchlist-filter";
import type { WatchlistRow } from "@/types/api";

export default function WatchlistPage() {
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<WatchlistRow | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const { data, error, isLoading } = useQuery({
    queryKey: ["watchlist"],
    queryFn: api.watchlist,
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    return filterWatchlistRows(data, q);
  }, [data, q]);

  function openAdd() {
    setEditing(null);
    setDrawerOpen(true);
  }

  function openEdit(row: WatchlistRow) {
    setEditing(row);
    setDrawerOpen(true);
  }

  function closeDrawer() {
    setDrawerOpen(false);
    setEditing(null);
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Watchlist"
        title="自选池"
        description="本地维护的基金清单。可新建、编辑备注/持仓信息,或删除条目;搜索在前端完成,不会修改后端数据。"
        actions={
          <Button onClick={openAdd} type="button">
            <Plus className="mr-2 h-4 w-4" />
            加入自选
          </Button>
        }
      />

      <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full sm:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <Input
              className="pl-9"
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索基金代码或备注..."
              value={q}
            />
          </div>
          <p className="text-xs text-gray-500">
            {data ? `显示 ${filtered.length} / ${data.length} 行` : "等待数据加载"}
          </p>
        </div>
      </section>

      <WatchlistTable
        emptyMessage={q ? "没有匹配当前搜索条件的自选基金。" : "尚未加入任何自选基金。点击右上角“加入自选”开始记录。"}
        error={error}
        isLoading={isLoading}
        onEdit={openEdit}
        rows={filtered}
      />

      <WatchlistDrawer
        onClose={closeDrawer}
        open={drawerOpen}
        row={editing}
      />
    </main>
  );
}