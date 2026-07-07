"use client";
import { MarketSnapshot } from "@/lib/market";

export function AnnouncementList({ snap }: { snap: MarketSnapshot }) {
  const anns = (snap.announcements || []).slice(0, 10);
  if (!anns.length) {
    return <p className="text-gray-400 text-sm">暂无最新公告</p>;
  }
  return (
    <div className="space-y-3">
      {anns.map((a, i) => (
        <div key={i} className="relative pl-4 py-1">
          <span className="absolute left-0 top-2 h-3 w-0.5 rounded-full bg-blue-500" />
          <div className="text-sm leading-snug text-gray-950">{a.title}</div>
          <div className="text-xs text-gray-500 mt-0.5">
            {a.ann_date}
            {a.fund_code && (
              <>
                <span className="mx-1.5">·</span>
                <span className="text-gray-700">{a.fund_name || a.fund_code}</span>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
