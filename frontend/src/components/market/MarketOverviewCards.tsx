"use client";
import { MarketSnapshot } from "@/lib/market";

function IndexCard({
  name,
  close,
  changePct,
}: {
  name: string;
  close: number;
  changePct: number;
}) {
  const positive = changePct >= 0;
  const bg = positive ? "bg-green-50" : "bg-red-50";
  const border = positive ? "border-green-200" : "border-red-200";
  const valueColor = positive ? "text-green-700" : "text-red-700";
  const subColor = positive ? "text-green-600" : "text-red-600";
  return (
    <div className={`rounded-lg border ${border} ${bg} p-4 shadow-sm`}>
      <div className="text-xs text-gray-500">{name}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${valueColor}`}>
        {close.toFixed(2)}
      </div>
      <div className={`mt-1 text-xs font-medium tabular-nums ${subColor}`}>
        {positive ? "+" : ""}
        {changePct.toFixed(2)}%
      </div>
    </div>
  );
}

export function MarketOverviewCards({ snap }: { snap: MarketSnapshot }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {snap.indices.map((idx) => (
        <IndexCard
          key={idx.symbol}
          name={idx.name}
          close={idx.close}
          changePct={idx.change_pct}
        />
      ))}
    </div>
  );
}
