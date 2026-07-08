import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { EvidenceCategory, MarketEvidenceItem, MarketEvidenceResponse } from "@/types/api";

export interface MarketBreadth {
  up: number;
  down: number;
  limit_up: number;
  limit_down: number;
  volume?: number;
  amount?: number;
  total?: number;
  source?: string;
  as_of?: string;
  error?: string;
}

export interface MarketSnapshot {
  trade_date: string;
  snapshot_type: string;
  indices: Array<{ symbol: string; name: string; close: number; change_pct: number }>;
  breadth: Partial<MarketBreadth> & { error?: string; source?: string };
  industry_sectors: Array<{ name: string; change_pct: number }>;
  concept_sectors: Array<{ name: string; change_pct: number }>;
  industry_flows: Array<{ name: string; net_flow: number }>;
  concept_flows: Array<{ name: string; net_flow: number }>;
  themes: Array<{ theme: string; count: number; stocks: Array<{ name: string }> }>;
  breadth_indicators: { board_height: Array<{ name: string; boards: number }> };
  overseas: Array<{ market: string; name: string; symbol: string; close: number | null; change_pct: number | null }>;
  announcements: Array<{ title: string; ann_date: string; fund_code: string; fund_name: string }>;
  source: string;
  as_of: string;
}

function finiteNumber(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

export function normalizeMarketBreadth(
  breadth: MarketSnapshot["breadth"] | null | undefined,
): MarketBreadth {
  return {
    up: finiteNumber(breadth?.up),
    down: finiteNumber(breadth?.down),
    limit_up: finiteNumber(breadth?.limit_up),
    limit_down: finiteNumber(breadth?.limit_down),
    volume: breadth?.volume === undefined ? undefined : finiteNumber(breadth.volume),
    amount: breadth?.amount === undefined ? undefined : finiteNumber(breadth.amount),
    total: breadth?.total === undefined ? undefined : finiteNumber(breadth.total),
    source: breadth?.source,
    as_of: breadth?.as_of,
    error: typeof breadth?.error === "string" ? breadth.error : undefined,
  };
}

export function flattenMarketEvidence(
  response: MarketEvidenceResponse | null | undefined,
): MarketEvidenceItem[] {
  if (response?.items && response.items.length > 0) return response.items;
  return Object.values(response?.groups ?? {}).flatMap((items) =>
    Array.isArray(items) ? items : [],
  );
}

function formatShanghaiDate(date: Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function resolveMarketDate(opt: string, now: Date = new Date()): string {
  const target = opt === "yesterday"
    ? new Date(now.getTime() - 24 * 60 * 60 * 1000)
    : now;
  return formatShanghaiDate(target);
}

export function useMarketSnapshot(date: string, type: string) {
  return useQuery<MarketSnapshot>({
    queryKey: ["market", "snapshot", date, type],
    queryFn: () =>
      fetch(`/api/market/snapshot?date=${encodeURIComponent(date)}&type=${encodeURIComponent(type)}`).then(r => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      }),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useMarketEvidence(date: string, category?: EvidenceCategory, limit: number = 20) {
  return useQuery<MarketEvidenceResponse>({
    queryKey: ["market", "evidence", date, category ?? "", limit],
    queryFn: () => {
      const url = new URL("/api/market/evidence", window.location.origin);
      url.searchParams.set("date", date);
      url.searchParams.set("limit", String(limit));
      if (category) url.searchParams.set("category", category);
      return fetch(url.toString()).then(r => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      });
    },
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useRefreshMarket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      fetch("/api/market/refresh", {
        method: "POST",
        headers: { "X-Local-Trigger": "1" },
      }).then(r => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["market"] });
    },
  });
}
