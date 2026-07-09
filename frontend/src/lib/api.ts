import type {
  AnnouncementList, Fund, FundMetrics, FundSummary, MarketLatest,
  NavHistory, NavPoint, PortfolioPnl, ComparisonSeries,
  DiagnosisRefreshJob, FundDiagnosis, PeerFund,
  InvestmentPlan, InvestmentPlanPatchPayload, InvestmentPlanPayload,
  PendingBuy, PendingBuyConfirmPayload, PendingBuyConfirmResponse, PendingBuyPayload,
  FundTransaction, InitialHoldingPayload, InitialHoldingResponse, TransactionUpsertPayload,
  WatchlistAddResponse, WatchlistPatchPayload, WatchlistPreloadJob,
  WatchlistRow, WatchlistUpsertPayload,
  PortfolioPnlSeries,
  Briefing, BriefingLatestResponse, BriefingListResponse, BriefingRunResponse,
  BriefingFeedbackPayload, BriefingFeedbackResponse,
  MarketEvidenceResponse, EvidenceCategory,
} from "@/types/api";

// 兼容两种命名:Docker 部署用 NEXT_PUBLIC_API_BASE_URL,本地 dev 历史上用 NEXT_PUBLIC_API_BASE
const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://localhost:8000";

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

const post = <T>(path: string, body?: unknown) => send<T>("POST", path, body);

export const api = {
  fund: (code: string) => get<Fund>(`/api/funds/${code}`),
  nav: (code: string, date = "") => get<NavPoint>(`/api/funds/${code}/nav`, { date }),
  navHistory: (code: string, start = "", end = "") =>
    get<NavHistory>(`/api/funds/${code}/nav-history`, { start, end }),
  metrics: (code: string, period = "1m") =>
    get<FundMetrics>(`/api/funds/${code}/metrics`, { period }),
  fundSummary: (code: string, period = "1m", start = "") =>
    get<FundSummary>(`/api/funds/${code}/summary`, { period, start }),
  fundDiagnosis: (code: string, period = "1y") =>
    get<FundDiagnosis>(`/api/funds/${code}/diagnosis`, { period }),
  fundPeers: (code: string, limit = 5, period = "1y") =>
    get<{ fund_code: string; peers: PeerFund[] }>(`/api/funds/${code}/peers`, { limit, period }),
  refreshFundDiagnosis: (code: string, force = true) =>
    send<DiagnosisRefreshJob>(
      "POST",
      `/api/funds/${encodeURIComponent(code)}/diagnosis/refresh?force=${force ? "true" : "false"}`,
    ),
  fundDiagnosisRefreshJob: (code: string, jobId: string) =>
    get<DiagnosisRefreshJob>(
      `/api/funds/${encodeURIComponent(code)}/diagnosis/refresh/${encodeURIComponent(jobId)}`,
    ),
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
    send<WatchlistAddResponse>("POST", "/api/watchlist", payload),
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
    send<InitialHoldingResponse>(
      "POST",
      `/api/watchlist/${encodeURIComponent(fundCode)}/initial-holding`,
      body,
    ),
  watchlistPreloadJob: (fundCode: string, jobId: string) =>
    get<WatchlistPreloadJob>(
      `/api/watchlist/${encodeURIComponent(fundCode)}/preload/${encodeURIComponent(jobId)}`,
    ),
  watchlistRemoveTransaction: (fundCode: string, txId: number) =>
    send<{ removed: boolean; transaction: FundTransaction; watchlist: WatchlistRow | null }>(
      "DELETE",
      `/api/watchlist/${encodeURIComponent(fundCode)}/transactions/${txId}`,
    ),
  investmentPlans: (fundCode: string) =>
    get<InvestmentPlan[]>(
      `/api/watchlist/${encodeURIComponent(fundCode)}/investment-plans`,
    ),
  investmentPlanAdd: (fundCode: string, payload: InvestmentPlanPayload) =>
    send<InvestmentPlan>(
      "POST",
      `/api/watchlist/${encodeURIComponent(fundCode)}/investment-plans`,
      payload,
    ),
  investmentPlanUpdate: (
    fundCode: string,
    planId: number,
    payload: InvestmentPlanPatchPayload,
  ) =>
    send<InvestmentPlan>(
      "PATCH",
      `/api/watchlist/${encodeURIComponent(fundCode)}/investment-plans/${planId}`,
      payload,
    ),
  investmentPlanRemove: (fundCode: string, planId: number) =>
    send<{ removed: boolean; plan: InvestmentPlan }>(
      "DELETE",
      `/api/watchlist/${encodeURIComponent(fundCode)}/investment-plans/${planId}`,
    ),
  pendingBuys: (fundCode: string) =>
    get<PendingBuy[]>(
      `/api/watchlist/${encodeURIComponent(fundCode)}/pending-buys`,
    ),
  pendingBuyAdd: (fundCode: string, payload: PendingBuyPayload) =>
    send<PendingBuy>(
      "POST",
      `/api/watchlist/${encodeURIComponent(fundCode)}/pending-buys`,
      payload,
    ),
  pendingBuyConfirm: (
    fundCode: string,
    pendingId: number,
    payload: PendingBuyConfirmPayload,
  ) =>
    send<PendingBuyConfirmResponse>(
      "POST",
      `/api/watchlist/${encodeURIComponent(fundCode)}/pending-buys/${pendingId}/confirm`,
      payload,
    ),
  pendingBuyCancel: (fundCode: string, pendingId: number) =>
    send<PendingBuy>(
      "POST",
      `/api/watchlist/${encodeURIComponent(fundCode)}/pending-buys/${pendingId}/cancel`,
    ),
  marketLatest: () => get<MarketLatest>("/api/market/latest"),
  marketEvidence: (date: string, category?: EvidenceCategory, limit: number = 20) =>
    get<MarketEvidenceResponse>("/api/market/evidence", {
      date,
      category: category ?? "",
      limit,
    }),
  briefingLatest: (type = "post_market") =>
    get<BriefingLatestResponse>("/api/briefing/latest", { type }),
  briefingList: (limit = 30, type = "post_market") =>
    get<BriefingListResponse>("/api/briefing/list", { limit, type }),
  briefingRun: (briefType = "post_market") =>
    fetch(BASE + "/api/briefing/run", {
      method: "POST",
      headers: { "X-Local-Trigger": "1", "Content-Type": "application/json" },
      body: JSON.stringify({ brief_type: briefType }),
      cache: "no-store",
    }).then(async (r) => {
      if (!r.ok) throw new Error(`/api/briefing/run -> ${r.status}`);
      return (await r.json()) as BriefingRunResponse;
    }),
  briefingFeedback: (payload: BriefingFeedbackPayload) =>
    post<BriefingFeedbackResponse>("/api/briefing/feedback", payload),
  announcements: (fundCode = "", limit = 20) =>
    get<AnnouncementList>("/api/announcements", { fund_code: fundCode, limit }),
  portfolioPnl: (codes: string[] = []) =>
    get<PortfolioPnl>("/api/portfolio/pnl", { codes: codes.join(",") }),
  portfolioPnlSeries: (codes: string[] = [], start = "", end = "") =>
    get<PortfolioPnlSeries>("/api/portfolio/pnl-series", {
      codes: codes.join(","),
      start,
      end,
    }),
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
