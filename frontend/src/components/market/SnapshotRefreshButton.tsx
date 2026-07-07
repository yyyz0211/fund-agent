"use client";
import { useRefreshMarket } from "@/lib/market";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

export function SnapshotRefreshButton() {
  const { mutate, isPending } = useRefreshMarket();
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => mutate()}
      disabled={isPending}
      className="gap-2"
    >
      <RefreshCw className={`h-4 w-4 ${isPending ? "animate-spin" : ""}`} />
      {isPending ? "采集中…" : "刷新数据"}
    </Button>
  );
}
