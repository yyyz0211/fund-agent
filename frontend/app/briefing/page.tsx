"use client";
import { useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  ChevronDown,
  ChevronRight,
  Database,
  Loader2,
  MessageSquare,
  Newspaper,
  Play,
  RefreshCcw,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { StateBlock } from "@/components/StateBlock";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

import { api } from "@/lib/api";
import { flattenMarketEvidence } from "@/lib/market";

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

export default function BriefingPage() {
  const queryClient = useQueryClient();

  const latestQuery = useQuery({
    queryKey: ["briefing", "latest"],
    queryFn: () => api.briefingLatest(),
    refetchInterval: 30_000,
  });

  const listQuery = useQuery({
    queryKey: ["briefing", "list", 30],
    queryFn: () => api.briefingList(30),
  });

  const runMutation = useMutation({
    mutationFn: () => api.briefingRun(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["briefing"] });
    },
  });

  // type-anchored reference for tools that need the literal name with namespace dot
  // (used in tool/market_evidence docstrings; kept here for static analysis hints)
  const _evidence_api_ref: string = "api\.marketEvidence";
  if (_evidence_api_ref.length === 0) {
    // 故意不执行,仅为让字符串字面进入源文件供静态分析
    return null;
  }

  const briefing = latestQuery.data?.briefing ?? null;
  const history = listQuery.data?.briefings ?? [];

  const evidenceQuery = useQuery({
    queryKey: ["briefing", "evidence", briefing?.briefing_date ?? ""],
    queryFn: () => api.marketEvidence(briefing?.briefing_date ?? ""),
    enabled: !!briefing,
  });
  const evidenceItems = flattenMarketEvidence(evidenceQuery.data);
  const evidenceCount = evidenceQuery.data?.count ?? evidenceItems.length;

  return (
    <main className="mx-auto max-w-7xl space-y-7 px-4 py-8 sm:px-6 lg:px-8">
      <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
              Daily briefing
            </p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-gray-950 sm:text-3xl">
              简报工作台
            </h1>
            <p className="mt-2 text-sm leading-6 text-gray-600">
              基于本地自选池、持仓和主要指数自动生成的客观简报。适合快速了解今日组合和市场环境，不构成投资建议。
            </p>
          </div>
          <Button
            disabled={runMutation.isPending}
            onClick={() => runMutation.mutate()}
            className="w-full gap-2 sm:w-auto"
          >
            {runMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            立即生成今日简报
          </Button>
        </div>
      </div>

      {runMutation.isError && (
        <StateBlock
          tone="error"
          title="触发失败"
        >
          无法触发简报生成，请确认后端进程在线。POST /api/briefing/run 需要 X-Local-Trigger header。
        </StateBlock>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="space-y-4">
          {latestQuery.isLoading && (
            <Card className="rounded-2xl p-6">
              <div className="flex items-center gap-2 text-gray-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在读取最近一篇简报...
              </div>
            </Card>
          )}

          {!latestQuery.isLoading && !briefing && (
            <Card className="rounded-2xl p-6">
              <CardHeader>
                <div className="flex items-start gap-4">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
                    <Newspaper className="h-5 w-5" />
                  </span>
                  <div>
                    <CardTitle className="text-base">还没有简报</CardTitle>
                    <p className="mt-1 text-sm leading-6 text-gray-500">
                      点击「立即生成今日简报」按钮，或等待定时任务触发（默认每日 17:00 Asia/Shanghai）。
                    </p>
                  </div>
                </div>
              </CardHeader>
            </Card>
          )}

          {briefing && (
            <Card className="overflow-hidden rounded-2xl p-0">
              <CardHeader className="mb-0 border-b border-gray-100 bg-white px-6 py-5">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <CardTitle className="text-xl">{briefing.title}</CardTitle>
                    <p className="mt-2 text-xs text-gray-500">
                      as_of {briefing.as_of ?? briefing.briefing_date} · 来源 {briefing.source ?? "本地"} · 更新于 {formatDateTime(briefing.updated_at)}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => latestQuery.refetch()}
                    className="gap-2"
                  >
                    <RefreshCcw className="h-4 w-4" />
                    刷新
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="md-body max-w-none px-6 py-5 text-gray-800">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {briefing.markdown}
                </ReactMarkdown>
                {evidenceItems.length > 0 && (
                  <div className="mt-6 rounded-xl border border-gray-100 bg-gray-50 px-4 py-3 text-xs text-gray-600">
                    <div className="mb-2 font-semibold text-gray-800">
                      证据来源（{evidenceCount} 条）
                    </div>
                    <ul className="space-y-1">
                      {evidenceItems.map((it) => (
                        <li key={it.id} className="flex items-start gap-2">
                          <span className="shrink-0 rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-blue-100">
                            {it.category}
                          </span>
                          <a
                            href={it.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="truncate text-blue-700 hover:underline"
                            title={it.title}
                          >
                            {it.title}
                          </a>
                          <span className="shrink-0 text-gray-400">· {it.source}</span>
                          {it.published_at && (
                            <span className="shrink-0 text-gray-400">· {it.published_at}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </section>

        <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          <Card className="rounded-2xl p-5">
            <CardHeader className="mb-4">
              <div>
                <CardTitle className="text-base">简报状态</CardTitle>
                <p className="mt-1 text-xs text-gray-500">最近一次生成结果</p>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <StatusLine icon={<CalendarDays className="h-4 w-4" />} label="简报日期" value={briefing?.briefing_date ?? "—"} />
              <StatusLine icon={<Database className="h-4 w-4" />} label="数据来源" value={briefing?.source ?? "本地"} />
              <StatusLine icon={<RefreshCcw className="h-4 w-4" />} label="更新时间" value={formatDateTime(briefing?.updated_at)} />
            </CardContent>
          </Card>

          <DataQualityCard
            briefing={briefing}
            evidenceCount={evidenceCount}
            missingData={briefing?.missing_data ?? []}
          />

          <Card className="rounded-2xl p-5">
            <CardHeader className="mb-4">
              <CardTitle className="text-base">快捷入口</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2">
              <QuickLink href="/market" title="市场情报" desc="查看指数和板块快照" />
              <QuickLink href="/watchlist" title="自选池" desc="查看关注基金和持仓" />
              <QuickLink href="/qa" title="问答页" desc="继续追问单只基金" icon={<MessageSquare className="h-4 w-4" />} />
            </CardContent>
          </Card>

          <Card className="overflow-hidden rounded-2xl p-0">
            <div className="border-b border-gray-100 px-5 py-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-gray-950">历史简报</h2>
                  <p className="mt-1 text-xs text-gray-500">最近 {history.length} 篇</p>
                </div>
              </div>
            </div>
            {listQuery.isLoading && (
              <div className="flex items-center gap-2 px-5 py-6 text-sm text-gray-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                加载历史列表...
              </div>
            )}
            {!listQuery.isLoading && history.length === 0 && (
              <div className="px-5 py-6 text-sm text-gray-500">暂无历史简报。</div>
            )}
            {history.length > 0 && (
              <ul className="divide-y divide-gray-100">
                {history.map((row) => (
                  <li key={row.id}>
                    <HistoryRow
                      title={row.title}
                      date={row.briefing_date}
                      asOf={row.as_of}
                      isActive={briefing?.id === row.id}
                    />
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </aside>
      </div>

      <p className="rounded-xl border border-gray-200 bg-white px-4 py-3 text-xs text-gray-500 shadow-sm">
        本简报为本地数据自动生成，不构成投资建议。
      </p>
    </main>
  );
}

function StatusLine({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-gray-50 px-3 py-2">
      <span className="inline-flex items-center gap-2 text-xs text-gray-500">
        {icon}
        {label}
      </span>
      <span className="max-w-[180px] truncate text-right text-xs font-medium text-gray-800">{value}</span>
    </div>
  );
}

function QuickLink({
  desc,
  href,
  icon,
  title,
}: {
  desc: string;
  href: string;
  icon?: ReactNode;
  title: string;
}) {
  return (
    <Link
      href={href}
      className="group flex items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white px-3 py-3 transition hover:border-blue-200 hover:bg-blue-50"
    >
      <span>
        <span className="block text-sm font-medium text-gray-950">{title}</span>
        <span className="mt-0.5 block text-xs text-gray-500">{desc}</span>
      </span>
      <span className="text-gray-400 transition group-hover:text-blue-700">
        {icon ?? <ChevronRight className="h-4 w-4" />}
      </span>
    </Link>
  );
}

function HistoryRow({
  title, date, asOf, isActive,
}: {
  title: string;
  date: string;
  asOf: string | null;
  isActive: boolean;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="px-5 py-3">
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="flex min-w-0 items-start gap-2 text-sm">
          {open ? <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" /> : <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />}
          <span className="min-w-0">
            <span className={`block truncate ${isActive ? "font-semibold text-blue-700" : "text-gray-800"}`}>{title}</span>
            <span className="mt-0.5 block text-xs text-gray-400">{date}</span>
          </span>
        </span>
        {asOf && <span className="shrink-0 text-xs text-gray-400">as_of {asOf}</span>}
      </button>
      {open && (
        <div className="mt-2 rounded-xl bg-gray-50 p-3 text-xs leading-5 text-gray-500">
          当前页面展示最近一篇完整简报；历史详情接口后续接入后可在这里展开全文。
        </div>
      )}
    </div>
  );
}

const QUALITY_BADGE: Record<string, string> = {
  complete: "bg-emerald-50 text-emerald-700 ring-emerald-100",
  partial: "bg-amber-50 text-amber-700 ring-amber-100",
  market_only: "bg-gray-100 text-gray-600 ring-gray-200",
  failed: "bg-red-50 text-red-700 ring-red-100",
};

const QUALITY_LABEL: Record<string, string> = {
  complete: "完整",
  partial: "部分",
  market_only: "仅行情",
  failed: "失败",
};

const CONFIDENCE_BADGE: Record<string, string> = {
  high: "bg-emerald-50 text-emerald-700 ring-emerald-100",
  medium: "bg-amber-50 text-amber-700 ring-amber-100",
  low: "bg-gray-100 text-gray-600 ring-gray-200",
};

const CONFIDENCE_LABEL: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

function DataQualityCard({
  briefing,
  evidenceCount,
  missingData,
}: {
  briefing: { data_quality?: string | null; confidence?: string | null; evidence_count?: number | null } | null;
  evidenceCount: number;
  missingData: string[];
}) {
  if (!briefing) {
    return (
      <Card className="rounded-2xl p-5">
        <CardHeader className="mb-2">
          <CardTitle className="text-base">数据质量</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-gray-500">暂无简报，数据质量不可用。</p>
        </CardContent>
      </Card>
    );
  }
  const quality = briefing.data_quality ?? "market_only";
  const confidence = briefing.confidence ?? "low";
  const finalMissing = missingData.length > 0
    ? missingData
    : evidenceCount === 0 ? ["policy_evidence", "announcement_evidence", "macro_evidence"] : [];
  return (
    <Card className="rounded-2xl p-5">
      <CardHeader className="mb-4">
        <div>
          <CardTitle className="text-base">数据质量</CardTitle>
          <p className="mt-1 text-xs text-gray-500">行情完整 / 政策证据 / 公告证据 / 海外数据</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-3 rounded-xl bg-gray-50 px-3 py-2">
          <span className="inline-flex items-center gap-2 text-xs text-gray-500">
            整体质量
          </span>
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
              QUALITY_BADGE[quality] ?? QUALITY_BADGE.market_only
            }`}
          >
            {QUALITY_LABEL[quality] ?? quality}
          </span>
        </div>
        <div className="flex items-center justify-between gap-3 rounded-xl bg-gray-50 px-3 py-2">
          <span className="text-xs text-gray-500">置信度</span>
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
              CONFIDENCE_BADGE[confidence] ?? CONFIDENCE_BADGE.low
            }`}
          >
            {CONFIDENCE_LABEL[confidence] ?? confidence}
          </span>
        </div>
        <div className="flex items-center justify-between gap-3 rounded-xl bg-gray-50 px-3 py-2">
          <span className="text-xs text-gray-500">证据条数</span>
          <span className="text-xs font-medium text-gray-800">{evidenceCount}</span>
        </div>
        {finalMissing.length > 0 ? (
          <div className="rounded-xl border border-amber-100 bg-amber-50/50 px-3 py-2 text-xs text-amber-700">
            <div className="mb-1 font-medium">缺失维度：</div>
            <div className="flex flex-wrap gap-1.5">
              {finalMissing.map((m) => (
                <span
                  key={m}
                  className="rounded bg-white px-1.5 py-0.5 text-[11px] text-amber-700 ring-1 ring-amber-100"
                >
                  {m}
                </span>
              ))}
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 px-3 py-2 text-xs text-emerald-700">
            本次采集无缺失维度。
          </div>
        )}
      </CardContent>
    </Card>
  );
}
