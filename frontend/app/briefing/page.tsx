"use client";
import { useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  Database,
  Eye,
  EyeOff,
  Loader2,
  MessageSquare,
  Newspaper,
  Play,
  RefreshCcw,
  ShieldAlert,
  ThumbsUp,
  TrendingUp,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { StateBlock } from "@/components/StateBlock";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

import { api } from "@/lib/api";
import { flattenMarketEvidence } from "@/lib/market";
import type {
  Briefing,
  BriefingSection,
  DataStatementSection,
  EvidenceItem,
  RiskItem,
  ThemeItem,
  BriefingModule,
} from "@/types/api";

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

  const briefing = latestQuery.data?.briefing ?? null;
  const history = listQuery.data?.briefings ?? [];

  const evidenceQuery = useQuery({
    queryKey: ["briefing", "evidence", briefing?.briefing_date ?? ""],
    queryFn: () => api.marketEvidence(briefing?.briefing_date ?? ""),
    enabled: !!briefing,
  });
  const evidenceItems = flattenMarketEvidence(evidenceQuery.data);
  const evidenceCount = evidenceQuery.data?.count ?? evidenceItems.length;

  // V2: check if sections has module_order
  const sections = briefing?.sections;
  const isV2 = sections !== undefined &&
    typeof sections === "object" &&
    sections !== null &&
    "module_order" in sections;

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
                {/* V2: Render modules by module_order */}
                {isV2 && sections && "module_order" in sections && Array.isArray(sections.module_order) ? (
                  <V2ModuleRenderer
                    sections={sections as BriefingSection}
                    evidenceItems={evidenceItems}
                    evidenceCount={evidenceCount}
                  />
                ) : (
                  <>
                    {/* Legacy: just show markdown */}
                    {isV2Briefing(briefing.sections) && (
                      <QuickSummaryCard sections={briefing.sections} />
                    )}
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {briefing.markdown}
                    </ReactMarkdown>
                    {isV2Briefing(briefing.sections) && (
                      <RiskRadarCard sections={briefing.sections} />
                    )}
                    {evidenceItems.length > 0 && (
                      <EvidenceCard items={evidenceItems} />
                    )}
                  </>
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

          {briefing && <FeedbackPanel briefingId={briefing.id} />}

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
  briefing: {
    data_quality?: string | null;
    confidence?: string | null;
    evidence_count?: number | null;
    failed_modules?: Array<{ module: string; fund_code?: string; reason: string }>;
    data_sources_last_updated?: Record<string, string>;
  } | null;
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
        {/* V2: Failed modules */}
        {briefing?.failed_modules && briefing.failed_modules.length > 0 && (
          <div className="rounded-xl border border-red-100 bg-red-50/50 px-3 py-2 text-xs text-red-700">
            <div className="mb-1 font-medium">失败模块：</div>
            <div className="flex flex-col gap-1">
              {briefing.failed_modules.map((f, i) => (
                <span key={i}>
                  {f.module}{f.fund_code ? ` (${f.fund_code})` : ""}：{f.reason}
                </span>
              ))}
            </div>
          </div>
        )}
        {/* V2: Data sources freshness */}
        {briefing?.data_sources_last_updated && Object.keys(briefing.data_sources_last_updated ?? {}).length > 0 && (
          <div className="rounded-xl border border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-500">
            <div className="mb-1 font-medium text-gray-700">数据源最后更新：</div>
            {Object.entries(briefing.data_sources_last_updated ?? {}).map(([source, time]) => (
              <div key={source} className="flex justify-between gap-2">
                <span>{source}</span>
                <span className="text-gray-400">{time ? formatDateTime(time) : "—"}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// V2 helper: type guard
// ---------------------------------------------------------------------------

function isV2Briefing(sections: BriefingSection | Record<string, unknown>): sections is BriefingSection {
  return typeof sections === "object" && sections !== null && "quick_summary" in sections;
}

// ---------------------------------------------------------------------------
// V2: Quick Summary card (market state + themes + risks badges)
// ---------------------------------------------------------------------------

const MARKET_STATE_COLORS: Record<string, string> = {
  "偏强": "bg-emerald-50 text-emerald-700 ring-emerald-200",
  "偏弱": "bg-red-50 text-red-700 ring-red-200",
  "分化": "bg-amber-50 text-amber-700 ring-amber-200",
  "退潮": "bg-red-50 text-red-700 ring-red-200",
  "数据不足": "bg-gray-100 text-gray-600 ring-gray-200",
};

const WATCHLIST_IMPACT_COLORS: Record<string, string> = {
  positive: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  negative: "bg-red-50 text-red-700 ring-red-200",
  neutral: "bg-gray-100 text-gray-600 ring-gray-200",
  mixed: "bg-amber-50 text-amber-700 ring-amber-200",
  empty: "bg-gray-100 text-gray-600 ring-gray-200",
};

const WATCHLIST_IMPACT_LABELS: Record<string, string> = {
  positive: "自选正向",
  negative: "自选负向",
  neutral: "自选中性",
  mixed: "自选分化",
  empty: "自选池空",
};

function QuickSummaryCard({ sections }: { sections: BriefingSection }) {
  const qs = sections.quick_summary;
  if (!qs) return null;

  const marketStateColor = MARKET_STATE_COLORS[qs.market_state ?? ""] ?? "bg-gray-100 text-gray-600 ring-gray-200";
  const impactColor = WATCHLIST_IMPACT_COLORS[qs.watchlist_impact ?? ""] ?? "bg-gray-100 text-gray-600 ring-gray-200";
  const impactLabel = WATCHLIST_IMPACT_LABELS[qs.watchlist_impact ?? ""] ?? qs.watchlist_impact ?? "";

  return (
    <div className="mb-6 rounded-xl border border-gray-100 bg-gray-50/50 p-4">
      {/* Row 1: market state + confidence */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-gray-500">市场状态</span>
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${marketStateColor}`}>
          {qs.market_state ?? "未知"}
        </span>
        {qs.confidence && (
          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${CONFIDENCE_BADGE[qs.confidence] ?? "bg-gray-100 text-gray-600 ring-gray-200"}`}>
            置信度: {CONFIDENCE_LABEL[qs.confidence] ?? qs.confidence}
          </span>
        )}
      </div>

      {/* Row 2: main themes */}
      {qs.main_themes && qs.main_themes.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1 text-xs font-medium text-gray-500">
            <TrendingUp className="h-3.5 w-3.5" />
            主线
          </span>
          {qs.main_themes.map((t) => (
            <span key={t} className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-blue-100">
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Row 3: top risks */}
      {qs.top_risks && qs.top_risks.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1 text-xs font-medium text-gray-500">
            <AlertTriangle className="h-3.5 w-3.5" />
            主要风险
          </span>
          {qs.top_risks.map((r) => (
            <span key={r} className="inline-flex items-center rounded-full bg-orange-50 px-2.5 py-0.5 text-xs font-medium text-orange-700 ring-1 ring-orange-100">
              {r}
            </span>
          ))}
        </div>
      )}

      {/* Row 4: watchlist impact */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-gray-500">自选池影响</span>
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${impactColor}`}>
          {impactLabel}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// V2: Risk Radar card
// ---------------------------------------------------------------------------

const RISK_LEVEL_COLORS: Record<string, string> = {
  high: "border-red-300 bg-red-50/50",
  medium: "border-amber-300 bg-amber-50/50",
  low: "border-gray-200 bg-gray-50",
};

const RISK_LEVEL_LABEL_COLORS: Record<string, string> = {
  high: "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-gray-100 text-gray-600",
};

function RiskRadarCard({ sections }: { sections: BriefingSection }) {
  const rr = sections.risk_radar;
  if (!rr || (!rr.market?.length && !rr.sector?.length && !rr.watchlist?.length && !rr.data?.length)) {
    return null;
  }

  const allRisks: Array<{ category: string; item: RiskItem }> = [
    ...(rr.market ?? []).map((item) => ({ category: "市场", item })),
    ...(rr.sector ?? []).map((item) => ({ category: "板块", item })),
    ...(rr.watchlist ?? []).map((item) => ({ category: "自选池", item })),
    ...(rr.data ?? []).map((item) => ({ category: "数据", item })),
  ];

  if (allRisks.length === 0) return null;

  return (
    <div className="mt-6 rounded-xl border border-gray-100 bg-gray-50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-orange-600" />
        <span className="font-semibold text-gray-800">风险雷达</span>
      </div>
      <div className="flex flex-col gap-2">
        {allRisks.map(({ category, item }, idx) => (
          <div
            key={idx}
            className={`flex items-start gap-2 rounded-lg border p-2.5 text-xs ${RISK_LEVEL_COLORS[item.level] ?? "border-gray-200 bg-gray-50"}`}
          >
            <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${RISK_LEVEL_LABEL_COLORS[item.level] ?? "bg-gray-100 text-gray-600"}`}>
              {item.level.toUpperCase()}
            </span>
            <span className="shrink-0 rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-gray-500 ring-1 ring-gray-100">
              {category}
            </span>
            <div className="min-w-0">
              <span className="font-medium text-gray-800">{item.signal}</span>
              {item.detail && <span className="ml-1 text-gray-500">{item.detail}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// V2: Evidence card with freshness/weight badges
// ---------------------------------------------------------------------------

const FRESHNESS_COLORS: Record<string, string> = {
  realtime: "bg-purple-50 text-purple-700 ring-purple-100",
  today: "bg-blue-50 text-blue-700 ring-blue-100",
  recent: "bg-amber-50 text-amber-700 ring-amber-100",
  older: "bg-gray-100 text-gray-500 ring-gray-200",
};

const FRESHNESS_LABELS: Record<string, string> = {
  realtime: "实时",
  today: "当日",
  recent: "近3日",
  older: "较早",
};

const WEIGHT_COLORS: Record<string, string> = {
  high: "bg-emerald-50 text-emerald-700 ring-emerald-100",
  medium: "bg-amber-50 text-amber-700 ring-amber-100",
  low: "bg-gray-100 text-gray-500 ring-gray-200",
};

const WEIGHT_LABELS: Record<string, string> = {
  high: "高权重",
  medium: "中权重",
  low: "低权重",
};

const CATEGORY_LABELS: Record<string, string> = {
  policy: "政策",
  announcement: "公告",
  macro: "宏观",
  news: "资讯",
};

function EvidenceCard({ items }: { items: EvidenceItem[] }) {
  if (!items || items.length === 0) return null;

  return (
    <div className="mt-6 rounded-xl border border-gray-100 bg-gray-50 px-4 py-3 text-xs text-gray-600">
      <div className="mb-2 flex items-center gap-2 font-semibold text-gray-800">
        <Newspaper className="h-4 w-4" />
        关键证据（{items.length} 条）
      </div>
      <ul className="flex flex-col gap-2">
        {items.map((it, idx) => (
          <li key={it.evidence_id ?? idx} className="flex flex-wrap items-start gap-2 rounded-lg bg-white p-2">
            <span className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-blue-100">
              {CATEGORY_LABELS[it.category] ?? it.category}
            </span>
            {it.freshness && (
              <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${FRESHNESS_COLORS[it.freshness] ?? "bg-gray-100 text-gray-500 ring-gray-200"}`}>
                {FRESHNESS_LABELS[it.freshness] ?? it.freshness}
              </span>
            )}
            {it.weight && (
              <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${WEIGHT_COLORS[it.weight] ?? "bg-gray-100 text-gray-500 ring-gray-200"}`}>
                {WEIGHT_LABELS[it.weight] ?? it.weight}
              </span>
            )}
            <a
              href={it.source_url || "#"}
              target="_blank"
              rel="noreferrer"
              className="min-w-0 flex-1 truncate text-blue-700 hover:underline"
              title={it.title}
            >
              {it.title}
            </a>
            <span className="shrink-0 text-gray-400">{it.source}</span>
            {it.published_at && (
              <span className="shrink-0 text-gray-400">{formatDateTime(it.published_at)}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// V2 Module Renderer (按 module_order + status 渲染)
// ---------------------------------------------------------------------------

const STATUS_ICON_COLOR: Record<string, string> = {
  ready: "text-emerald-600",
  partial: "text-amber-600",
  missing: "text-gray-400",
  failed: "text-red-600",
};

const MODULE_TITLES: Record<string, string> = {
  quick_summary: "30 秒摘要",
  market_state: "市场状态",
  themes_and_flows: "主线与资金",
  watchlist_impact: "自选池影响",
  risk_radar: "风险雷达",
  key_evidence: "关键证据",
  data_statement: "数据质量",
  overnight: "隔夜外围",
  intraday_anomaly: "盘中异动",
  events: "事件日历",
};

function V2ModuleRenderer({
  sections,
  evidenceItems,
  evidenceCount,
}: {
  sections: BriefingSection;
  evidenceItems: EvidenceItem[];
  evidenceCount: number;
}) {
  const modules = sections.modules;
  const moduleOrder: string[] = sections.module_order ?? [];

  if (!modules || moduleOrder.length === 0) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {(sections as unknown as { markdown?: string }).markdown ?? ""}
      </ReactMarkdown>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {moduleOrder.map((key) => {
        const mod = modules[key] as BriefingModule | undefined;
        if (!mod) return null;
        return (
          <ModuleCard
            key={key}
            moduleKey={key}
            mod={mod}
            evidenceItems={evidenceItems}
            evidenceCount={evidenceCount}
          />
        );
      })}
    </div>
  );
}

function ModuleCard({
  moduleKey,
  mod,
  evidenceItems,
  evidenceCount,
}: {
  moduleKey: string;
  mod: BriefingModule;
  evidenceItems: EvidenceItem[];
  evidenceCount: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const title = MODULE_TITLES[moduleKey] ?? mod.title ?? moduleKey;
  const statusColor = STATUS_ICON_COLOR[mod.status] ?? "text-gray-400";

  return (
    <div className={`rounded-xl border ${
      mod.status === "failed" ? "border-red-200 bg-red-50/30" :
      mod.status === "partial" ? "border-amber-200 bg-amber-50/30" :
      "border-gray-100 bg-gray-50/50"
    } p-4`}>
      {/* Module header */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {mod.status === "ready" && <span className={`h-2 w-2 rounded-full bg-emerald-500 ${statusColor}`} />}
          {mod.status === "partial" && <span className={`h-2 w-2 rounded-full bg-amber-500 ${statusColor}`} />}
          {mod.status === "missing" && <Eye className="h-3.5 w-3.5 text-gray-400" />}
          {mod.status === "failed" && <ShieldAlert className={`h-3.5 w-3.5 ${statusColor}`} />}
          <span className="text-sm font-semibold text-gray-800">{title}</span>
          {mod.status !== "ready" && (
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${
              mod.status === "partial" ? "bg-amber-50 text-amber-700 ring-amber-200" :
              mod.status === "missing" ? "bg-gray-100 text-gray-500 ring-gray-200" :
              "bg-red-50 text-red-700 ring-red-200"
            }`}>
              {mod.status === "partial" ? "部分" : mod.status === "missing" ? "缺失" : "失败"}
            </span>
          )}
        </div>
        {mod.warnings && mod.warnings.length > 0 && (
          <button
            onClick={() => setExpanded((e) => !e)}
            className="flex items-center gap-1 text-xs text-amber-600 hover:text-amber-800"
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            {expanded ? <EyeOff className="h-3.5 w-3.5" /> : <span>警告</span>}
          </button>
        )}
      </div>

      {/* Warnings */}
      {expanded && mod.warnings && mod.warnings.length > 0 && (
        <div className="mb-2 rounded-lg border border-amber-100 bg-amber-50 p-2 text-xs text-amber-700">
          {mod.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
        </div>
      )}

      {/* Module-specific content */}
      {moduleKey === "quick_summary" && <QuickSummaryContent mod={mod} />}
      {moduleKey === "market_state" && <MarketStateContent mod={mod} />}
      {moduleKey === "themes_and_flows" && <ThemesAndFlowsContent mod={mod} />}
      {moduleKey === "watchlist_impact" && <WatchlistImpactContent mod={mod} />}
      {moduleKey === "risk_radar" && <RiskRadarContent mod={mod} />}
      {moduleKey === "key_evidence" && <KeyEvidenceContent mod={mod} evidenceItems={evidenceItems} />}
      {moduleKey === "data_statement" && <DataStatementContent mod={mod} evidenceCount={evidenceCount} />}
    </div>
  );
}

function QuickSummaryContent({ mod }: { mod: BriefingModule }) {
  const c = mod.content;
  if (!c) return <p className="text-sm text-gray-500">{mod.summary ?? ""}</p>;
  const marketState = (c.market_state as string | undefined) ?? "";
  const themes = (c.main_themes as string[] | undefined) ?? [];
  const risks = (c.top_risks as string[] | undefined) ?? [];
  const impact = (c.watchlist_impact as string | undefined) ?? "";
  const confidence = (c.confidence as string | undefined) ?? "low";
  const stateColor = MARKET_STATE_COLORS[marketState] ?? "bg-gray-100 text-gray-600 ring-gray-200";
  const impactColor = WATCHLIST_IMPACT_COLORS[impact] ?? "bg-gray-100 text-gray-600 ring-gray-200";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-gray-500">市场状态</span>
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${stateColor}`}>
          {marketState || "未知"}
        </span>
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${CONFIDENCE_BADGE[confidence] ?? "bg-gray-100 text-gray-600 ring-gray-200"}`}>
          置信度: {CONFIDENCE_LABEL[confidence] ?? confidence}
        </span>
      </div>
      {themes.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1 text-xs font-medium text-gray-500">
            <TrendingUp className="h-3.5 w-3.5" />主线
          </span>
          {themes.map((t) => (
            <span key={t} className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-blue-100">{t}</span>
          ))}
        </div>
      )}
      {risks.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1 text-xs font-medium text-gray-500">
            <AlertTriangle className="h-3.5 w-3.5" />主要风险
          </span>
          {risks.map((r) => (
            <span key={r} className="inline-flex items-center rounded-full bg-orange-50 px-2.5 py-0.5 text-xs font-medium text-orange-700 ring-1 ring-orange-100">{r}</span>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-gray-500">自选池影响</span>
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${impactColor}`}>
          {(WATCHLIST_IMPACT_LABELS[impact] ?? impact) || "未知"}
        </span>
      </div>
    </div>
  );
}

function MarketStateContent({ mod }: { mod: BriefingModule }) {
  const c = mod.content;
  if (!c) return <p className="text-sm text-gray-500">{mod.summary ?? ""}</p>;
  const label = c.label as string | undefined;
  const reasons = c.reasons as string[] | undefined;
  const stateColor = MARKET_STATE_COLORS[label ?? ""] ?? "bg-gray-100 text-gray-600 ring-gray-200";
  return (
    <div className="space-y-2 text-sm">
      {mod.summary && <p className="text-gray-700">{mod.summary}</p>}
      {label && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">状态</span>
          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${stateColor}`}>
            {label}
          </span>
        </div>
      )}
      {reasons && reasons.length > 0 && (
        <ul className="ml-4 list-disc space-y-1 text-xs text-gray-600">
          {reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
    </div>
  );
}

function ThemesAndFlowsContent({ mod }: { mod: BriefingModule }) {
  const c = mod.content;
  if (!c) return <p className="text-sm text-gray-500">{mod.summary ?? ""}</p>;
  const leading = (c.leading_themes ?? c.items ?? []) as ThemeItem[];
  const lagging = (c.lagging_themes ?? []) as ThemeItem[];
  return (
    <div className="space-y-2 text-sm">
      {mod.summary && <p className="text-gray-700">{mod.summary}</p>}
      {leading.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-xs font-medium text-gray-500">强势</span>
          {leading.slice(0, 5).map((t, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-emerald-100">
              {t.name}
              {t.change_pct !== undefined && <span className="text-emerald-500">{(t.change_pct >= 0 ? "+" : "") + t.change_pct.toFixed(1)}%</span>}
              {t.trend && (
                <span className="text-[10px] text-emerald-400">[{t.trend}]</span>
              )}
            </span>
          ))}
        </div>
      )}
      {lagging.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-xs font-medium text-gray-500">弱势</span>
          {lagging.slice(0, 3).map((t, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700 ring-1 ring-red-100">
              {t.name}
              {t.change_pct !== undefined && <span className="text-red-400">{(t.change_pct >= 0 ? "+" : "") + t.change_pct.toFixed(1)}%</span>}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function WatchlistImpactContent({ mod }: { mod: BriefingModule }) {
  const c = mod.content;
  if (!c) return <p className="text-sm text-gray-500">{mod.summary ?? ""}</p>;
  const overall = c.overall as string | undefined;
  const positive = (c.positive ?? []) as Array<{ fund_code: string; fund_name: string; reason: string }>;
  const negative = (c.negative ?? []) as Array<{ fund_code: string; fund_name: string; reason: string }>;
  const neutral = (c.neutral ?? []) as Array<{ fund_code: string; fund_name: string }>;
  const impactColor = WATCHLIST_IMPACT_COLORS[overall ?? ""] ?? "bg-gray-100 text-gray-600 ring-gray-200";
  return (
    <div className="space-y-2 text-sm">
      {mod.summary && <p className="text-gray-700">{mod.summary}</p>}
      {overall && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">整体影响</span>
          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${impactColor}`}>
            {WATCHLIST_IMPACT_LABELS[overall] ?? overall}
          </span>
        </div>
      )}
      {positive.length > 0 && (
        <div className="space-y-1">
          <span className="text-xs font-medium text-emerald-600">正向 ({positive.length})</span>
          {positive.slice(0, 3).map((p, i) => (
            <div key={i} className="ml-2 text-xs text-gray-600">
              {p.fund_name ?? p.fund_code}：{p.reason}
            </div>
          ))}
        </div>
      )}
      {negative.length > 0 && (
        <div className="space-y-1">
          <span className="text-xs font-medium text-red-600">负向 ({negative.length})</span>
          {negative.slice(0, 3).map((p, i) => (
            <div key={i} className="ml-2 text-xs text-gray-600">
              {p.fund_name ?? p.fund_code}：{p.reason}
            </div>
          ))}
        </div>
      )}
      {neutral.length > 0 && (
        <div className="text-xs text-gray-400">中性 {neutral.length} 只，无明确主题关联</div>
      )}
    </div>
  );
}

function RiskRadarContent({ mod }: { mod: BriefingModule }) {
  const c = mod.content;
  if (!c) return <p className="text-sm text-gray-500">{mod.summary ?? ""}</p>;
  const market = (c.market ?? []) as RiskItem[];
  const sector = (c.sector ?? []) as RiskItem[];
  const watchlist = (c.watchlist ?? []) as RiskItem[];
  const data = (c.data ?? []) as RiskItem[];
  const allRisks = [
    ...market.map((r) => ({ ...r, cat: "市场" })),
    ...sector.map((r) => ({ ...r, cat: "板块" })),
    ...watchlist.map((r) => ({ ...r, cat: "自选池" })),
    ...data.map((r) => ({ ...r, cat: "数据" })),
  ];
  if (allRisks.length === 0) return <p className="text-sm text-gray-400">{mod.summary ?? "未发现明显风险"}</p>;
  return (
    <div className="space-y-1.5">
      {mod.summary && <p className="mb-2 text-sm text-gray-700">{mod.summary}</p>}
      {allRisks.map((r, i) => (
        <div
          key={i}
          className={`flex items-start gap-2 rounded-lg border p-2 text-xs ${RISK_LEVEL_COLORS[r.level] ?? "border-gray-200 bg-gray-50"}`}
        >
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold ${RISK_LEVEL_LABEL_COLORS[r.level] ?? "bg-gray-100 text-gray-600"}`}>
            {r.level.toUpperCase()}
          </span>
          <span className="shrink-0 rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-gray-500 ring-1 ring-gray-100">
            {r.cat}
          </span>
          <div className="min-w-0">
            <span className="font-medium text-gray-800">{r.signal}</span>
            {r.detail && <span className="ml-1 text-gray-500">{r.detail}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function KeyEvidenceContent({ mod, evidenceItems }: { mod: BriefingModule; evidenceItems: EvidenceItem[] }) {
  const c = mod.content;
  const items = (c?.items ?? evidenceItems) as EvidenceItem[];
  if (items.length === 0) {
    return <p className="text-sm text-gray-400">{mod.summary ?? "暂无关键证据"}</p>;
  }
  return (
    <div className="space-y-1 text-sm">
      {mod.summary && <p className="mb-2 text-gray-700">{mod.summary}</p>}
      <div className="flex flex-col gap-1.5">
        {items.slice(0, 8).map((it, idx) => (
          <div key={it.evidence_id ?? idx} className="flex flex-wrap items-center gap-1.5 rounded-lg bg-white p-2">
            <span className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-blue-100">
              {CATEGORY_LABELS[it.category] ?? it.category}
            </span>
            {it.freshness && (
              <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${FRESHNESS_COLORS[it.freshness] ?? "bg-gray-100 text-gray-500 ring-gray-200"}`}>
                {FRESHNESS_LABELS[it.freshness] ?? it.freshness}
              </span>
            )}
            {it.weight && (
              <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${WEIGHT_COLORS[it.weight] ?? "bg-gray-100 text-gray-500 ring-gray-200"}`}>
                {WEIGHT_LABELS[it.weight] ?? it.weight}
              </span>
            )}
            <a href={it.source_url || "#"} target="_blank" rel="noreferrer"
              className="min-w-0 flex-1 truncate text-blue-700 hover:underline" title={it.title}>
              {it.title}
            </a>
            <span className="shrink-0 text-gray-400">{it.source}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DataStatementContent({ mod, evidenceCount }: { mod: BriefingModule; evidenceCount: number }) {
  const c = mod.content;
  if (!c) return <p className="text-sm text-gray-500">{mod.summary ?? ""}</p>;
  const quality = (c.data_quality as string) ?? "unknown";
  const confidence = (c.confidence as string) ?? "low";
  const missing = (c.missing_data ?? []) as string[];
  const failed = (c.failed_modules ?? []) as Array<{ module: string; fund_code?: string; reason: string }>;
  const lastUpdated = (c.data_sources_last_updated ?? {}) as Record<string, string>;
  return (
    <div className="space-y-2 text-sm">
      {mod.summary && <p className="text-gray-700">{mod.summary}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${QUALITY_BADGE[quality] ?? "bg-gray-100 text-gray-600 ring-gray-200"}`}>
          {QUALITY_LABEL[quality] ?? quality}
        </span>
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${CONFIDENCE_BADGE[confidence] ?? "bg-gray-100 text-gray-600 ring-gray-200"}`}>
          置信度 {CONFIDENCE_LABEL[confidence] ?? confidence}
        </span>
        <span className="text-xs text-gray-400">证据 {evidenceCount} 条</span>
      </div>
      {missing.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-amber-600">缺失：</span>
          {missing.map((m) => (
            <span key={m} className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700 ring-1 ring-amber-100">{m}</span>
          ))}
        </div>
      )}
      {failed.length > 0 && (
        <div className="rounded-lg border border-red-100 bg-red-50 p-2 text-xs text-red-700">
          <div className="mb-1 font-medium">失败模块：</div>
          {failed.map((f, i) => (
            <div key={i}>{f.module}{f.fund_code ? `(${f.fund_code})` : ""}：{f.reason}</div>
          ))}
        </div>
      )}
      {Object.keys(lastUpdated).length > 0 && (
        <div className="text-xs text-gray-400">
          数据源最后更新：{Object.entries(lastUpdated).map(([k, v]) => `${k} ${v ? formatDateTime(v) : "—"}`).join(" · ")}
        </div>
      )}
      {c.disclaimer && (
        <p className="border-t border-gray-200 pt-2 text-xs text-gray-400">{c.disclaimer}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// V2: User Feedback Panel (Phase 5)
// ---------------------------------------------------------------------------

const FEEDBACK_FIELDS: Array<{ key: "risk_accuracy" | "theme_accuracy" | "evidence_quality" | "overall_satisfaction"; label: string }> = [
  { key: "risk_accuracy", label: "风险判断" },
  { key: "theme_accuracy", label: "主线判断" },
  { key: "evidence_quality", label: "证据质量" },
  { key: "overall_satisfaction", label: "整体满意度" },
];

function FeedbackPanel({ briefingId }: { briefingId: number }) {
  const [ratings, setRatings] = useState<Record<string, number>>({});
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setSubmitted(false);
    try {
      await api.briefingFeedback({
        briefing_id: briefingId,
        risk_accuracy: ratings.risk_accuracy,
        theme_accuracy: ratings.theme_accuracy,
        evidence_quality: ratings.evidence_quality,
        overall_satisfaction: ratings.overall_satisfaction,
        comment: comment.trim() || null,
      });
      setSubmitted(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败");
    }
  };

  return (
    <Card className="rounded-2xl p-5">
      <CardHeader className="mb-4">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <ThumbsUp className="h-4 w-4 text-blue-600" />
            简报反馈
          </CardTitle>
          <p className="mt-1 text-xs text-gray-500">用于优化简报质量，可选填写</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {FEEDBACK_FIELDS.map(({ key, label }) => (
          <div key={key} className="flex items-center justify-between gap-2">
            <span className="text-xs text-gray-500">{label}</span>
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setRatings((r) => ({ ...r, [key]: n }))}
                  className={`h-6 w-6 rounded text-xs font-medium transition ${
                    ratings[key] === n
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 text-gray-500 hover:bg-blue-50"
                  }`}
                  aria-label={`${label} ${n} 星`}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        ))}
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="简评（可选）"
          maxLength={2000}
          className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none"
          rows={2}
        />
        <button
          type="button"
          onClick={submit}
          disabled={Object.keys(ratings).length === 0 && !comment.trim()}
          className="w-full rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          提交反馈
        </button>
        {submitted && (
          <p className="text-xs text-emerald-600">已收到您的反馈，感谢支持。</p>
        )}
        {error && (
          <p className="text-xs text-red-600">提交失败：{error}</p>
        )}
      </CardContent>
    </Card>
  );
}
