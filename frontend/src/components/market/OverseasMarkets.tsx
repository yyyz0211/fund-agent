"use client";
import { MarketSnapshot } from "@/lib/market";

export function OverseasMarkets({ snap }: { snap: MarketSnapshot }) {
  const markets = snap.overseas || [];
  if (!markets.length) return <p className="text-gray-400 text-sm">暂无外围市场数据</p>;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {markets.map(m => (
        <div key={m.symbol} className="border rounded p-3 text-center">
          <div className="text-xs text-gray-500 mb-1">{m.name}</div>
          <div className="text-lg font-mono font-medium">{m.close?.toFixed(2) ?? "—"}</div>
          <div className={`text-sm ${(m.change_pct ?? 0) >= 0 ? "text-green-600" : "text-red-600"}`}>
            {m.change_pct != null ? `${m.change_pct >= 0 ? "+" : ""}${m.change_pct.toFixed(2)}%` : "—"}
          </div>
        </div>
      ))}
    </div>
  );
}
