"use client";
import { MarketSnapshot } from "@/lib/market";

export function AnnouncementList({ snap }: { snap: MarketSnapshot }) {
  const anns = snap.announcements || [];
  if (!anns.length) return <p className="text-gray-400 text-sm">暂无最新公告</p>;
  return (
    <div className="space-y-2">
      {anns.slice(0, 20).map((a, i) => (
        <div key={i} className="border-l-2 border-blue-400 pl-3 py-1">
          <div className="text-sm leading-snug">{a.title}</div>
          <div className="text-xs text-gray-400 mt-0.5">
            {a.ann_date}
            {a.fund_code && ` · ${a.fund_name || a.fund_code}`}
          </div>
        </div>
      ))}
    </div>
  );
}
