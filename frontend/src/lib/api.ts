import type {
  AnnouncementList, Fund, FundMetrics, MarketLatest,
  NavHistory, NavPoint, WatchlistPatchPayload, WatchlistRow,
  WatchlistUpsertPayload,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(BASE + path);
  if (params) Object.entries(params).forEach(([k, v]) => {
    if (v !== "" && v !== undefined && v !== null) url.searchParams.set(k, String(v));
  });
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} -> ${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

async function send<T>(
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const r = await fetch(BASE + path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const data = await r.json();
      if (data && typeof data.detail === "string") detail = data.detail;
    } catch {
      // body 不是 JSON,保留默认 detail
    }
    throw new Error(`${path} -> ${detail}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export const api = {
  fund: (code: string) => get<Fund>(`/api/funds/${code}`),
  nav: (code: string) => get<NavPoint>(`/api/funds/${code}/nav`),
  navHistory: (code: string, start = "", end = "") =>
    get<NavHistory>(`/api/funds/${code}/nav-history`, { start, end }),
  metrics: (code: string, period = "1m") =>
    get<FundMetrics>(`/api/funds/${code}/metrics`, { period }),
  watchlist: () => get<WatchlistRow[]>("/api/watchlist"),
  watchlistAdd: (payload: WatchlistUpsertPayload) =>
    send<WatchlistRow>("POST", "/api/watchlist", payload),
  watchlistUpdate: (fundCode: string, payload: WatchlistPatchPayload) =>
    send<WatchlistRow>("PATCH", `/api/watchlist/${encodeURIComponent(fundCode)}`, payload),
  watchlistRemove: (fundCode: string) =>
    send<{ fund_code: string; removed: boolean }>(
      "DELETE",
      `/api/watchlist/${encodeURIComponent(fundCode)}`,
    ),
  marketLatest: () => get<MarketLatest>("/api/market/latest"),
  announcements: (fundCode = "", limit = 20) =>
    get<AnnouncementList>("/api/announcements", { fund_code: fundCode, limit }),
};
