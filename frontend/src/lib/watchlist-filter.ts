import type { WatchlistRow } from "@/types/api";

export function filterWatchlistRows(rows: WatchlistRow[], query: string): WatchlistRow[] {
  const keyword = query.trim().toLowerCase();
  if (!keyword) return rows;

  return rows.filter((row) => {
    const code = row.fund_code.toLowerCase();
    const note = (row.note ?? "").toLowerCase();
    return code.includes(keyword) || note.includes(keyword);
  });
}
