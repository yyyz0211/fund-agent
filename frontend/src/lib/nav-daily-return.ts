import type { NavHistory } from "@/types/api";

export interface NavDailyReturnPoint {
  date: string;
  nav: number | null;
  dailyReturn: number | null;
}

export interface PeriodReturnSummary {
  rowsCount: number;
  upCount: number;
  downCount: number;
  flatCount: number;
  bestDay: NavDailyReturnPoint | null;
  worstDay: NavDailyReturnPoint | null;
  cumulativeReturn: number | null;
  navChange: number | null;
  currentStreak: { kind: "up" | "down" | "flat"; length: number } | null;
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

/**
 * 纯函数:对 periodDailyReturnRows 返回的降序行集做汇总统计。
 * 所有计算基于 daily_return 字段(null/0 → flat),navChange 基于累计净值。
 */
export function summarizePeriodReturns(rows: NavDailyReturnPoint[]): PeriodReturnSummary {
  if (!rows.length) {
    return {
      rowsCount: 0,
      upCount: 0,
      downCount: 0,
      flatCount: 0,
      bestDay: null,
      worstDay: null,
      cumulativeReturn: null,
      navChange: null,
      currentStreak: null,
    };
  }

  let upCount = 0;
  let downCount = 0;
  let flatCount = 0;
  let bestDay: NavDailyReturnPoint | null = null;
  let worstDay: NavDailyReturnPoint | null = null;

  for (const row of rows) {
    const r = row.dailyReturn;
    if (r === null || r === 0) {
      flatCount++;
    } else if (r > 0) {
      upCount++;
      if (!bestDay || r > bestDay.dailyReturn!) bestDay = row;
    } else {
      downCount++;
      if (!worstDay || r < worstDay.dailyReturn!) worstDay = row;
    }
  }

  // cumulativeReturn: compound by daily_return, skipping NaN/Infinity
  let cumRet: number | null = null;
  for (const row of rows) {
    const r = row.dailyReturn;
    if (r !== null && Number.isFinite(r)) {
      cumRet = cumRet === null ? r : (1 + cumRet) * (1 + r) - 1;
    }
  }

  // navChange: (last.nav - first.nav) / first.nav — requires both navs valid
  let navChange: number | null = null;
  const validNavRows = rows.filter((r) => r.nav !== null && Number.isFinite(r.nav!));
  if (validNavRows.length >= 2) {
    const last = validNavRows[0].nav!;
    const first = validNavRows[validNavRows.length - 1].nav!;
    if (first !== 0) navChange = (last - first) / first;
  }

  // currentStreak: scan from newest (rows[0])
  let currentStreak: { kind: "up" | "down" | "flat"; length: number } | null = null;
  for (const row of rows) {
    const r = row.dailyReturn;
    const kind: "up" | "down" | "flat" =
      r === null || r === 0 ? "flat" : r > 0 ? "up" : "down";
    if (currentStreak === null) {
      currentStreak = { kind, length: 1 };
    } else if (currentStreak.kind === kind) {
      currentStreak.length++;
    } else {
      break;
    }
  }

  return {
    rowsCount: rows.length,
    upCount,
    downCount,
    flatCount,
    bestDay,
    worstDay,
    cumulativeReturn: cumRet,
    navChange,
    currentStreak,
  };
}
