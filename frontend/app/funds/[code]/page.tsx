"use client";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft, DownloadCloud, GitCompareArrows, MessageSquareText, Plus, Star } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NavChart, PERIODS, periodToStart } from "@/components/NavChart";
import { PageHeader, SectionHeader } from "@/components/PageHeader";
import { HoldingCard } from "@/components/HoldingCard";
import { FundDiagnosisCard } from "@/components/FundDiagnosisCard";
import { StateBlock } from "@/components/StateBlock";
import { WatchlistDrawer } from "@/components/WatchlistDrawer";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import { formatPct, formatNav, formatDate } from "@/lib/format";
import {
  periodDailyReturnRows,
  summarizePeriodReturns,
  type NavDailyReturnPoint,
} from "@/lib/nav-daily-return";
import type { FundMetrics } from "@/types/api";

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
  const [refreshJobId, setRefreshJobId] = useState<string | null>(null);
  const toast = useToast();
  const qc = useQueryClient();
  const start = periodToStart(period);

  const summary = useQuery({
    queryKey: ["fundSummary", code, period, start],
    queryFn: () => api.fundSummary(code, period, start),
  });
  const summaryData = summary.data;
  const errors = summaryData?.errors ?? {};
  const fundData = summaryData?.fund ?? null;
  const latestNav = summaryData?.latest_nav ?? null;
  const metricsData = summaryData?.metrics ?? null;
  const inWatchlist = summaryData?.watchlist ?? null;
  const fundName = fundData?.fund_name ?? code;
  const dailyReturnRows = periodDailyReturnRows(summaryData?.nav_history);

  const diagnosis = useQuery({
    queryKey: ["fundDiagnosis", code, period],
    queryFn: () => api.fundDiagnosis(code, period),
  });

  const refreshDiagnosisJob = useQuery({
    queryKey: ["fundDiagnosisRefreshJob", code, refreshJobId],
    queryFn: () => api.fundDiagnosisRefreshJob(code, refreshJobId!),
    enabled: Boolean(refreshJobId),
    refetchInterval: refreshJobId ? 1000 : false,
  });

  // 当本地无 Fund 数据时,提供"立即拉取"按钮 —— 用户从自选池进来
  // 但还没 refresh_fund 过,详情页会 404。点按钮调 POST /api/funds/{code}/refresh,
  // 成功后 invalidate 所有相关 query(基础信息/净值/历史/指标/持仓卡)。
  const refreshFund = useMutation({
    mutationFn: () => api.refreshFund(code),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["fundSummary", code] });
      qc.invalidateQueries({ queryKey: ["fund", code] });
      qc.invalidateQueries({ queryKey: ["nav", code] });
      qc.invalidateQueries({ queryKey: ["navHistory", code] });
      qc.invalidateQueries({ queryKey: ["metrics", code] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", [code]] });
      qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
      if (res.already_up_to_date) {
        toast.push(`${code} 本地已是最新`, "success");
      } else {
        const base = `已拉取 ${code},新增 ${res.navs_inserted} 条净值`;
        // 雪球蛋卷 API 现在 100% 拒服,fund_name/manager 等可能拉不到;
        // 提示用户知道"基础信息不全"但 NAV 可用。
        const note = res.fund_info_warn
          ? `${base}(基础信息暂未拉取)`
          : base;
        toast.push(note, res.fund_info_warn ? "info" : "success");
      }
    },
    onError: (err) => {
      toast.push(`拉取失败：${String(err)}`, "error");
    },
  });

  async function removeFromWatchlist() {
    if (typeof window !== "undefined") {
      const ok = window.confirm(`确认从自选池移除 ${code}?`);
      if (!ok) return;
    }
    try {
      await api.watchlistRemove(code);
      // 与 `refreshFund` 对齐:除了更新自选池列表,本详情页用到的
      // fund / nav / navHistory / metrics / portfolioPnl 缓存必须一并
      // 失效 —— 后端 `remove_from_watchlist` 已经级联删 Fund 和 FundNav,
      // 详情页留在 React Query 里的旧数据会显示"幽灵信息"。
      qc.invalidateQueries({ queryKey: ["fundSummary", code] });
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["fund", code] });
      qc.invalidateQueries({ queryKey: ["nav", code] });
      qc.invalidateQueries({ queryKey: ["navHistory", code] });
      qc.invalidateQueries({ queryKey: ["metrics", code] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", [code]] });
      qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
      toast.push(`已从自选池移除 ${code}`, "success");
    } catch (err) {
      toast.push(`移除失败：${String(err)}`, "error");
    }
  }

  const refreshDiagnosis = useMutation({
    mutationFn: () => api.refreshFundDiagnosis(code),
    onSuccess: (job) => {
      if (job.status === "done") {
        qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
        toast.push("体检数据已是最新", "success");
        return;
      }
      setRefreshJobId(job.job_id);
      toast.push("已开始刷新体检数据", "info");
    },
    onError: (err) => {
      toast.push(`体检刷新失败：${String(err)}`, "error");
    },
  });

  useEffect(() => {
    const job = refreshDiagnosisJob.data;
    if (!job) return;
    if (job.status === "done") {
      setRefreshJobId(null);
      qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
      toast.push(
        job.missing_data.length > 0
          ? `体检数据已刷新，仍缺失 ${job.missing_data.slice(0, 3).join(", ")}`
          : "体检数据已刷新",
        job.missing_data.length > 0 ? "info" : "success",
      );
    } else if (job.status === "failed" || job.status === "missing") {
      setRefreshJobId(null);
      toast.push(`体检刷新失败：${job.error ?? job.status}`, "error");
    }
  }, [code, qc, refreshDiagnosisJob.data, toast]);

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
            <Link href={`/compare?codes=${encodeURIComponent(code)}`}>
              <Button variant="outline">
                <GitCompareArrows className="mr-2 h-4 w-4" />
                对比
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
            {summary.isLoading ? (
              <StateBlock title="加载基金信息" tone="loading">正在读取本地基金基础资料。</StateBlock>
            ) : summary.error || errors.fund ? (
              <div className="space-y-3">
                <StateBlock title="本地暂无该基金数据" tone="error">
                  <span>
                    代码 {code} 不在本地库中{inWatchlist ? "(已在自选池)" : ""}。
                    点击下方按钮立即联网拉取基础信息与历史净值,完成后此页会自动刷新。
                  </span>
                </StateBlock>
                <Button
                  type="button"
                  disabled={refreshFund.isPending}
                  onClick={() => refreshFund.mutate()}
                >
                  <DownloadCloud className="mr-2 h-4 w-4" />
                  {refreshFund.isPending ? "拉取中..." : `立即拉取 ${code} 数据`}
                </Button>
              </div>
            ) : (
              <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
                <InfoItem label="基金类型">{fundData?.fund_type ?? "--"}</InfoItem>
                <InfoItem label="基金经理">{fundData?.manager ?? "--"}</InfoItem>
                <InfoItem label="管理人">{fundData?.company ?? "--"}</InfoItem>
                <InfoItem label="来源">
                  {fundData?.source ?? "--"} · {formatDate(fundData?.as_of)}
                </InfoItem>
              </dl>
            )}
          </CardContent>
        </Card>

        <Card className="p-6">
          <CardHeader>
            <div>
              <CardTitle className="text-base">最新净值</CardTitle>
              <p className="mt-1 text-xs text-gray-500">{formatDate(latestNav?.nav_date)}</p>
            </div>
          </CardHeader>
          <CardContent>
            {summary.isLoading ? (
              <StateBlock title="加载最新净值" tone="loading">正在读取最新净值。</StateBlock>
            ) : summary.error || errors.latest_nav ? (
              <StateBlock title="最新净值加载失败" tone="error">本地没有该基金最新净值。</StateBlock>
            ) : (
              <div className="space-y-4">
                <div className="text-4xl font-semibold tracking-tight text-gray-950">
                  {formatNav(latestNav?.accumulated_nav)}
                </div>
                <div className="flex items-center justify-between gap-3 rounded-lg bg-gray-50 p-3 text-xs">
                  <span className="text-gray-500">日涨跌</span>
                  <span className={trendBadgeClass(latestNav?.daily_return)}>
                    {formatPct(latestNav?.daily_return)}
                  </span>
                </div>
                <div className="rounded-lg bg-gray-50 p-3 text-xs leading-5 text-gray-500">
                  来源 {latestNav?.source ?? "--"} · 数据日期 {formatDate(latestNav?.nav_date)}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      <FundDiagnosisCard
        code={code}
        data={diagnosis.data}
        error={diagnosis.error}
        isLoading={diagnosis.isLoading}
        onRefresh={() => refreshDiagnosis.mutate()}
        refreshing={refreshDiagnosis.isPending || Boolean(refreshJobId)}
      />

      <HoldingCard
        fundCode={code}
        pnlError={summary.error}
        pnlItem={summaryData?.pnl_item}
        pnlLoading={summary.isLoading}
        pnlSkipped={summaryData?.pnl_skipped}
      />

      <section>
        <SectionHeader
          title="净值走势与区间涨跌"
          description="累计净值、日涨跌、收益、回撤和波动率均基于本地历史数据计算。"
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
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.7fr_1fr]">
          <NavChart
            code={code}
            navError={summary.error ?? errors.nav_history}
            navHistory={summaryData?.nav_history}
            navLoading={summary.isLoading}
            period={period}
          />
          <RecentDailyReturns
            endDate={dailyReturnRows[0]?.date ?? null}
            metrics={metricsData}
            metricsError={summary.error ?? errors.metrics}
            metricsLoading={summary.isLoading}
            periodLabel={PERIOD_LABELS[period]}
            periodStart={start}
            rows={dailyReturnRows}
          />
        </div>
      </section>

      <WatchlistDrawer
        onClose={() => setDrawerOpen(false)}
        onSaved={() => {
          qc.invalidateQueries({ queryKey: ["fundSummary", code] });
          qc.invalidateQueries({ queryKey: ["watchlist"] });
          qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
        }}
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

function RecentDailyReturns({
  rows,
  periodStart,
  endDate,
  metrics,
  metricsLoading,
  metricsError,
  periodLabel,
}: {
  rows: NavDailyReturnPoint[];
  periodStart: string;
  endDate: string | null;
  metrics: FundMetrics | null;
  metricsLoading: boolean;
  metricsError: unknown;
  periodLabel: string;
}) {
  const summary = summarizePeriodReturns(rows);

  const caption =
    endDate && periodStart
      ? `${formatDate(periodStart)} ~ ${formatDate(endDate)}`
      : endDate
        ? `截至 ${formatDate(endDate)}`
        : formatDate(periodStart);

  const streakLabel =
    summary.currentStreak &&
    `${summary.currentStreak.kind === "up" ? "连涨" : summary.currentStreak.kind === "down" ? "连跌" : "走平"}${summary.currentStreak.length}天`;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="flex shrink-0 items-center justify-between border-b border-gray-100 px-3 py-2 text-[11px]">
        <span className="font-medium text-gray-700">区间涨跌 · {periodLabel}</span>
        <span className="text-gray-500">{caption}</span>
      </div>

      <div className="border-b border-gray-100 p-3">
        <div className="mb-2 flex items-center justify-between text-[11px]">
          <span className="font-medium text-gray-700">阶段指标</span>
          <span className="text-gray-500">
            来源 {metrics?.source ?? "--"} · as_of {formatDate(metrics?.as_of)}
          </span>
        </div>
        {metricsLoading ? (
          <StateBlock title="计算阶段指标" tone="loading">正在读取并计算 {periodLabel} 指标。</StateBlock>
        ) : metricsError ? (
          <StateBlock title="阶段指标加载失败" tone="error">{String(metricsError)}</StateBlock>
        ) : (
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-gray-100">
            <KpiCell
              label={`${periodLabel}收益`}
              value={formatPct(metrics?.period_return)}
              valueColor={trendTextColor(metrics?.period_return)}
            />
            <KpiCell
              label="累计收益"
              value={formatPct(metrics?.cumulative_return)}
              valueColor={trendTextColor(metrics?.cumulative_return)}
            />
            <KpiCell
              label="最大回撤"
              value={formatPct(metrics?.max_drawdown)}
              valueColor={metrics?.max_drawdown === null || metrics?.max_drawdown === undefined ? "text-gray-600" : "text-green-600"}
            />
            <KpiCell
              label="波动率"
              value={formatVolatility(metrics?.volatility)}
            />
          </div>
        )}
      </div>

      <div className="grid shrink-0 grid-cols-2 gap-px border-b border-gray-100 bg-gray-100">
        <KpiCell
          label={streakLabel ?? "暂无连涨/跌"}
          value={streakLabel ? (summary.currentStreak!.kind === "up" ? "↑" : summary.currentStreak!.kind === "down" ? "↓" : "—") : ""}
          valueColor={summary.currentStreak?.kind === "up" ? "text-red-600" : summary.currentStreak?.kind === "down" ? "text-green-600" : "text-gray-400"}
        />
        <KpiCell
          label={summary.bestDay ? `${formatDate(summary.bestDay.date)}` : "最大单日涨幅"}
          value={formatPct(summary.bestDay?.dailyReturn)}
          valueColor="text-red-600"
        />
        <KpiCell
          label={summary.worstDay ? `${formatDate(summary.worstDay.date)}` : "最大单日跌幅"}
          value={formatPct(summary.worstDay?.dailyReturn)}
          valueColor="text-green-600"
        />
        <KpiCell
          label="累计净值涨跌"
          value={formatPct(summary.navChange)}
          valueColor={summary.navChange !== null && summary.navChange > 0 ? "text-red-600" : summary.navChange !== null && summary.navChange < 0 ? "text-green-600" : "text-gray-600"}
        />
      </div>

      <div className="max-h-[300px] flex-1 overflow-y-auto">
        <div className="grid grid-cols-[1fr_auto] gap-x-2 border-b border-gray-100 bg-white px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide text-gray-400 sticky top-0">
          <span>日期</span>
          <span className="text-right">日涨跌</span>
        </div>
        {rows.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-gray-500">
            本地区间内暂无日涨跌数据。
          </div>
        ) : (
          rows.map((row) => (
            <div
              className="grid grid-cols-[1fr_auto] items-center gap-x-2 border-b border-gray-50 px-3 py-1.5 text-[11px]"
              key={row.date}
            >
              <span className="text-gray-500">{formatDate(row.date)}</span>
              <span className={`${trendBadgeClass(row.dailyReturn)} whitespace-nowrap`}>
                {formatPct(row.dailyReturn)}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function KpiCell({
  label,
  value,
  valueColor = "text-gray-900",
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="flex items-center justify-between bg-white px-3 py-2">
      <span className="text-[10px] text-gray-500">{label}</span>
      <span className={`text-xs font-semibold tabular-nums ${valueColor}`}>{value}</span>
    </div>
  );
}

function formatVolatility(value: number | null | undefined) {
  if (value === null || value === undefined) return "--";
  return `${(value * 100).toFixed(2)}%`;
}

function trendTextColor(value: number | null | undefined) {
  if (value === null || value === undefined) return "text-gray-600";
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-green-600";
  return "text-gray-600";
}

function trendBadgeClass(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "rounded-full bg-gray-100 px-2 py-1 font-medium text-gray-600";
  }
  if (value > 0) {
    return "rounded-full bg-red-50 px-2 py-1 font-medium text-red-600";
  }
  if (value < 0) {
    return "rounded-full bg-green-50 px-2 py-1 font-medium text-green-600";
  }
  return "rounded-full bg-gray-100 px-2 py-1 font-medium text-gray-600";
}
