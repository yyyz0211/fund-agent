import type {
  AnnouncementList, Fund, FundMetrics, FundSummary, MarketLatest,
  NavHistory, NavPoint, PortfolioPnl, ComparisonSeries,
  FundTransaction, InitialHoldingPayload, TransactionUpsertPayload,
  WatchlistPatchPayload, WatchlistRow, WatchlistUpsertPayload,
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
  fundSummary: (code: string, period = "1m", start = "") =>
    get<FundSummary>(`/api/funds/${code}/summary`, { period, start }),
  refreshFund: (code: string) =>
    send<{
      fund_code: string;
      navs_inserted: number;
      already_up_to_date: boolean;
      fund_info_warn?: string | null;
      source: string;
      as_of: string;
    }>("POST", `/api/funds/${encodeURIComponent(code)}/refresh`),
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
  watchlistTransactions: (fundCode: string) =>
    get<FundTransaction[]>(
      `/api/watchlist/${encodeURIComponent(fundCode)}/transactions`,
    ),
  watchlistAddTransaction: (fundCode: string, body: TransactionUpsertPayload) =>
    send<{ transaction: FundTransaction; watchlist: WatchlistRow }>(
      "POST",
      `/api/watchlist/${encodeURIComponent(fundCode)}/transactions`,
      body,
    ),
  watchlistSetInitialHolding: (fundCode: string, body: InitialHoldingPayload) =>
    send<{ transaction: FundTransaction; watchlist: WatchlistRow }>(
      "POST",
      `/api/watchlist/${encodeURIComponent(fundCode)}/initial-holding`,
      body,
    ),
  watchlistRemoveTransaction: (fundCode: string, txId: number) =>
    send<{ removed: boolean; transaction: FundTransaction; watchlist: WatchlistRow | null }>(
      "DELETE",
      `/api/watchlist/${encodeURIComponent(fundCode)}/transactions/${txId}`,
    ),
  marketLatest: () => get<MarketLatest>("/api/market/latest"),
  announcements: (fundCode = "", limit = 20) =>
    get<AnnouncementList>("/api/announcements", { fund_code: fundCode, limit }),
  portfolioPnl: (codes: string[] = []) =>
    get<PortfolioPnl>("/api/portfolio/pnl", { codes: codes.join(",") }),
  portfolioCompare: (codes: string[], start = "", end = "") =>
    get<{
      as_of: string;
      start: string;
      end: string;
      series: (ComparisonSeries & { fund_name: string | null })[];
      source: string;
    }>("/api/portfolio/compare", {
      codes: codes.join(","),
      start,
      end,
    }),
};
