import type { NavHistory } from "@/types/api";

export interface NavDailyReturnPoint {
  date: string;
  nav: number | null;
  dailyReturn: number | null;
}

export function toNavChartPoints(
  history: Pick<NavHistory, "navs"> | null | undefined,
): NavDailyReturnPoint[] {
  return (history?.navs ?? []).map((p) => ({
    date: p.nav_date,
    nav: p.accumulated_nav,
    dailyReturn: p.daily_return,
  }));
}

export function recentDailyReturnRows(
  history: Pick<NavHistory, "navs"> | null | undefined,
  limit = 5,
): NavDailyReturnPoint[] {
  return toNavChartPoints(history)
    .filter((p) => p.date)
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, limit);
}

/**
 * 详情页"区间涨跌"表使用的全量行集 —— period 已经决定了 nav_history
 * 的区间范围,这里不限制条数。返回按日期降序排列,日期为空(尚未写入
 * 完整快照)的条目会被过滤掉。
 */
export function periodDailyReturnRows(
  history: Pick<NavHistory, "navs"> | null | undefined,
): NavDailyReturnPoint[] {
  return toNavChartPoints(history)
    .filter((p) => p.date)
    .sort((a, b) => b.date.localeCompare(a.date));
}
