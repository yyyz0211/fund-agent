"use client";
import { MarketSnapshot } from "@/lib/market";

export function AnnouncementList({ snap }: { snap: MarketSnapshot }) {
  const anns = (snap.announcements || []).slice(0, 10);
  if (!anns.length) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-6 text-center text-sm text-gray-400 shadow-sm">
        暂无最新公告
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      {anns.map((a, i) => (
        <div key={i} className="relative border-b border-gray-100 px-4 py-3 last:border-b-0">
          <span className="absolute left-0 top-4 h-4 w-0.5 rounded-full bg-blue-500" />
          <div className="line-clamp-2 text-sm font-medium leading-5 text-gray-950">{a.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500">
            <span>{a.ann_date}</span>
            {a.fund_code && <span className="text-gray-300">·</span>}
            {a.fund_code && <span className="text-gray-700">{a.fund_name || a.fund_code}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
