"use client";
import { useState, useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  GitCompareArrows,
  Plus,
  X,
} from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, SectionHeader } from "@/components/PageHeader";
import { StateBlock } from "@/components/StateBlock";
import { api } from "@/lib/api";
import { formatDate, formatNav, formatPct } from "@/lib/format";

const SERIES_COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"];

interface Metrics {
  cumulative_return: number | null;
  max_drawdown: number | null;
  volatility: number | null;
}

function computeMetrics(points: { nav_date: string; accumulated_nav: number | null }[]): Metrics {
  const navs = points.map((p) => p.accumulated_nav).filter((v): v is number => v != null);
  if (navs.length < 2) {
    return { cumulative_return: null, max_drawdown: null, volatility: null };
  }
  // cumulative return
  const cum = navs[navs.length - 1] / navs[0] - 1;
  // max drawdown
  let peak = navs[0];
  let worst = 0;
  for (const v of navs) {
    if (v > peak) peak = v;
    const dd = v / peak - 1;
    if (dd < worst) worst = dd;
  }
  // annualized volatility
  const dr: number[] = [];
  for (let i = 1; i < navs.length; i++) dr.push(navs[i] / navs[i - 1] - 1);
  let vol: number | null = null;
  if (dr.length >= 2) {
    const mean = dr.reduce((a, b) => a + b, 0) / dr.length;
    const variance = dr.reduce((a, b) => a + (b - mean) ** 2, 0) / (dr.length - 1);
    vol = Math.sqrt(variance) * Math.sqrt(252);
  }
  return { cumulative_return: cum, max_drawdown: worst, volatility: vol };
}

export default function ComparePage({
  searchParams,
}: {
  searchParams: { codes?: string };
}) {
  const initialCodes = useMemo(() => {
    const raw = searchParams.codes ?? "";
    return raw.split(",").map((s) => s.trim()).filter((s) => s.length > 0);
  }, [searchParams.codes]);

  const [input, setInput] = useState("");
  const [codes, setCodes] = useState<string[]>(initialCodes.length > 0 ? initialCodes : ["110011", "000001"]);

  function addCode(raw: string) {
    const c = raw.trim();
    if (!c) return;
    if (codes.includes(c)) return;
    setCodes([...codes, c]);
    setInput("");
  }

  function removeCode(c: string) {
    setCodes(codes.filter((x) => x !== c));
  }

  const query = useQuery({
    queryKey: ["compare", codes],
    queryFn: () => api.portfolioCompare(codes),
    enabled: codes.length > 0,
  });

  // 把多 series 合并成单数组,按日期对齐
  const chartData = useMemo(() => {
    if (!query.data) return [] as { date: string; [k: string]: number | string | null }[];
    const dateSet = new Set<string>();
    query.data.series.forEach((s) => s.points.forEach((p) => dateSet.add(p.nav_date)));
    const dates = Array.from(dateSet).sort();
    return dates.map((d) => {
      const row: { date: string; [k: string]: number | string | null } = { date: d };
      query.data!.series.forEach((s) => {
        const point = s.points.find((p) => p.nav_date === d);
        if (point) row[s.code] = point.accumulated_nav;
      });
      return row;
    });
  }, [query.data]);

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Compare"
        title="多基金对比"
        description="把多只基金的累计净值历史按日期对齐,直观比较走势、阶段收益、回撤与年化波动率。数据来自本地库,缺失请先 refresh_fund。"
        actions={
          <Link href="/watchlist">
            <Button variant="outline">
              <ArrowLeft className="mr-2 h-4 w-4" />
              返回自选池
            </Button>
          </Link>
        }
      />

      <Card className="p-5">
        <CardHeader>
          <CardTitle className="text-base">参与对比的基金</CardTitle>
          <p className="mt-1 text-xs text-gray-500">
            至少 1 只,代码 6 位。直接输入 fund_code 然后回车添加。
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            {codes.map((c) => (
              <span
                key={c}
                className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-sm text-blue-700"
              >
                <GitCompareArrows className="h-3.5 w-3.5" />
                {c}
                <button
                  type="button"
                  onClick={() => removeCode(c)}
                  className="ml-1 rounded p-0.5 hover:bg-blue-100"
                  aria-label={`移除 ${c}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            {codes.length === 0 && (
              <span className="text-sm text-gray-500">还没有基金,在下方输入基金代码。</span>
            )}
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              addCode(input);
            }}
          >
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入基金代码,如 110011"
            />
            <Button type="submit" disabled={!input.trim()}>
              <Plus className="mr-1.5 h-4 w-4" />
              添加
            </Button>
          </form>
        </CardContent>
      </Card>

      {codes.length === 0 ? (
        <StateBlock title="请添加基金">至少添加 1 只基金再开始对比。</StateBlock>
      ) : query.isLoading ? (
        <StateBlock title="加载对比数据" tone="loading">正在拉取累计净值历史...</StateBlock>
      ) : query.error ? (
        <StateBlock title="对比数据加载失败" tone="error">{String(query.error)}</StateBlock>
      ) : query.data ? (
        (() => {
          const data = query.data;
          return (
            <>
              <Card className="p-6">
                <CardHeader>
                  <SectionHeader
                    title="累计净值走势"
                    description={`区间 ${formatDate(data.start)} — ${formatDate(data.end)}`}
                  />
                </CardHeader>
                <CardContent>
                  <div className="h-[400px]">
                    <ResponsiveContainer>
                      <LineChart data={chartData} margin={{ top: 12, right: 16, bottom: 8, left: 0 }}>
                        <CartesianGrid stroke="#eef2f7" strokeDasharray="3 3" vertical={false} />
                        <XAxis
                          dataKey="date"
                          minTickGap={32}
                          tick={{ fill: "#6b7280", fontSize: 11 }}
                          tickLine={false}
                        />
                        <YAxis
                          domain={["auto", "auto"]}
                          tick={{ fill: "#6b7280", fontSize: 11 }}
                          tickFormatter={(v) => formatNav(Number(v))}
                          tickLine={false}
                          width={56}
                        />
                        <Tooltip
                          contentStyle={{ borderColor: "#e5e7eb", borderRadius: 8, boxShadow: "0 8px 24px rgb(15 23 42 / 0.08)" }}
                          formatter={(value, name) => [formatNav(Number(value)), name]}
                          labelFormatter={(label) => `日期 ${label}`}
                        />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        {data.series.map((s, i) => (
                          <Line
                            key={s.code}
                            type="monotone"
                            dataKey={s.code}
                            name={s.fund_name ? `${s.code} ${s.fund_name}` : s.code}
                            stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                            strokeWidth={2}
                            dot={false}
                            connectNulls
                          />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <p className="mt-3 text-xs text-gray-500">来源 {data.source}</p>
                </CardContent>
              </Card>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {data.series.map((s) => {
                  const m = computeMetrics(s.points);
                  return (
                    <Card key={s.code} className="p-5">
                      <CardHeader>
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-base">
                            <Link
                              href={`/funds/${encodeURIComponent(s.code)}`}
                              className="hover:text-blue-700"
                            >
                              {s.fund_name ?? s.code}
                            </Link>
                          </CardTitle>
                          <span className="font-mono text-xs text-gray-500">{s.code}</span>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <dl className="space-y-2 text-sm">
                          <MetricRow label="区间收益" value={formatPct(m.cumulative_return)} />
                          <MetricRow label="最大回撤" value={formatPct(m.max_drawdown)} />
                          <MetricRow
                            label="年化波动率"
                            value={
                              m.volatility === null
                                ? "—"
                                : `${(m.volatility * 100).toFixed(2)}%`
                            }
                          />
                        </dl>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </>
          );
        })()
      ) : null}
    </main>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className="text-sm font-semibold text-gray-900">{value}</dd>
    </div>
  );
}
