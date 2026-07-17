export interface PortfolioPnlSeriesKeyParams {
  period: string;
  start: string;
  end: string;
  codes: string[];
}

export const queryKeys = {
  watchlist: {
    all: ["watchlist"] as const,
    transactions: (fundCode: string) => ["watchlistTransactions", fundCode] as const,
    investmentPlans: (fundCode: string) => ["investmentPlans", fundCode] as const,
    pendingBuys: (fundCode: string) => ["pendingBuys", fundCode] as const,
    preloadJob: (fundCode: string, jobId: string) =>
      ["watchlistPreloadJob", fundCode, jobId] as const,
  },
  fund: {
    detail: (fundCode: string) => ["fund", fundCode] as const,
    navForFund: (fundCode: string) => ["nav", fundCode] as const,
    nav: (fundCode: string, navDate: string) => ["nav", fundCode, navDate] as const,
    navHistoryForFund: (fundCode: string) => ["navHistory", fundCode] as const,
    navHistory: (fundCode: string, start: string | undefined) =>
      ["navHistory", fundCode, start] as const,
    metrics: (fundCode: string) => ["metrics", fundCode] as const,
    summaryForFund: (fundCode: string) => ["fundSummary", fundCode] as const,
    summary: (fundCode: string, period: string, start: string | undefined) =>
      ["fundSummary", fundCode, period, start] as const,
    diagnosisForFund: (fundCode: string) => ["fundDiagnosis", fundCode] as const,
    diagnosis: (fundCode: string, period: string) =>
      ["fundDiagnosis", fundCode, period] as const,
    diagnosisRefreshJob: (fundCode: string, jobId: string | null) =>
      ["fundDiagnosisRefreshJob", fundCode, jobId] as const,
  },
  portfolio: {
    pnl: (codes: string[]) => ["portfolioPnl", codes] as const,
    pnlSeries: (params: PortfolioPnlSeriesKeyParams) =>
      ["portfolioPnlSeries", params] as const,
  },
  market: {
    all: ["market"] as const,
    latest: ["market", "latest"] as const,
    snapshots: ["market", "snapshot"] as const,
    snapshot: (tradeDate: string, category: string) =>
      ["market", "snapshot", tradeDate, category] as const,
    evidence: {
      all: ["market", "evidence"] as const,
      list: (tradeDate: string, category: string, limit: number) =>
        ["market", "evidence", tradeDate, category, limit] as const,
      refreshStatuses: ["market", "evidence", "refresh-status"] as const,
      refreshStatus: (category: string) =>
        ["market", "evidence", "refresh-status", category] as const,
    },
    refreshPolling: {
      snapshot: (tradeDate: string | undefined) =>
        ["marketRefreshPolling", "snapshot", tradeDate ?? ""] as const,
      evidence: (tradeDate: string) =>
        ["marketRefreshPolling", "evidence", tradeDate] as const,
    },
  },
  briefing: {
    all: ["briefing"] as const,
    latest: ["briefing", "latest"] as const,
    list: (limit: number) => ["briefing", "list", limit] as const,
    evidence: (tradeDate: string) => ["briefing", "evidence", tradeDate] as const,
  },
  compare: (codes: string[]) => ["compare", codes] as const,
  langgraph: {
    health: ["langgraph", "health"] as const,
  },
} as const;
