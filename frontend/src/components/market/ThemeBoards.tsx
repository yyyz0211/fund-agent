"use client";
import { MarketSnapshot } from "@/lib/market";

export function ThemeBoards({ snap }: { snap: MarketSnapshot }) {
  const themes = snap.themes || [];
  if (!themes.length) return <p className="text-gray-400 text-sm">暂无题材数据（收盘后更新）</p>;
  return (
    <div className="space-y-2">
      {themes.map((t, i) => (
        <div key={i} className="border rounded p-3">
          <div className="flex justify-between items-center">
            <span className="font-medium text-sm">{t.theme}</span>
            <span className="text-xs text-gray-400 bg-gray-100 rounded px-2 py-0.5">{t.count}只</span>
          </div>
          {t.stocks?.length > 0 && (
            <div className="text-xs text-gray-400 mt-1">
              {t.stocks.map(s => s.name).join(", ")}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
