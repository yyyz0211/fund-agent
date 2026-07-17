import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { queryPolicy } from "@/lib/query-policy";
import {
  hasFingerprintChanged,
  hasPollingTimedOut,
  marketEvidenceFingerprint,
  marketSnapshotFingerprint,
} from "@/lib/polling";
import type {
  EvidenceCategory,
  MarketEvidenceItem,
  MarketEvidenceRefreshStatus,
  MarketEvidenceResponse,
} from "@/types/api";

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
  /** true = 数据不可信 (接口空/列名改/全 0); 前端应展示空态而非"震荡" */
  stale?: boolean;
  stale_reason?: string;
  error?: string;
}

export interface MarketSnapshot {
  trade_date: string;
  snapshot_type: string;
  indices: Array<{ symbol: string; name: string; close: number; change_pct: number; history?: number[] | null }>;
  breadth: Partial<MarketBreadth> & { error?: string; source?: string };
  industry_sectors: Array<{ name: string; change_pct: number; history?: number[] | null }>;
  concept_sectors: Array<{ name: string; change_pct: number; history?: number[] | null }>;
  industry_flows: Array<{ name: string; net_flow: number }>;
  concept_flows: Array<{ name: string; net_flow: number }>;
  themes: Array<{ theme: string; count: number; stocks: Array<{ name: string }> }>;
  breadth_indicators: { board_height: Array<{ name: string; boards: number }> };
  overseas: Array<{ market: string; name: string; symbol: string; close: number | null; change_pct: number | null }>;
  announcements: Array<{ title: string; ann_date: string; fund_code: string; fund_name: string }>;
  /** 字段级 staleness:外网接口拉取失败时为 true。前端应据此展示"网络异常"而非"暂无数据"。 */
  stale_fields?: Partial<Record<"industry_sectors" | "concept_sectors" | "industry_flows" | "concept_flows" | "themes" | "overseas" | "announcements", boolean>>;
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
    stale: Boolean(breadth?.stale),
    stale_reason: typeof breadth?.stale_reason === "string" ? breadth.stale_reason : undefined,
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

/** 当前本地日历日(Asia/Shanghai),格式 YYYY-MM-DD。 */
export function todayShanghai(now: Date = new Date()): string {
  return formatShanghaiDate(now);
}

/** 给定 YYYY-MM-DD 是否为今天。 */
export function isMarketDateToday(date: string, now: Date = new Date()): boolean {
  return date === todayShanghai(now);
}

export function useMarketSnapshot(date: string, type: string) {
  return useQuery<MarketSnapshot>({
    queryKey: queryKeys.market.snapshot(date, type),
    queryFn: () =>
      fetch(`/api/market/snapshot?date=${encodeURIComponent(date)}&type=${encodeURIComponent(type)}`).then(r => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      }),
    ...queryPolicy.marketData,
  });
}

export function useMarketEvidence(date: string, category?: EvidenceCategory, limit: number = 20) {
  return useQuery<MarketEvidenceResponse>({
    queryKey: queryKeys.market.evidence.list(date, category ?? "", limit),
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
    ...queryPolicy.marketData,
  });
}

export function useEvidenceRefreshStatus(briefType: string = "post_market") {
  return useQuery<MarketEvidenceRefreshStatus>({
    queryKey: queryKeys.market.evidence.refreshStatus(briefType),
    queryFn: () =>
      fetch(`/api/market/evidence/refresh/status?brief_type=${encodeURIComponent(briefType)}`).then((r) => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      }),
    ...queryPolicy.evidenceStatus,
  });
}

interface RefreshPollingState {
  active: boolean;
  startedAt: number;
  baseline: string;
  target: string | undefined;
}

interface RefreshPollingTick {
  startedAt: number;
  fingerprint: string;
}

const idlePolling: RefreshPollingState = {
  active: false,
  startedAt: 0,
  baseline: "",
  target: undefined,
};

export function useRefreshMarket(date?: string) {
  const qc = useQueryClient();
  const snapshotTargetRef = useRef<string | undefined>(date);
  const [polling, setPolling] = useState<RefreshPollingState>(idlePolling);
  const targetDate = polling.active ? polling.target : date;
  const resourceKey = targetDate
    ? queryKeys.market.snapshot(targetDate, "post_market")
    : queryKeys.market.snapshots;
  const pollingKey = queryKeys.market.refreshPolling.snapshot(targetDate);
  const poll = useQuery<RefreshPollingTick>({
    queryKey: pollingKey,
    enabled: polling.active,
    queryFn: async () => {
      if (Date.now() - polling.startedAt < queryPolicy.marketSnapshotRefresh.intervalMs) {
        return { startedAt: polling.startedAt, fingerprint: polling.baseline };
      }
      try {
        await qc.refetchQueries({ queryKey: resourceKey });
      } catch {
        // 单次失败忽略，下一次 observer tick 继续轮询。
      }
      return {
        startedAt: polling.startedAt,
        fingerprint: marketSnapshotFingerprint(qc.getQueryData<MarketSnapshot>(resourceKey)),
      };
    },
    refetchInterval: polling.active ? queryPolicy.marketSnapshotRefresh.intervalMs : false,
    ...queryPolicy.pollingObserver,
  });

  useEffect(() => {
    if (!polling.active || !poll.data || poll.data.startedAt !== polling.startedAt) return;
    const completed = hasFingerprintChanged(polling.baseline, poll.data.fingerprint);
    const timedOut = hasPollingTimedOut(
      polling.startedAt,
      Date.now(),
      queryPolicy.marketSnapshotRefresh.timeoutMs,
    );
    if (!completed && !timedOut) return;
    setPolling(idlePolling);
    qc.invalidateQueries({ queryKey: queryKeys.market.all });
  }, [poll.data, poll.dataUpdatedAt, polling, qc]);

  const mutation = useMutation({
    mutationFn: () => {
      snapshotTargetRef.current = date;
      const target = snapshotTargetRef.current;
      return fetch(`/api/market/refresh${target ? `?date=${encodeURIComponent(target)}` : ""}`, {
        method: "POST",
        headers: { "X-Local-Trigger": "1" },
      }).then((r) => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      });
    },
    onSuccess: () => {
      const target = snapshotTargetRef.current;
      const startedAt = Date.now();
      const targetResourceKey = target
        ? queryKeys.market.snapshot(target, "post_market")
        : queryKeys.market.snapshots;
      qc.removeQueries({
        queryKey: queryKeys.market.refreshPolling.snapshot(target),
        exact: true,
      });
      setPolling({
        active: true,
        startedAt,
        baseline: marketSnapshotFingerprint(qc.getQueryData<MarketSnapshot>(targetResourceKey)),
        target,
      });
    },
  });

  return { ...mutation, isPending: mutation.isPending || polling.active };
}

export function useRefreshEvidence(date: string) {
  const qc = useQueryClient();
  const evidenceTargetRef = useRef(date);
  const [polling, setPolling] = useState<RefreshPollingState>(idlePolling);
  const targetDate = polling.active ? polling.target ?? date : date;
  const resourceKey = queryKeys.market.evidence.list(targetDate, "", 20);
  const pollingKey = queryKeys.market.refreshPolling.evidence(targetDate);
  const poll = useQuery<RefreshPollingTick>({
    queryKey: pollingKey,
    enabled: polling.active,
    queryFn: async () => {
      if (Date.now() - polling.startedAt < queryPolicy.marketEvidenceRefresh.intervalMs) {
        return { startedAt: polling.startedAt, fingerprint: polling.baseline };
      }
      try {
        await qc.refetchQueries({ queryKey: resourceKey });
        await qc.refetchQueries({
          queryKey: queryKeys.market.evidence.refreshStatus("post_market"),
        });
      } catch {
        // 单次失败忽略，下一次 observer tick 继续轮询。
      }
      return {
        startedAt: polling.startedAt,
        fingerprint: marketEvidenceFingerprint(qc.getQueryData<MarketEvidenceResponse>(resourceKey)),
      };
    },
    refetchInterval: polling.active ? queryPolicy.marketEvidenceRefresh.intervalMs : false,
    ...queryPolicy.pollingObserver,
  });

  useEffect(() => {
    if (!polling.active || !poll.data || poll.data.startedAt !== polling.startedAt) return;
    const completed = hasFingerprintChanged(polling.baseline, poll.data.fingerprint);
    const timedOut = hasPollingTimedOut(
      polling.startedAt,
      Date.now(),
      queryPolicy.marketEvidenceRefresh.timeoutMs,
    );
    if (!completed && !timedOut) return;
    setPolling(idlePolling);
    qc.invalidateQueries({ queryKey: queryKeys.market.evidence.all });
    qc.invalidateQueries({ queryKey: queryKeys.market.evidence.refreshStatuses });
  }, [poll.data, poll.dataUpdatedAt, polling, qc]);

  const mutation = useMutation({
    mutationFn: () => {
      evidenceTargetRef.current = date;
      return fetch(
        `/api/market/evidence/refresh?brief_type=post_market`,
        {
          method: "POST",
          headers: { "X-Local-Trigger": "1" },
        },
      ).then((r) => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      });
    },
    onSuccess: () => {
      const target = evidenceTargetRef.current;
      const startedAt = Date.now();
      const targetResourceKey = queryKeys.market.evidence.list(target, "", 20);
      qc.removeQueries({
        queryKey: queryKeys.market.refreshPolling.evidence(target),
        exact: true,
      });
      setPolling({
        active: true,
        startedAt,
        baseline: marketEvidenceFingerprint(
          qc.getQueryData<MarketEvidenceResponse>(targetResourceKey),
        ),
        target,
      });
    },
  });

  return { ...mutation, isPending: mutation.isPending || polling.active };
}
