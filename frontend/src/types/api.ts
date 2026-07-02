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
  source: string;
  as_of: string;
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

export interface WatchlistRow {
  id?: number;
  fund_code: string;
  note: string | null;
  is_holding: boolean;
  is_focus: boolean;
  holding_amount: number | null;
  holding_share: number | null;
  cost_nav: number | null;
  buy_date: string | null;
  cost_nav_basis: "legacy" | "transactions" | null;
  transaction_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

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
