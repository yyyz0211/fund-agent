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

// ---- Market evidence (Wave 1) ----
export type EvidenceCategory =
  | "policy"
  | "announcement"
  | "overseas_disclosure"
  | "macro"
  | "sector"
  | "news";

export type EvidenceReliability = "official" | "wire" | "rumor";

export interface MarketEvidenceItem {
  id: number;
  trade_date: string;
  category: EvidenceCategory;
  title: string;
  summary: string | null;
  symbols: string[];
  metrics: Record<string, number | string> | null;
  source: string;
  source_url: string;
  published_at: string | null;
  reliability: EvidenceReliability;
}

export interface MarketEvidenceResponse {
  count: number;
  groups: Partial<Record<EvidenceCategory, MarketEvidenceItem[]>>;
  items?: MarketEvidenceItem[];
}

export interface MarketEvidenceRefreshStatus {
  status: "idle" | "running" | "completed" | "partial" | "failed";
  brief_type: string;
  job_id?: string;
  trigger?: string;
  started_at?: string;
  finished_at?: string;
  error?: string;
  result?: {
    inserted: number;
    fetched: number;
    errors: Array<{ adapter?: string; error: string; details?: Record<string, unknown> }>;
    categories: Record<string, number>;
  };
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
  // Legacy flat fields (for backward compatibility)
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
  // V2 structured fields
  quick_summary?: QuickSummarySection;
  market_state?: MarketStateSection;
  themes_and_flows?: ThemesAndFlowsSection;
  watchlist_impact?: WatchlistImpactSection;
  risk_radar?: RiskRadarSection;
  key_evidence?: KeyEvidenceSection;
  data_statement?: DataStatementSection;
  // V2 sections JSON top-level keys (when sections_json has module_order)
  brief_type?: string;
  profile_version?: string;
  module_order?: string[];
  modules?: Record<string, BriefingModule>;
  warnings?: string[];
}

export interface QuickSummarySection {
  key: string;
  title: string;
  status: "ready" | "partial" | "missing" | "failed";
  market_state?: string;
  main_themes?: string[];
  top_risks?: string[];
  watchlist_impact?: WatchlistImpact;
  confidence?: BriefingConfidence;
}

export interface MarketStateSection {
  key: string;
  title: string;
  status: "ready" | "partial" | "missing" | "failed";
  label?: string;
  summary?: string;
}

export interface ThemeItem {
  name: string;
  direction?: "leading" | "lagging";
  change_pct?: number;
  net_flow?: number;
  trend?: ThemeTrend;
  confidence?: BriefingConfidence;
}

export interface ThemesAndFlowsSection {
  key: string;
  title: string;
  status: "ready" | "partial" | "missing" | "failed";
  items?: ThemeItem[];
  warnings?: string[];
}

export interface WatchlistImpactSection {
  key: string;
  title: string;
  status: "ready" | "partial" | "missing" | "failed";
  summary?: string;
  positive?: Array<{ fund_code: string; fund_name: string; reason: string }>;
  negative?: Array<{ fund_code: string; fund_name: string; reason: string }>;
  neutral?: Array<{ fund_code: string; fund_name: string }>;
  divergent?: Array<{ fund_code: string; fund_name: string; reason: string }>;
}

export interface RiskItem {
  level: RiskLevel;
  signal: string;
  detail?: string;
}

export interface RiskRadarSection {
  key: string;
  title: string;
  status: "ready" | "partial" | "missing" | "failed";
  market?: RiskItem[];
  sector?: RiskItem[];
  watchlist?: RiskItem[];
  data?: RiskItem[];
}

export interface EvidenceItem {
  evidence_id?: number;
  category: string;
  title: string;
  source?: string | null;
  source_url?: string | null;
  published_at?: string | null;
  freshness?: EvidenceFreshness;
  weight?: EvidenceWeight;
}

export interface KeyEvidenceSection {
  key: string;
  title: string;
  status: "ready" | "partial" | "missing" | "failed";
  items?: EvidenceItem[];
  missing_data?: string[];
  warnings?: string[];
}

export interface DataStatementSection {
  key: string;
  title: string;
  status: "ready" | "partial" | "missing" | "failed";
  summary?: string;
  content?: {
    data_quality?: DataQuality;
    confidence?: BriefingConfidence;
    missing_data?: string[];
    failed_modules?: Array<{ module: string; fund_code?: string; reason: string }>;
    data_sources_last_updated?: Record<string, string>;
    disclaimer?: string;
    // watchlist_impact content
    overall?: WatchlistImpact;
    positive?: Array<{ fund_code: string; fund_name: string; reason: string }>;
    negative?: Array<{ fund_code: string; fund_name: string; reason: string }>;
    neutral?: Array<{ fund_code: string; fund_name: string }>;
    divergent?: Array<{ fund_code: string; fund_name: string; reason: string }>;
    // themes_and_flows content
    leading_themes?: ThemeItem[];
    lagging_themes?: ThemeItem[];
    // market_state content
    label?: string;
    reasons?: string[];
    signals?: string[];
    state?: string;
    // risk_radar content (already covered by risk_radar fields above)
    market?: RiskItem[];
    sector?: RiskItem[];
    watchlist?: RiskItem[];
    data?: RiskItem[];
    // key_evidence content
    items?: EvidenceItem[];
    // quick_summary content
    market_state?: string;
    main_themes?: string[];
    top_risks?: string[];
    watchlist_impact?: WatchlistImpact;
  };
  evidence_ids?: number[];
  missing_data?: string[];
  warnings?: string[];
  confidence?: BriefingConfidence;
}

// V2 sections JSON envelope
export interface BriefingModule {
  key: string;
  title: string;
  status: "ready" | "partial" | "missing" | "failed";
  summary?: string;
  content?: DataStatementSection["content"];
  evidence_ids?: number[];
  missing_data?: string[];
  warnings?: string[];
  confidence?: BriefingConfidence;
}

export interface Briefing {
  id: number;
  briefing_date: string;
  brief_type?: string;
  title: string;
  markdown: string;
  sections: BriefingSection | Record<string, unknown>;
  source: string | null;
  as_of: string | null;
  data_quality?: DataQuality | null;
  confidence?: BriefingConfidence | null;
  missing_data?: string[];
  evidence_count?: number | null;
  // V2 fields
  failed_modules?: Array<{ module: string; fund_code?: string; reason: string }>;
  data_sources_last_updated?: Record<string, string>;
  created_at: string | null;
  updated_at: string | null;
}

export type DataQuality = "complete" | "partial" | "market_only" | "failed";
export type BriefingConfidence = "high" | "medium" | "low";
export type MarketState = "偏强" | "偏弱" | "分化" | "退潮" | "数据不足";
export type WatchlistImpact = "positive" | "negative" | "neutral" | "mixed" | "empty";
export type RiskLevel = "high" | "medium" | "low";
export type ThemeTrend = "continuing" | "emerging" | "fading" | "new";
export type EvidenceFreshness = "realtime" | "today" | "recent" | "older";
export type EvidenceWeight = "high" | "medium" | "low";

export interface BriefingSummary {
  id: number;
  briefing_date: string;
  brief_type?: string;
  title: string;
  as_of: string | null;
  data_quality?: DataQuality | null;
  evidence_count?: number | null;
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
  brief_type?: string;
}

export interface BriefingFeedbackPayload {
  briefing_id: number;
  user_id?: string;
  risk_accuracy?: number | null;
  theme_accuracy?: number | null;
  evidence_quality?: number | null;
  overall_satisfaction?: number | null;
  comment?: string | null;
  feedback_meta?: Record<string, unknown>;
}

export interface BriefingFeedbackResponse {
  id: number;
  briefing_id: number;
  user_id: string;
  created_at: string | null;
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
