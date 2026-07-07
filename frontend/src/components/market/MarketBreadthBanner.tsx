"use client";
import { MarketSnapshot } from "@/lib/market";

export function MarketBreadthBanner({ snap }: { snap: MarketSnapshot }) {
  const { up, down, limit_up, limit_down } = snap.breadth;
  const total = up + down || 1;
  const upRatio = (up / total) * 100;
  const downRatio = (down / total) * 100;
  const sentiment =
    up > down * 1.3
      ? { label: "偏暖", tone: "red" as const, note: "上涨家数占优" }
      : down > up * 1.3
      ? { label: "偏弱", tone: "green" as const, note: "下跌家数占优" }
      : { label: "震荡", tone: "gray" as const, note: "涨跌接近平衡" };

  const toneCls =
    sentiment.tone === "red"
      ? {
          bg: "bg-red-50",
          border: "border-red-200",
          text: "text-red-700",
        }
      : sentiment.tone === "green"
      ? {
          bg: "bg-green-50",
          border: "border-green-200",
          text: "text-green-700",
        }
      : {
          bg: "bg-gray-50",
          border: "border-gray-200",
          text: "text-gray-700",
        };

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Market breadth</span>
            <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${toneCls.border} ${toneCls.bg} ${toneCls.text}`}>
              {sentiment.label}
            </span>
          </div>
          <div className="mt-2 text-2xl font-semibold tracking-tight text-gray-950">市场宽度</div>
          <p className="mt-1 text-sm text-gray-500">{sentiment.note}，涨跌停用于观察短线情绪强度。</p>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:min-w-[430px]">
          <div className="rounded-lg bg-red-50 px-4 py-3">
            <div className="text-sm font-medium text-red-700">上涨 {up}</div>
            <div className="mt-1 text-xs text-red-500">{upRatio.toFixed(1)}%</div>
          </div>
          <div className="rounded-lg bg-green-50 px-4 py-3">
            <div className="text-sm font-medium text-green-700">下跌 {down}</div>
            <div className="mt-1 text-xs text-green-500">{downRatio.toFixed(1)}%</div>
          </div>
          <div className="rounded-lg bg-gray-50 px-4 py-3">
            <div className="text-xs text-gray-500">涨停</div>
            <div className="mt-1 font-semibold text-red-700 tabular-nums">{limit_up}</div>
          </div>
          <div className="rounded-lg bg-gray-50 px-4 py-3">
            <div className="text-xs text-gray-500">跌停</div>
            <div className="mt-1 font-semibold text-green-700 tabular-nums">{limit_down}</div>
          </div>
        </div>
      </div>
      <div className="mt-5 flex h-2.5 w-full overflow-hidden rounded-full bg-gray-100">
        <div className="bg-red-500" style={{ width: `${upRatio}%` }} />
        <div className="bg-green-500" style={{ width: `${downRatio}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-xs text-gray-500">
        <span>红色代表上涨家数</span>
        <span>绿色代表下跌家数</span>
      </div>
    </div>
  );
}
