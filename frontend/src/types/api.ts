export interface Fund {
  fund_code: string;
  fund_name: string | null;
  fund_type: string | null;
  manager: string | null;
  company: string | null;
  source: string;
  as_of: string;
}

export interface NavPoint {
  fund_code: string;
  nav_date: string;
  accumulated_nav: number | null;
  daily_return: number | null;
  source: string;
  as_of: string;
}

export type InvestmentPlanFrequency = "daily" | "weekly" | "monthly";
export type InvestmentPlanStatus = "active" | "paused";
export type PendingBuyStatus = "pending" | "confirmed" | "cancelled";
export type PendingBuyStage = "submitted" | "confirmable" | "confirmed" | "cancelled";

export interface InvestmentPlan {
  id: number;
  fund_code: string;
  amount: number;
  frequency: InvestmentPlanFrequency;
  day_rule: string;
  start_date: string;
  end_date: string | null;
  status: InvestmentPlanStatus;
  note: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface InvestmentPlanPayload {
  amount: number;
  frequency: InvestmentPlanFrequency;
  day_rule: string;
  start_date: string;
  end_date?: string | null;
  status?: InvestmentPlanStatus;
  note?: string | null;
}

export type InvestmentPlanPatchPayload = Partial<InvestmentPlanPayload>;

export interface PendingBuy {
  id: number;
  fund_code: string;
  request_date: string;
  amount: number;
  fee: number | null;
  note: string | null;
  status: PendingBuyStatus;
  stage: PendingBuyStage;
  expected_confirm_date: string | null;
  pending_amount: number;
  message: string;
  nav_date: string | null;
  nav: number | null;
  share: number | null;
  transaction_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PendingBuyPayload {
  request_date: string;
  amount: number;
  fee?: number | null;
  note?: string | null;
}

export interface PendingBuyConfirmPayload {
  tx_date: string;
}

export interface PendingBuyConfirmResponse {
  pending_buy: PendingBuy;
  transaction: FundTransaction;
  watchlist: WatchlistRow;
}

export interface NavHistory {
  fund_code: string;
  navs: { nav_date: string; accumulated_nav: number | null; daily_return: number | null }[];
  count: number;
  source: string;
  as_of: string;
}

export interface FundMetrics {
  fund_code: string;
  period: string;
  period_return: number | null;
  cumulative_return: number | null;
  max_drawdown: number | null;
  volatility: number | null;
  source: string;
  as_of: string;
}

export interface BriefingSection {
  market_snapshot?: Array<{
    symbol: string;
    name?: string | null;
    close?: number | null;
    change_pct?: number | null;
  }>;
  watchlist_changes?: Array<{
    fund_code: string;
    fund_name?: string | null;
    period_returns?: Record<string, number | null>;
    source?: string | null;
    as_of?: string | null;
  }>;
  errors?: Array<Record<string, unknown>>;
  disclaimer?: string;
}

export interface Briefing {
  id: number;
  briefing_date: string;
  title: string;
  markdown: string;
  sections: BriefingSection | Record<string, unknown>;
  source: string | null;
  as_of: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface BriefingSummary {
  id: number;
  briefing_date: string;
  title: string;
  as_of: string | null;
}

export interface BriefingLatestResponse {
  briefing: Briefing | null;
}

export interface BriefingListResponse {
  briefings: BriefingSummary[];
  limit: number;
}

export interface BriefingRunResponse {
  status: string;
  trigger: string;
  job_id?: string;
}

export interface WatchlistRow {
  id?: number;
  fund_code: string;
  fund_name?: string | null;
  note: string | null;
  is_holding: boolean;
  is_focus: boolean;
  holding_amount: number | null;
  holding_share: number | null;
  cost_nav: number | null;
  buy_date: string | null;
  preload_status?: WatchlistPreloadStatus | null;
  cost_nav_basis: "legacy" | "transactions" | null;
  transaction_count?: number;
  latest_nav?: number | null;
  nav_date?: string | null;
  daily_return?: number | null;
  daily_pnl_abs?: number | null;
  daily_pnl_pct?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export type WatchlistPreloadStatus = "pending" | "running" | "done" | "partial" | "failed" | "missing";

export interface WatchlistPreloadJob {
  job_id: string;
  fund_code: string;
  status: WatchlistPreloadStatus;
  started_at?: string | null;
  finished_at?: string | null;
  missing_data?: string[];
  errors?: string[];
  as_of?: string | null;
}

export type WatchlistAddResponse = WatchlistRow & {
  preload_job?: WatchlistPreloadJob | null;
};

export interface FundTransaction {
  id: number;
  fund_code: string;
  tx_date: string;
  tx_seq: number;
  kind: "buy" | string;
  amount: number;
  nav: number;
  share: number | null;
  fee: number | null;
  note: string | null;
  created_at: string;
}

export interface TransactionUpsertPayload {
  tx_date: string;
  amount: number;
  nav: number;
  fee?: number | null;
  note?: string | null;
  kind?: string;
}

export interface InitialHoldingPayload extends TransactionUpsertPayload {
  is_focus?: boolean | null;
  watchlist_note?: string | null;
}

export interface InitialHoldingResponse {
  transaction: FundTransaction;
  watchlist: WatchlistRow;
  preload_job?: WatchlistPreloadJob | null;
}

export interface WatchlistUpsertPayload {
  fund_code: string;
  note?: string | null;
  is_holding?: boolean | null;
  is_focus?: boolean | null;
  holding_amount?: number | null;
  holding_share?: number | null;
  cost_nav?: number | null;
  buy_date?: string | null;
}

export type WatchlistPatchPayload = Partial<Omit<WatchlistUpsertPayload, "fund_code">>;

export interface MarketIndex {
  symbol: string;
  name: string;
  close: number | null;
  change_pct: number | null;
  market_date: string;
}

export interface MarketLatest {
  rows: MarketIndex[];
  source: string;
  as_of: string;
}

export interface AnnouncementList {
  announcements: unknown[];
  note: string;
  fund_code?: string;
  limit?: number;
}

export interface PnlItem {
  fund_code: string;
  fund_name: string | null;
  is_focus: boolean;
  buy_date: string | null;
  cost_nav: number;
  current_nav: number;
  nav_date: string;
  holding_share: number;
  holding_amount: number | null;
  invested: number;
  market_value: number;
  pnl_abs: number;
  pnl_pct: number | null;
  daily_return?: number | null;
  daily_pnl_abs?: number | null;
  daily_pnl_pct?: number | null;
  cost_nav_basis?: "legacy" | "transactions";
  transaction_count?: number;
}

export interface PnlTotals {
  invested: number;
  market_value: number;
  pnl_abs: number;
  pnl_pct: number | null;
  count: number;
}

export interface PnlSkipped {
  fund_code: string;
  reason: string;
}

export interface PortfolioPnl {
  as_of: string;
  source: string;
  items: PnlItem[];
  totals: PnlTotals;
  skipped: PnlSkipped[];
}

export interface FundSummary {
  fund_code: string;
  fund: Fund | null;
  latest_nav: NavPoint | null;
  metrics: FundMetrics | null;
  nav_history: NavHistory | null;
  watchlist: WatchlistRow | null;
  pnl_item: PnlItem | null;
  pnl_skipped: PnlSkipped | null;
  errors: Record<string, string>;
  source: string;
  as_of: string;
}

export interface ComparisonSeries {
  code: string;
  points: { nav_date: string; accumulated_nav: number | null }[];
}

export type DiagnosisLabel = "暂不碰" | "观察" | "小仓试验" | "候选";
export type DiagnosisConfidence = "low" | "medium" | "high";
export type RiskLightLevel = "red" | "yellow" | "green" | "gray";

export interface RiskLight {
  key: string;
  label: string;
  level: RiskLightLevel;
  value: number | string | null;
  reason: string;
  source: string;
  as_of: string;
}

export interface Pitfall {
  key: string;
  severity: "info" | "warning" | "danger";
  title: string;
  detail: string;
  source: string;
  as_of: string;
}

export interface PeerFund {
  fund_code: string;
  fund_name: string | null;
  fund_type: string | null;
  period_return: number | null;
  max_drawdown: number | null;
  volatility: number | null;
  scale: number | null;
  has_local_nav: boolean;
}

export interface FundDiagnosis {
  fund_code: string;
  period?: string;
  decision_label: DiagnosisLabel;
  confidence: DiagnosisConfidence;
  summary: string;
  reasons: string[];
  risk_lights: RiskLight[];
  pitfalls: Pitfall[];
  suitable_for: { fit: string[]; avoid: string[] };
  peers: PeerFund[];
  missing_data: string[];
  fund?: Fund | null;
  latest_nav?: NavPoint | null;
  source: string;
  as_of: string;
}

export interface DiagnosisRefreshJob {
  job_id: string;
  fund_code: string;
  status: "started" | "running" | "done" | "failed" | "missing";
  started_at: string | null;
  finished_at: string | null;
  missing_data: string[];
  error: string | null;
  as_of: string | null;
}

export interface PortfolioPnlPoint {
  date: string;
  invested: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  missing_funds: string[];
}

export interface PortfolioPnlFund {
  fund_code: string;
  fund_name: string | null;
  current_share: number;
  current_invested: number;
  current_market_value: number;
}

export interface PortfolioPnlSummary {
  invested: number;
  market_value: number;
  pnl_abs: number;
  pnl_pct: number;
  daily_points: number;
}

export interface PortfolioPnlSeries {
  start: string;
  end: string;
  as_of: string;
  source: string;
  dates: PortfolioPnlPoint[];
  per_fund: PortfolioPnlFund[];
  summary: PortfolioPnlSummary;
  uncovered_funds: string[];
}
