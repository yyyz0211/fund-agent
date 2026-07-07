"use client";
import { useRefreshMarket } from "@/lib/market";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

export function SnapshotRefreshButton() {
  const { mutate, isPending } = useRefreshMarket();
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => mutate()}
      disabled={isPending}
      className="gap-2 border border-gray-200 bg-white shadow-sm hover:border-gray-300"
    >
      <RefreshCw className={`h-4 w-4 ${isPending ? "animate-spin" : ""}`} />
      {isPending ? "采集中…" : "刷新数据"}
    </Button>
  );
}
