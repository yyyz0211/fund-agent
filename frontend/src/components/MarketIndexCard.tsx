"use client";
import { useQuery } from "@tanstack/react-query";
import { Activity, TrendingDown, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StateBlock } from "@/components/StateBlock";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { formatPct } from "@/lib/format";

export function MarketIndexCard() {
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.market.latest, queryFn: api.marketLatest,
  });
  if (isLoading) return <StateBlock title="加载市场数据" tone="loading">正在读取本地缓存的指数数据。</StateBlock>;
  if (error) return (
    <StateBlock title="市场数据加载失败" tone="error">
      本地无市场数据，请先刷新市场数据后再查看。
    </StateBlock>
  );

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {data!.rows.map((r) => (
        <Card key={r.symbol} className="p-5">
          <CardHeader>
            <div>
              <CardTitle className="text-base">{r.name}</CardTitle>
              <p className="mt-1 text-xs text-gray-500">{r.symbol}</p>
            </div>
            <TrendIcon value={r.change_pct} />
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-3xl font-semibold tracking-tight text-gray-950">
              {r.close?.toFixed(2) ?? "--"}
            </div>
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className={trendClass(r.change_pct)}>
                {formatPct(r.change_pct)}
              </span>
              <span className="text-gray-500">{r.market_date}</span>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function trendClass(value: number | null) {
  if (value === null) return "rounded-full bg-gray-100 px-2 py-1 font-medium text-gray-600";
  if (value > 0) return "rounded-full bg-red-50 px-2 py-1 font-medium text-red-600";
  if (value < 0) return "rounded-full bg-green-50 px-2 py-1 font-medium text-green-600";
  return "rounded-full bg-gray-100 px-2 py-1 font-medium text-gray-600";
}

function TrendIcon({ value }: { value: number | null }) {
  const Icon = value === null ? Activity : value >= 0 ? TrendingUp : TrendingDown;
  const tone =
    value === null
      ? "bg-gray-100 text-gray-500"
      : value >= 0
        ? "bg-red-50 text-red-600"
        : "bg-green-50 text-green-600";

  return (
    <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${tone}`}>
      <Icon className="h-4 w-4" />
    </span>
  );
}
