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
  is_holding?: boolean;
  is_focus?: boolean;
  holding_amount?: number | null;
  holding_share?: number | null;
  cost_nav?: number | null;
  buy_date?: string | null;
}

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
