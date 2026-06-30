"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Disclaimer } from "@/components/Disclaimer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NavChart } from "@/components/NavChart";
import { MetricCards } from "@/components/MetricCard";
import { api } from "@/lib/api";
import { formatPct, formatNav, formatDate } from "@/lib/format";

const PERIODS = ["1w", "1m", "3m", "6m", "1y"] as const;

export default function FundDetail({ params }: { params: { code: string } }) {
  const code = params.code;
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("1m");

  const fund = useQuery({ queryKey: ["fund", code], queryFn: () => api.fund(code) });
  const nav = useQuery({ queryKey: ["nav", code], queryFn: () => api.nav(code) });
  const metrics = useQuery({
    queryKey: ["metrics", code, period], queryFn: () => api.metrics(code, period),
  });

  return (
    <>
      <Disclaimer />
      <main className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">
            {fund.data?.fund_name ?? code}{" "}
            <code className="text-base text-gray-500">({code})</code>
          </h1>
          <Link href={`/qa?prefill=${encodeURIComponent(`基金 ${code} 净值`)}`}>
            <Button variant="outline">向助手提问</Button>
          </Link>
        </div>

        <Card>
          <CardHeader><CardTitle>基础信息</CardTitle></CardHeader>
          <CardContent>
            {fund.isLoading ? "加载中…" : (
              <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
                <div><span className="text-gray-500">类型：</span>{fund.data?.fund_type ?? "—"}</div>
                <div><span className="text-gray-500">经理：</span>{fund.data?.manager ?? "—"}</div>
                <div><span className="text-gray-500">管理人：</span>{fund.data?.company ?? "—"}</div>
                <div>
                  <span className="text-gray-500">来源：</span>
                  {fund.data?.source} · {formatDate(fund.data?.as_of)}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <section>
          <h2 className="mb-2 text-lg font-semibold">
            最新净值{" "}
            <span className="text-sm text-gray-500">{formatDate(nav.data?.nav_date)}</span>
          </h2>
          <Card>
            <CardContent>
              <div className="text-3xl font-bold">{formatNav(nav.data?.accumulated_nav)}</div>
              <div className="text-xs text-gray-500">
                来源 {nav.data?.source} · 数据日期 {formatDate(nav.data?.nav_date)}
              </div>
            </CardContent>
          </Card>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold">净值走势</h2>
          <NavChart code={code} />
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold">阶段指标</h2>
            <div className="flex gap-1">
              {PERIODS.map((p) => (
                <Button
                  key={p}
                  size="sm"
                  variant={p === period ? "default" : "outline"}
                  onClick={() => setPeriod(p)}
                >
                  {p}
                </Button>
              ))}
            </div>
          </div>
          {metrics.isLoading ? (
            <p className="text-sm text-gray-500">计算中…</p>
          ) : metrics.error ? (
            <p className="text-sm text-red-600">{String(metrics.error)}</p>
          ) : (
            <MetricCards items={[
              { label: `${period} 收益`, value: formatPct(metrics.data?.period_return) },
              { label: "累计收益", value: formatPct(metrics.data?.cumulative_return) },
              { label: "最大回撤", value: formatPct(metrics.data?.max_drawdown) },
              {
                label: "波动率",
                value: metrics.data?.volatility
                  ? `${(metrics.data.volatility * 100).toFixed(2)}%`
                  : "—",
              },
            ]} />
          )}
        </section>
      </main>
    </>
  );
}
