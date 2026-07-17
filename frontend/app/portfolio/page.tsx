"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader, SectionHeader } from "@/components/PageHeader";
import { StateBlock } from "@/components/StateBlock";
import { MetricCards, type MetricItem } from "@/components/MetricCard";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { formatDate, formatMoney, formatPct } from "@/lib/format";
import {
  PORTFOLIO_PERIODS,
  periodLabel,
  periodStartForEnd,
  type PortfolioPeriod,
} from "@/lib/portfolio-series";

// 投入 / 市值 / 盈亏 三条线的颜色，与自选池页保持一致；
// 盈亏用红色强调，0 用灰色。
const INVESTED_COLOR = "#2563eb";
const MARKET_COLOR = "#059669";
const PNL_COLOR = "#dc2626";
const NEUTRAL_COLOR = "#6b7280";

export default function PortfolioPage({
  searchParams,
}: {
  searchParams: { codes?: string };
}) {
  const initialCodes = useMemo(() => {
    const raw = searchParams.codes ?? "";
    return raw.split(",").map((s) => s.trim()).filter((s) => s.length > 0);
  }, [searchParams.codes]);

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const [period, setPeriod] = useState<PortfolioPeriod>("1y");
  const start = useMemo(() => periodStartForEnd(period, today), [period, today]);

  const query = useQuery({
    queryKey: queryKeys.portfolio.pnlSeries({ period, start, end: today, codes: initialCodes }),
    queryFn: () => api.portfolioPnlSeries(initialCodes, start, today),
  });

  if (query.isLoading) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <StateBlock title="加载组合数据" tone="loading">
          正在按日期游走计算持仓组合的投入、市值与盈亏...
        </StateBlock>
      </main>
    );
  }

  if (query.error || !query.data) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <StateBlock title="组合数据加载失败" tone="error">
          {String(query.error ?? "未知错误")}
        </StateBlock>
      </main>
    );
  }

  const data = query.data;
  const isEmpty = data.dates.length === 0;
  const summary = data.summary;

  const items: MetricItem[] = [
    {
      label: "累计投入",
      value: `¥ ${formatMoney(summary.invested)}`,
      sub: `区间 ${formatDate(data.start)} — ${formatDate(data.end)}`,
    },
    {
      label: "当前市值",
      value: `¥ ${formatMoney(summary.market_value)}`,
      sub: `${data.per_fund.length} 只持仓`,
    },
    {
      label: "累计盈亏",
      value: `¥ ${formatMoney(summary.pnl_abs)}`,
      sub: `数据点 ${summary.daily_points} 天`,
    },
    {
      label: "累计收益率",
      value: formatPct(summary.pnl_pct),
      sub: "市值 / 投入 − 1",
    },
  ];

  // 各基金当前贡献柱状图
  const perFundRows = data.per_fund.map((f) => ({
    code: f.fund_code,
    name: f.fund_name ?? f.fund_code,
    invested: f.current_invested,
    market: f.current_market_value,
    pnl: Number((f.current_market_value - f.current_invested).toFixed(4)),
  }));

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Portfolio"
        title="组合表现"
        description="基于自选池中 is_holding=true 的逐笔买入与本地日级 NAV，确定性计算每日的投入、市值与累计盈亏。周末 / 节假日照跑，NAV 缺位前向填充。"
        actions={
          <Link href="/watchlist">
            <Button variant="outline">
              <ArrowLeft className="mr-2 h-4 w-4" />
              返回自选池
            </Button>
          </Link>
        }
      />

      <div className="flex flex-wrap gap-2">
        {PORTFOLIO_PERIODS.map((p) => (
          <Button
            key={p}
            variant={p === period ? "default" : "outline"}
            size="sm"
            onClick={() => setPeriod(p)}
          >
            {periodLabel(p)}
          </Button>
        ))}
      </div>

      {isEmpty ? (
        <StateBlock title="暂无持仓组合">
          {data.uncovered_funds.length > 0
            ? `以下基金有买入记录但本地无 NAV 数据，已从图表中排除：${data.uncovered_funds.join(", ")}。`
            : "尚未在自选池中标记任何基金为 is_holding，或本地无 NAV 数据。"}
        </StateBlock>
      ) : (
        <>
          <MetricCards items={items} />

          <Card className="p-6">
            <CardHeader>
              <SectionHeader
                title="投入 / 市值 / 累计盈亏"
                description={`区间 ${formatDate(data.start)} — ${formatDate(data.end)} · ${summary.daily_points} 个交易日`}
              />
            </CardHeader>
            <CardContent>
              <div className="h-[400px]">
                <ResponsiveContainer>
                  <LineChart
                    data={data.dates}
                    margin={{ top: 12, right: 16, bottom: 8, left: 0 }}
                  >
                    <CartesianGrid stroke="#eef2f7" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="date"
                      minTickGap={32}
                      tick={{ fill: "#6b7280", fontSize: 11 }}
                      tickLine={false}
                    />
                    <YAxis
                      yAxisId="left"
                      tick={{ fill: "#6b7280", fontSize: 11 }}
                      tickFormatter={(v) => formatMoney(Number(v))}
                      width={68}
                      tickLine={false}
                    />
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      tick={{ fill: "#6b7280", fontSize: 11 }}
                      tickFormatter={(v) => formatMoney(Number(v))}
                      width={68}
                      tickLine={false}
                    />
                    <Tooltip
                      contentStyle={{
                        borderColor: "#e5e7eb",
                        borderRadius: 8,
                        boxShadow: "0 8px 24px rgb(15 23 42 / 0.08)",
                      }}
                      formatter={(value: number, name: string) => [
                        `¥ ${formatMoney(value)}`,
                        name,
                      ]}
                      labelFormatter={(label) => `日期 ${label}`}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="invested"
                      name="累计投入"
                      stroke={INVESTED_COLOR}
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="market_value"
                      name="当前市值"
                      stroke={MARKET_COLOR}
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="pnl"
                      name="累计盈亏"
                      stroke={PNL_COLOR}
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-3 text-xs text-gray-500">
                来源 {data.source} · 截至 {formatDate(data.as_of)}
              </p>
            </CardContent>
          </Card>

          <Card className="p-6">
            <CardHeader>
              <SectionHeader
                title="各基金当前贡献"
                description="按当前市值与盈亏拆分"
              />
            </CardHeader>
            <CardContent>
              <div className="h-[320px]">
                <ResponsiveContainer>
                  <BarChart
                    data={perFundRows}
                    margin={{ top: 12, right: 16, bottom: 8, left: 0 }}
                  >
                    <CartesianGrid stroke="#eef2f7" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="name"
                      tick={{ fill: "#6b7280", fontSize: 11 }}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fill: "#6b7280", fontSize: 11 }}
                      tickFormatter={(v) => formatMoney(Number(v))}
                      width={68}
                      tickLine={false}
                    />
                    <Tooltip
                      contentStyle={{
                        borderColor: "#e5e7eb",
                        borderRadius: 8,
                        boxShadow: "0 8px 24px rgb(15 23 42 / 0.08)",
                      }}
                      formatter={(value: number, name: string) => [
                        `¥ ${formatMoney(value)}`,
                        name,
                      ]}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="invested" name="投入" fill={INVESTED_COLOR} />
                    <Bar dataKey="market" name="市值" fill={MARKET_COLOR} />
                    <Bar dataKey="pnl" name="盈亏">
                      {perFundRows.map((row, i) => (
                        <Cell
                          key={i}
                          fill={row.pnl === 0 ? NEUTRAL_COLOR : PNL_COLOR}
                          opacity={row.pnl === 0 ? 0.6 : 1}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-xs text-gray-500">
                灰色柱 = 该基金当前盈亏为 0。
              </p>
            </CardContent>
          </Card>

          {data.uncovered_funds.length > 0 && (
            <Card className="border-amber-200 bg-amber-50 p-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-amber-900">估值缺失的基金</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-amber-800">
                以下基金有买入记录但本地无 NAV 数据，已从上表剔除：
                <span className="ml-1 font-mono">{data.uncovered_funds.join(", ")}</span>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
