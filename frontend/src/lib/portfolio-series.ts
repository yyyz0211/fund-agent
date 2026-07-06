import type { PortfolioPnlSeries } from "@/types/api";

// 组合页的时间区间选项。"all" 表示不传 start，由后端回落到全量。
export const PORTFOLIO_PERIODS = ["1m", "3m", "6m", "1y", "all"] as const;
export type PortfolioPeriod = (typeof PORTFOLIO_PERIODS)[number];

const PERIOD_DAYS: Record<Exclude<PortfolioPeriod, "all">, number> = {
  "1m": 30,
  "3m": 90,
  "6m": 180,
  "1y": 365,
};

// 由区间与结束日期推算 start（YYYY-MM-DD）。"all" 返回空串，交给后端默认窗口。
export function periodStartForEnd(period: PortfolioPeriod, end: string): string {
  if (period === "all") return "";
  const days = PERIOD_DAYS[period];
  const d = new Date(`${end}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export function periodLabel(period: PortfolioPeriod): string {
  return period === "all" ? "全部" : period.toUpperCase();
}

// 从完整 series 里抽出前端 KPI 卡需要的紧凑摘要。
export function compactPnlSummary(series: PortfolioPnlSeries): {
  invested: number;
  market: number;
  pnl: number;
  pnlPct: number;
} {
  return {
    invested: series.summary.invested,
    market: series.summary.market_value,
    pnl: series.summary.pnl_abs,
    pnlPct: series.summary.pnl_pct,
  };
}
