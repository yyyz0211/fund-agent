"use client";
import { MarketSnapshot } from "@/lib/market";

export function MarketBreadthBanner({ snap }: { snap: MarketSnapshot }) {
  const { up, down, limit_up, limit_down } = snap.breadth;
  const total = up + down || 1;
  const upRatio = (up / total) * 100;
  const downRatio = (down / total) * 100;
  const sentiment =
    up > down * 1.3
      ? { label: "偏暖", tone: "green" as const }
      : down > up * 1.3
      ? { label: "偏弱", tone: "red" as const }
      : { label: "震荡", tone: "gray" as const };

  const toneCls =
    sentiment.tone === "green"
      ? {
          bg: "bg-green-50",
          border: "border-green-200",
          text: "text-green-700",
        }
      : sentiment.tone === "red"
      ? {
          bg: "bg-red-50",
          border: "border-red-200",
          text: "text-red-700",
        }
      : {
          bg: "bg-gray-50",
          border: "border-gray-200",
          text: "text-gray-700",
        };

  return (
    <div className={`rounded-lg border ${toneCls.border} ${toneCls.bg} p-5 shadow-sm`}>
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3">
        <div>
          <div className="text-xs text-gray-500">市场情绪</div>
          <div className={`mt-1 text-2xl font-semibold ${toneCls.text}`}>{sentiment.label}</div>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tracking-tight text-green-700 tabular-nums">
            {up}
          </span>
          <span className="text-sm text-gray-500">上涨</span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tracking-tight text-red-700 tabular-nums">
            {down}
          </span>
          <span className="text-sm text-gray-500">下跌</span>
        </div>
        <div className="ml-auto flex gap-8 text-sm">
          <div>
            <div className="text-xs text-gray-500">涨停</div>
            <div className="font-semibold text-green-700 tabular-nums">{limit_up}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500">跌停</div>
            <div className="font-semibold text-red-700 tabular-nums">{limit_down}</div>
          </div>
        </div>
      </div>
      <div className="mt-4 flex h-3 w-full overflow-hidden rounded-full bg-gray-200">
        <div className="bg-green-500" style={{ width: `${upRatio}%` }} />
        <div className="bg-red-500" style={{ width: `${downRatio}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-xs text-gray-500">
        <span>上涨 {upRatio.toFixed(1)}%</span>
        <span>下跌 {downRatio.toFixed(1)}%</span>
      </div>
    </div>
  );
}
