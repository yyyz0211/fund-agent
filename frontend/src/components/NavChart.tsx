"use client";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { StateBlock } from "@/components/StateBlock";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { formatNav, formatPct } from "@/lib/format";
import { toNavChartPoints, type NavDailyReturnPoint } from "@/lib/nav-daily-return";
import type { NavHistory } from "@/types/api";

/** Convert period shorthand to a cutoff date string (YYYY-MM-DD). */
export function periodToStart(period: (typeof PERIODS)[number]): string {
  const now = new Date();
  switch (period) {
    case "1w": now.setDate(now.getDate() - 7); break;
    case "1m": now.setMonth(now.getMonth() - 1); break;
    case "3m": now.setMonth(now.getMonth() - 3); break;
    case "6m": now.setMonth(now.getMonth() - 6); break;
    case "1y": now.setFullYear(now.getFullYear() - 1); break;
    case "all": return "";
  }
  return now.toISOString().slice(0, 10);
}

export const PERIODS = ["1w", "1m", "3m", "6m", "1y", "all"] as const;
export type Period = (typeof PERIODS)[number];

export function NavChart({
  code,
  period = "1m",
  navHistory,
  navError,
  navLoading,
}: {
  code: string;
  period?: Period;
  navHistory?: NavHistory | null;
  navError?: unknown;
  navLoading?: boolean;
}) {
  const start = useMemo(() => periodToStart(period), [period]);
  const shouldFetch = navHistory === undefined && navError === undefined && navLoading === undefined;

  const query = useQuery({
    queryKey: queryKeys.fund.navHistory(code, start),
    queryFn: () => api.navHistory(code, start),
    enabled: shouldFetch,
  });
  const data = navHistory === undefined ? query.data : navHistory;
  const isLoading = navLoading ?? query.isLoading;
  const error = navError ?? query.error;

  if (isLoading) return <StateBlock title="加载净值走势" tone="loading">正在读取 {period} 净值历史。</StateBlock>;
  if (error) return <StateBlock title="净值走势加载失败" tone="error">本地暂无净值历史，请先刷新基金数据。</StateBlock>;
  if (!data) return <StateBlock title="暂无净值走势">本地在 {period} 区间内无可用净值历史。</StateBlock>;

  const points = toNavChartPoints(data);

  if (points.length === 0) {
    return <StateBlock title="暂无净值走势">本地在 {period} 区间内无可用净值历史。</StateBlock>;
  }

  return (
    <div className="h-[340px] rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <ResponsiveContainer>
        <LineChart data={points} margin={{ bottom: 8, left: 0, right: 8, top: 8 }}>
          <CartesianGrid stroke="#eef2f7" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="date" minTickGap={28} tick={{ fill: "#6b7280", fontSize: 11 }} tickLine={false} />
          <YAxis
            domain={["auto", "auto"]}
            tick={{ fill: "#6b7280", fontSize: 11 }}
            tickFormatter={(value) => formatNav(Number(value))}
            tickLine={false}
            width={48}
          />
          <Tooltip
            content={<NavTooltip />}
          />
          <Line type="monotone" dataKey="nav" stroke="#2563eb" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function NavTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload?: NavDailyReturnPoint }[];
}) {
  if (!active) return null;
  const point = payload?.[0]?.payload;
  if (!point) return null;
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-lg">
      <div className="font-medium text-gray-900">日期 {point.date}</div>
      <div className="mt-1 flex items-center justify-between gap-6 text-gray-600">
        <span>累计净值</span>
        <span className="font-medium text-gray-900">{formatNav(point.nav)}</span>
      </div>
      <div className="mt-1 flex items-center justify-between gap-6 text-gray-600">
        <span>日涨跌</span>
        <span className={trendTextClass(point.dailyReturn)}>
          {formatPct(point.dailyReturn)}
        </span>
      </div>
    </div>
  );
}

function trendTextClass(value: number | null | undefined) {
  if (value === null || value === undefined) return "font-medium text-gray-600";
  if (value > 0) return "font-medium text-red-600";
  if (value < 0) return "font-medium text-green-600";
  return "font-medium text-gray-600";
}
