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
  const tone = positive ? "red" : "green";
  const bg = tone === "red" ? "bg-red-50" : "bg-green-50";
  const border = tone === "red" ? "border-red-100" : "border-green-100";
  const valueColor = tone === "red" ? "text-red-700" : "text-green-700";
  const subColor = tone === "red" ? "text-red-600" : "text-green-600";
  return (
    <div className={`rounded-xl border ${border} ${bg} p-4`}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium text-gray-600">{name}</div>
        <div className={`rounded-full bg-white/70 px-2 py-0.5 text-xs font-semibold tabular-nums ${subColor}`}>
          {positive ? "+" : ""}
          {changePct.toFixed(2)}%
        </div>
      </div>
      <div className={`mt-4 text-2xl font-semibold tracking-tight tabular-nums ${valueColor}`}>
        {close.toFixed(2)}
      </div>
    </div>
  );
}

export function MarketOverviewCards({ snap }: { snap: MarketSnapshot }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-950">主要指数</h2>
          <p className="mt-1 text-xs text-gray-500">红涨绿跌，按本地快照展示</p>
        </div>
        <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-500">
          {snap.indices.length} 项
        </span>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        {snap.indices.map((idx) => (
          <IndexCard
            key={idx.symbol}
            name={idx.name}
            close={idx.close}
            changePct={idx.change_pct}
          />
        ))}
      </div>
    </div>
  );
}
