"use client";
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Disclaimer } from "@/components/Disclaimer";
import { WatchlistTable } from "@/components/WatchlistTable";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function WatchlistPage() {
  const [q, setQ] = useState("");
  const { data } = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  const filtered = useMemo(() => {
    if (!data) return [];
    if (!q) return data;
    const k = q.toLowerCase();
    return data.filter((r) => r.fund_code.includes(k) || (r.note ?? "").toLowerCase().includes(k));
  }, [data, q]);

  return (
    <>
      <Disclaimer />
      <main className="mx-auto max-w-5xl space-y-4 p-6">
        <h1 className="text-2xl font-bold">自选池</h1>
        <Input placeholder="搜索基金代码或备注…" value={q} onChange={(e) => setQ(e.target.value)} />
        <p className="text-xs text-gray-500">
          自选池增删改（写入操作）在阶段 2 暂不支持；请使用 CLI：
          <code> python -m backend.scripts.add_to_watchlist &lt;code&gt;</code>。
        </p>
        <WatchlistTable />
        {q && data && (
          <p className="text-xs text-gray-500">
            已在前端过滤 {filtered.length} / {data.length} 行（搜索：{q}）
          </p>
        )}
      </main>
    </>
  );
}
