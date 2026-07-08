/** A 股配色：红涨绿跌 */
export function trendTextClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-gray-500";
  if (v > 0) return "text-red-700";
  if (v < 0) return "text-green-700";
  return "text-gray-500";
}

export function trendBgClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "bg-gray-100 text-gray-600";
  if (v > 0) return "bg-red-50 text-red-700";
  if (v < 0) return "bg-green-50 text-green-700";
  return "bg-gray-100 text-gray-600";
}

/** 把 0.5 -> "+0.50%";--/null -> "—" */
export function formatPctWithSign(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

/** "3 分钟前" / "2 小时前" / "昨天" / "07-08 14:30" */
export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return iso.slice(0, 16).replace("T", " ");
  const diffMs = now.getTime() - t.getTime();
  const min = Math.round(diffMs / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.round(hr / 24);
  if (day === 1) return "昨天";
  if (day < 7) return `${day} 天前`;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(t.getMonth() + 1)}-${pad(t.getDate())} ${pad(t.getHours())}:${pad(t.getMinutes())}`;
}
