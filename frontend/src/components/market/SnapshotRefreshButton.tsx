"use client";
import { useRefreshMarket } from "@/lib/market";

export function SnapshotRefreshButton() {
  const { mutate, isPending } = useRefreshMarket();
  return (
    <button
      onClick={() => mutate()}
      disabled={isPending}
      className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50 transition"
    >
      {isPending ? "采集中..." : "刷新市场数据"}
    </button>
  );
}
