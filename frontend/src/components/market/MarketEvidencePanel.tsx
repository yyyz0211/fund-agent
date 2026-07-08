"use client";
import { FileSearch2, ExternalLink, ShieldCheck, ShieldAlert, Newspaper } from "lucide-react";
import { useMarketEvidence } from "@/lib/market";
import type {
  EvidenceCategory,
  MarketEvidenceItem,
  EvidenceReliability,
} from "@/types/api";

const CATEGORY_LABELS: Record<EvidenceCategory, string> = {
  policy: "政策",
  announcement: "公告",
  overseas_disclosure: "海外披露",
  macro: "宏观",
  sector: "行业热点",
  news: "财联社快讯",
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
  wire: "聚合",
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

export function MarketEvidencePanel({ date }: MarketEvidencePanelProps) {
  const { data, isLoading, error } = useMarketEvidence(date);

  if (isLoading) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-400 shadow-sm">
        正在加载证据…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 shadow-sm">
        证据加载失败：{String(error)}
      </div>
    );
  }
  const groups = data?.groups ?? {};
  const count = data?.count ?? 0;
  const hasAny = count > 0 && Object.keys(groups).length > 0;

  if (!hasAny) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white px-4 py-10 text-center text-sm text-gray-400 shadow-sm">
        <FileSearch2 className="mx-auto mb-2 h-5 w-5 text-gray-300" />
        暂无可验证证据（政策/公告/宏观/行业/财联社快讯）。本地未采集到当日证据，证据面板留空并不代表市场没有事件。
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {CATEGORY_ORDER.map((cat) => {
        const items = groups[cat] as MarketEvidenceItem[] | undefined;
        if (!items || items.length === 0) return null;
        return (
          <section
            key={cat}
            className="rounded-xl border border-gray-200 bg-white shadow-sm"
            aria-label={CATEGORY_LABELS[cat]}
          >
            <header className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
              <div className="flex items-center gap-2">
                <Newspaper className="h-4 w-4 text-blue-700" />
                <h3 className="text-sm font-semibold text-gray-950">
                  {CATEGORY_LABELS[cat]}
                </h3>
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                  {items.length} 条
                </span>
              </div>
              <span className="text-[11px] text-gray-400">来源：官方公开页 / 宏观数据 / 财联社聚合</span>
            </header>
            <ul className="divide-y divide-gray-100">
              {items.map((item) => (
                <EvidenceRow key={item.id} item={item} />
              ))}
            </ul>
          </section>
        );
      })}
      <p className="px-1 text-[11px] text-gray-400">
        面板数据来源于本地 market_evidence 表, 抓取自公开政策页 / 公开宏观数据 / 公开公告 / 财联社电报; 仅供研究参考, 不构成投资建议。
      </p>
    </div>
  );
}

function EvidenceRow({ item }: { item: MarketEvidenceItem }) {
  const reliability = (item.reliability || "wire") as EvidenceReliability;
  return (
    <li className="flex gap-3 px-4 py-3">
      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="block truncate text-sm font-medium text-gray-950 hover:text-blue-700"
            title={item.title}
          >
            {item.title}
            <ExternalLink className="ml-1 inline h-3 w-3 align-middle text-gray-400" />
          </a>
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
        {item.summary ? (
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">
            {item.summary}
          </p>
        ) : null}
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-gray-400">
          <span>来源 · {item.source}</span>
          {item.published_at ? <span>published_at · {item.published_at}</span> : null}
          {item.symbols && item.symbols.length > 0 ? (
            <span>tag · {item.symbols.slice(0, 3).join(" / ")}</span>
          ) : null}
        </div>
      </div>
    </li>
  );
}