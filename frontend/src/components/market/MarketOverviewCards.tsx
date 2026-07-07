"use client";
import { MarketSnapshot } from "@/lib/market";
import { MetricCard } from "@/components/MetricCard";

export function MarketOverviewCards({ snap }: { snap: MarketSnapshot }) {
  const { breadth, indices } = snap;
  const total = breadth.up + breadth.down || 1;
  const upRatio = ((breadth.up / total) * 100).toFixed(1);
  const breadthLabel = breadth.up > breadth.down ? "偏暖" : breadth.up < breadth.down ? "偏弱" : "中性";

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {indices.map(idx => (
        <MetricCard
          key={idx.symbol}
          label={idx.name}
          value={idx.close.toFixed(2)}
          sub={idx.change_pct >= 0 ? `+${idx.change_pct.toFixed(2)}%` : `${idx.change_pct.toFixed(2)}%`}
          color={idx.change_pct >= 0 ? "green" : "red"}
        />
      ))}
      <MetricCard label="上涨家数" value={breadth.up.toString()} sub={`${upRatio}%`} color="green" />
      <MetricCard label="下跌家数" value={breadth.down.toString()} sub={breadthLabel} color="red" />
      <MetricCard label="涨停" value={breadth.limit_up.toString()} color="green" />
      <MetricCard label="跌停" value={breadth.limit_down.toString()} color="red" />
    </div>
  );
}
