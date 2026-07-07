"use client";
import { MarketSnapshot } from "@/lib/market";

export function ThemeBoards({ snap }: { snap: MarketSnapshot }) {
  const themes = snap.themes || [];
  if (!themes.length) {
    return <p className="text-gray-400 text-sm">暂无题材数据（收盘后更新）</p>;
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {themes.slice(0, 10).map((t, i) => (
        <div
          key={i}
          className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium text-sm text-gray-950 truncate">
              {t.theme}
            </span>
            <span className="text-xs text-blue-700 bg-blue-50 border border-blue-100 rounded px-2 py-0.5 whitespace-nowrap">
              {t.count}只
            </span>
          </div>
          {t.stocks?.length > 0 && (
            <div className="mt-2 text-xs text-gray-500 line-clamp-2">
              {t.stocks.map((s) => s.name).join("、")}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
