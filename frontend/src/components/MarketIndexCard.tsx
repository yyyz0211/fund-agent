"use client";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatPct } from "@/lib/format";

export function MarketIndexCard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["market", "latest"], queryFn: api.marketLatest,
  });
  if (isLoading) return <Card><CardContent>加载市场数据…</CardContent></Card>;
  if (error) return (
    <Card>
      <CardContent className="text-red-600">
        本地无市场数据，请先运行 <code>refresh_market</code>（CLI：<code>python -m backend.scripts.smoke_fetch</code>）。
      </CardContent>
    </Card>
  );
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {data!.rows.map((r) => (
        <Card key={r.symbol}>
          <CardHeader><CardTitle>{r.name}</CardTitle></CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{r.close?.toFixed(2) ?? "—"}</div>
            <div className={r.change_pct !== null && r.change_pct > 0 ? "text-red-600" : "text-green-600"}>
              {formatPct(r.change_pct)}  ·  {r.market_date}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
