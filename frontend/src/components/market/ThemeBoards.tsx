"use client";
import { MarketSnapshot } from "@/lib/market";

export function ThemeBoards({ snap }: { snap: MarketSnapshot }) {
  const themes = snap.themes || [];
  if (!themes.length) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-6 text-center text-sm text-gray-400 shadow-sm">
        暂无题材数据（收盘后更新）
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {themes.slice(0, 9).map((t, i) => (
        <div
          key={i}
          className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition hover:border-gray-300 hover:shadow-md"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-semibold text-gray-950">
              {t.theme}
            </span>
            <span className="whitespace-nowrap rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700">
              {t.count}只
            </span>
          </div>
          {t.stocks?.length > 0 && (
            <div className="mt-3 line-clamp-2 text-xs leading-5 text-gray-500">
              {t.stocks.map((s) => s.name).join("、")}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
