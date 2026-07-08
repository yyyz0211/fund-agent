"use client";
import { useRefreshMarket } from "@/lib/market";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

export function SnapshotRefreshButton({
  date,
  canRefresh = true,
}: {
  date?: string;
  canRefresh?: boolean;
} = {}) {
  const { mutate, isPending } = useRefreshMarket(date);
  const disabled = isPending || !canRefresh;
  const tooltip = canRefresh
    ? "从 akshare 抓取最新数据(会覆盖当前日期的行)"
    : "历史日不支持刷新:akshare 涨跌家数/板块接口只能拉今天,刷新会把今天数据覆盖过去";
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => mutate()}
      disabled={disabled}
      title={tooltip}
      className="gap-2 border border-gray-200 bg-white shadow-sm hover:border-gray-300 disabled:cursor-not-allowed disabled:opacity-60"
    >
      <RefreshCw className={`h-4 w-4 ${isPending ? "animate-spin" : ""}`} />
      {isPending ? "采集中…" : "刷新数据"}
    </Button>
  );
}
