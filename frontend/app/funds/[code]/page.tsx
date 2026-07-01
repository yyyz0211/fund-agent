"use client";
import type { ReactNode } from "react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft, MessageSquareText, Plus, Star } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NavChart } from "@/components/NavChart";
import { MetricCards } from "@/components/MetricCard";
import { PageHeader, SectionHeader } from "@/components/PageHeader";
import { StateBlock } from "@/components/StateBlock";
import { WatchlistDrawer } from "@/components/WatchlistDrawer";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import { formatPct, formatNav, formatDate } from "@/lib/format";

const PERIODS = ["1w", "1m", "3m", "6m", "1y"] as const;
const PERIOD_LABELS: Record<(typeof PERIODS)[number], string> = {
  "1w": "1周",
  "1m": "1月",
  "3m": "3月",
  "6m": "6月",
  "1y": "1年",
};

export default function FundDetail({ params }: { params: { code: string } }) {
  const code = params.code;
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("1m");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();

  const fund = useQuery({ queryKey: ["fund", code], queryFn: () => api.fund(code) });
  const nav = useQuery({ queryKey: ["nav", code], queryFn: () => api.nav(code) });
  const metrics = useQuery({
    queryKey: ["metrics", code, period], queryFn: () => api.metrics(code, period),
  });
  // 直接读 ["watchlist"] 缓存,详情页就能立刻判断该基金是否在池中;
  // 若缓存为空就拉一次。
  const watchlistQuery = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  const inWatchlist = (watchlistQuery.data ?? []).find((r) => r.fund_code === code);
  const fundName = fund.data?.fund_name ?? code;

  async function removeFromWatchlist() {
    if (typeof window !== "undefined") {
      const ok = window.confirm(`确认从自选池移除 ${code}?`);
      if (!ok) return;
    }
    try {
      await api.watchlistRemove(code);
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      toast.push(`已从自选池移除 ${code}`, "success");
    } catch (err) {
      toast.push(`移除失败：${String(err)}`, "error");
    }
  }

  return (
    <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Fund detail"
        title={
          <>
            {fundName} <code className="align-middle text-base font-medium text-gray-500">({code})</code>
          </>
        }
        description="展示本地已有的基金基础信息、净值走势和阶段指标。缺失数据会明确显示为空，不做推断。"
        actions={
          <>
            <Link href="/watchlist">
              <Button variant="outline">
                <ArrowLeft className="mr-2 h-4 w-4" />
                返回自选池
              </Button>
            </Link>
            {inWatchlist ? (
              <Button onClick={removeFromWatchlist} type="button" variant="outline">
                <Star className="mr-2 h-4 w-4 fill-current text-amber-500" />
                已在自选池
              </Button>
            ) : (
              <Button onClick={() => setDrawerOpen(true)} type="button">
                <Plus className="mr-2 h-4 w-4" />
                加入自选
              </Button>
            )}
            <Link href={`/qa?prefill=${encodeURIComponent(`基金 ${code} 净值`)}`}>
              <Button variant={inWatchlist ? "default" : "outline"}>
                <MessageSquareText className="mr-2 h-4 w-4" />
                向助手提问
              </Button>
            </Link>
          </>
        }
      />

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[1.25fr_0.75fr]">
        <Card className="p-6">
          <CardHeader>
            <CardTitle className="text-base">基础信息</CardTitle>
          </CardHeader>
          <CardContent>
            {fund.isLoading ? (
              <StateBlock title="加载基金信息" tone="loading">正在读取本地基金基础资料。</StateBlock>
            ) : fund.error ? (
              <StateBlock title="基金信息加载失败" tone="error">本地没有该基金的基础信息。</StateBlock>
            ) : (
              <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
                <InfoItem label="基金类型">{fund.data?.fund_type ?? "--"}</InfoItem>
                <InfoItem label="基金经理">{fund.data?.manager ?? "--"}</InfoItem>
                <InfoItem label="管理人">{fund.data?.company ?? "--"}</InfoItem>
                <InfoItem label="来源">
                  {fund.data?.source ?? "--"} · {formatDate(fund.data?.as_of)}
                </InfoItem>
              </dl>
            )}
          </CardContent>
        </Card>

        <Card className="p-6">
          <CardHeader>
            <div>
              <CardTitle className="text-base">最新净值</CardTitle>
              <p className="mt-1 text-xs text-gray-500">{formatDate(nav.data?.nav_date)}</p>
            </div>
          </CardHeader>
          <CardContent>
            {nav.isLoading ? (
              <StateBlock title="加载最新净值" tone="loading">正在读取最新净值。</StateBlock>
            ) : nav.error ? (
              <StateBlock title="最新净值加载失败" tone="error">本地没有该基金最新净值。</StateBlock>
            ) : (
              <div className="space-y-4">
                <div className="text-4xl font-semibold tracking-tight text-gray-950">
                  {formatNav(nav.data?.accumulated_nav)}
                </div>
                <div className="rounded-lg bg-gray-50 p-3 text-xs leading-5 text-gray-500">
                  来源 {nav.data?.source ?? "--"} · 数据日期 {formatDate(nav.data?.nav_date)}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      <section>
        <SectionHeader title="净值走势" description="累计净值历史曲线，按本地数据可用范围绘制。" />
        <NavChart code={code} />
      </section>

      <section>
        <SectionHeader
          title="阶段指标"
          description="收益、回撤和波动率均基于历史数据计算。"
          action={
            <div className="flex flex-wrap gap-1 rounded-lg border border-gray-200 bg-white p-1 shadow-sm">
              {PERIODS.map((p) => (
                <Button
                  key={p}
                  size="sm"
                  variant={p === period ? "default" : "ghost"}
                  onClick={() => setPeriod(p)}
                >
                  {PERIOD_LABELS[p]}
                </Button>
              ))}
            </div>
          }
        />
        {metrics.isLoading ? (
          <StateBlock title="计算阶段指标" tone="loading">正在读取并计算 {PERIOD_LABELS[period]} 指标。</StateBlock>
        ) : metrics.error ? (
          <StateBlock title="阶段指标加载失败" tone="error">{String(metrics.error)}</StateBlock>
        ) : (
          <div className="space-y-3">
            <MetricCards items={[
              { label: `${PERIOD_LABELS[period]}收益`, value: formatPct(metrics.data?.period_return) },
              { label: "累计收益", value: formatPct(metrics.data?.cumulative_return) },
              { label: "最大回撤", value: formatPct(metrics.data?.max_drawdown) },
              {
                label: "波动率",
                value:
                  metrics.data?.volatility === null || metrics.data?.volatility === undefined
                    ? "--"
                    : `${(metrics.data.volatility * 100).toFixed(2)}%`,
              },
            ]} />
            <p className="text-xs text-gray-500">
              来源 {metrics.data?.source ?? "--"} · as_of {formatDate(metrics.data?.as_of)}
            </p>
          </div>
        )}
      </section>

      <WatchlistDrawer
        onClose={() => setDrawerOpen(false)}
        onSaved={() => qc.invalidateQueries({ queryKey: ["watchlist"] })}
        open={drawerOpen}
        prefillFundCode={code}
      />
    </main>
  );
}

function InfoItem({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3">
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className="mt-1 font-medium text-gray-900">{children}</dd>
    </div>
  );
}
