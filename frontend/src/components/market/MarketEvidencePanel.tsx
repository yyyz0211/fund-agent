"use client";
import { useMemo } from "react";
import {
  Building2,
  ExternalLink,
  Globe2,
  Landmark,
  Megaphone,
  Newspaper,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Tag,
} from "lucide-react";
import {
  useMarketEvidence,
  useRefreshEvidence,
  useEvidenceRefreshStatus,
  isMarketDateToday,
} from "@/lib/market";
import type {
  EvidenceCategory,
  MarketEvidenceItem,
  EvidenceReliability,
} from "@/types/api";
import { StateBlock } from "@/components/StateBlock";
import { relativeTime } from "@/lib/market-format";

const CATEGORY_META: Record<EvidenceCategory, { label: string; icon: typeof Tag; tone: string }> = {
  policy: { label: "政策", icon: Landmark, tone: "bg-blue-50 text-blue-700" },
  announcement: { label: "公告", icon: Megaphone, tone: "bg-amber-50 text-amber-700" },
  overseas_disclosure: { label: "海外披露", icon: Globe2, tone: "bg-violet-50 text-violet-700" },
  macro: { label: "宏观", icon: Building2, tone: "bg-cyan-50 text-cyan-700" },
  sector: { label: "行业热点", icon: Tag, tone: "bg-emerald-50 text-emerald-700" },
  news: { label: "市场资讯", icon: Newspaper, tone: "bg-rose-50 text-rose-700" },
};

const CATEGORY_ORDER: EvidenceCategory[] = [
  "policy",
  "announcement",
  "overseas_disclosure",
  "macro",
  "sector",
  "news",
];

const RELIABILITY_LABEL: Record<EvidenceReliability, string> = {
  official: "官方",
  wire: "媒体源",
  rumor: "传闻",
};

const RELIABILITY_BADGE: Record<EvidenceReliability, string> = {
  official: "bg-blue-50 text-blue-700 ring-blue-100",
  wire: "bg-gray-100 text-gray-600 ring-gray-200",
  rumor: "bg-amber-50 text-amber-700 ring-amber-100",
};

interface MarketEvidencePanelProps {
  date: string;
}

function isClsTelegraphEvidence(item: MarketEvidenceItem): boolean {
  if ((item.source || "").trim() !== "财联社") return false;
  if (item.metrics?.cls_id) return true;
  return item.source_url.includes("https://www.cls.cn/detail/");
}

function sourceNewsLabel(item: MarketEvidenceItem): string {
  const normalized = (item.source || "").trim();
  if (isClsTelegraphEvidence(item)) return "财联社电报";
  if (normalized) return `${normalized}资讯`;
  return "市场资讯";
}

function evidenceCategoryLabel(item: MarketEvidenceItem): string {
  if (item.category !== "news") return CATEGORY_META[item.category].label;
  return sourceNewsLabel(item);
}

function evidenceSummaryCategoryLabel(category: EvidenceCategory, rows: MarketEvidenceItem[]): string {
  if (category !== "news") return CATEGORY_META[category].label;
  const labels = Array.from(new Set(rows.map((row) => evidenceCategoryLabel(row))));
  if (labels.length === 1) return labels[0];
  return CATEGORY_META.news.label;
}

export function MarketEvidencePanel({ date }: MarketEvidencePanelProps) {
  const { data, isLoading, error } = useMarketEvidence(date);
  const refresh = useRefreshEvidence(date);
  const refreshStatus = useEvidenceRefreshStatus();
  const groups = data?.groups ?? {};
  const count = data?.count ?? 0;
  const hasAny = count > 0 && Object.keys(groups).length > 0;
  const isToday = isMarketDateToday(date);
  const refreshResult = refreshStatus.data?.result;
  const refreshErrors = refreshResult?.errors ?? [];
  const firstRefreshError = refreshErrors[0];
  const remoteFailed =
    isToday &&
    !hasAny &&
    (refreshStatus.data?.status === "failed" || refreshStatus.data?.status === "partial") &&
    refreshErrors.length > 0;
  const manualDisabled = refresh.isPending || !isToday;
  const manualTitle = isToday
    ? "立即触发一次 evidence 采集(市场资讯 / 公告 / 宏观等)"
    : "历史日不支持手动刷新:akshare / 财联社接口只取最新,刷新会写错日期";

  const presentCategories = useMemo(
    () => CATEGORY_ORDER.filter((c) => (groups[c]?.length ?? 0) > 0),
    [groups],
  );

  const items = useMemo(
    () =>
      presentCategories.flatMap((cat) =>
        ((groups[cat] ?? []) as MarketEvidenceItem[]).map((item) => item),
      ),
    [groups, presentCategories],
  );

  if (isLoading) return <StateBlock title="正在加载证据…" tone="loading" />;
  if (error) return <StateBlock title="证据加载失败" tone="error">{String(error)}</StateBlock>;
  if (!hasAny) {
    return (
      <StateBlock
        title={remoteFailed ? "远程证据获取失败" : "今日暂无证据"}
        action={<span className="text-xs text-gray-400">来源：market_evidence 本地表</span>}
      >
        <div className="mt-2 flex justify-center">
          <button
            onClick={() => refresh.mutate()}
            disabled={manualDisabled}
            title={manualTitle}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-600 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${refresh.isPending ? "animate-spin" : ""}`} />
            {refresh.isPending ? "采集中…" : "立即拉取"}
          </button>
        </div>
        {remoteFailed ? (
          <div className="mt-2 space-y-1 text-xs leading-5 text-gray-500">
            <p>
              最近一次拉取未写入数据
              {refreshResult ? `（抓取 ${refreshResult.fetched} 条，新增 ${refreshResult.inserted} 条）` : null}
              ，请检查后端到财联社/公开数据源的网络连接。
            </p>
            {firstRefreshError ? (
              <p className="line-clamp-2 text-amber-700">
                {firstRefreshError.adapter ? `${firstRefreshError.adapter}: ` : ""}
                {firstRefreshError.error}
              </p>
            ) : null}
          </div>
        ) : (
          "暂无可验证证据（政策 / 公告 / 宏观 / 行业 / 市场资讯）。本地未采集到当日证据，证据面板留空并不代表市场没有事件。"
        )}
      </StateBlock>
    );
  }

  return (
    <div className="flex h-[520px] flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <header className="flex flex-col gap-2 border-b border-gray-100 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="text-sm font-semibold text-gray-950">证据面板</h2>
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
            共 {count} 条
          </span>
          <button
            onClick={() => refresh.mutate()}
            disabled={manualDisabled}
            title={manualTitle}
            className="inline-flex items-center gap-1 rounded-md border border-gray-200 bg-white px-1.5 py-0.5 text-[11px] font-medium text-gray-600 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${refresh.isPending ? "animate-spin" : ""}`} />
            {refresh.isPending ? "采集中…" : "立即拉取"}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {presentCategories.map((cat) => {
            const meta = CATEGORY_META[cat];
            const Icon = meta.icon;
            const rows = (groups[cat] ?? []) as MarketEvidenceItem[];
            const n = rows.length;
            return (
              <span
                key={cat}
                className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${meta.tone}`}
              >
                <Icon className="h-3 w-3" />
                {evidenceSummaryCategoryLabel(cat, rows)}
                <span className="tabular-nums">{n}</span>
              </span>
            );
          })}
        </div>
      </header>

      <ul className="min-h-0 flex-1 divide-y divide-gray-100 overflow-y-auto">
        {items.map((item) => (
          <EvidenceRow key={item.id} item={item} />
        ))}
      </ul>

      <p className="border-t border-gray-100 bg-gray-50/70 px-3 py-2 text-[11px] text-gray-400">
        来源：market_evidence 本地表 · 公开政策页 / 宏观数据 / 公告 / 公开资讯源 · 仅供研究参考。
      </p>
    </div>
  );
}

function EvidenceRow({ item }: { item: MarketEvidenceItem }) {
  const reliability = (item.reliability || "wire") as EvidenceReliability;
  const meta = CATEGORY_META[item.category];
  const Icon = meta.icon;
  const label = evidenceCategoryLabel(item);
  return (
    <li className="px-3 py-2.5 transition hover:bg-gray-50/70">
      <div className="flex min-w-0 items-start gap-2">
        <span
          className={`mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ${meta.tone}`}
        >
          <Icon className="h-3 w-3" />
          {label}
        </span>
        <div className="min-w-0 flex-1">
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="line-clamp-2 text-sm font-semibold leading-5 text-gray-950 hover:text-blue-700"
            title={item.title}
            aria-label={`打开证据：${item.title}`}
          >
            {item.title}
            <ExternalLink className="ml-1 inline h-3 w-3 align-middle text-gray-400" />
          </a>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-gray-400">
            <span>{item.source}</span>
            {item.published_at ? <span>{relativeTime(item.published_at)}</span> : null}
            <span
              className={`inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${RELIABILITY_BADGE[reliability]}`}
            >
              {reliability === "official" ? (
                <ShieldCheck className="h-3 w-3" />
              ) : (
                <ShieldAlert className="h-3 w-3" />
              )}
              {RELIABILITY_LABEL[reliability]}
            </span>
          </div>
          {item.summary ? <p className="mt-1 line-clamp-1 text-xs leading-4 text-gray-500">{item.summary}</p> : null}
          {item.symbols && item.symbols.length > 0 ? (
            <div className="mt-1 truncate text-[11px] text-gray-400">
              tag · {item.symbols.slice(0, 4).join(" / ")}
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}
