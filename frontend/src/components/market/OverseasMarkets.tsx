"use client";
import { MarketSnapshot } from "@/lib/market";

function regionStyle(market?: string) {
  if (market === "us") {
    return { border: "border-amber-300", badge: "bg-amber-50 text-amber-700" };
  }
  if (market === "hk") {
    return { border: "border-blue-300", badge: "bg-blue-50 text-blue-700" };
  }
  return { border: "border-gray-200", badge: "bg-gray-100 text-gray-600" };
}

export function OverseasMarkets({ snap }: { snap: MarketSnapshot }) {
  const markets = snap.overseas || [];
  if (!markets.length) {
    return <p className="text-gray-400 text-sm">暂无外围市场数据</p>;
  }
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {markets.map((m) => {
        const rs = regionStyle(m.market);
        const sign = (m.change_pct ?? 0) >= 0 ? "+" : "";
        const changeColor =
          (m.change_pct ?? 0) >= 0 ? "text-green-700" : "text-red-700";
        return (
          <div
            key={m.symbol}
            className={`rounded-lg border ${rs.border} bg-white p-3 shadow-sm`}
          >
            <div className="flex items-center justify-between">
              <div className="text-xs text-gray-500">{m.name}</div>
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded ${rs.badge}`}
              >
                {(m.market || "其他").toUpperCase()}
              </span>
            </div>
            <div className="mt-1 text-lg font-semibold tabular-nums">
              {m.close?.toFixed(2) ?? "—"}
            </div>
            <div className={`text-xs mt-0.5 tabular-nums ${changeColor}`}>
              {m.change_pct != null
                ? `${sign}${m.change_pct.toFixed(2)}%`
                : "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
