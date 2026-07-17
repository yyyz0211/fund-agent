import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import { hasReachedMaxAttempts, isWatchlistPreloadTerminal } from "@/lib/polling";
import { queryKeys } from "@/lib/query-keys";
import { queryPolicy } from "@/lib/query-policy";
import type { WatchlistPreloadJob } from "@/types/api";

interface ActivePreloadJob {
  job: WatchlistPreloadJob;
  startedAt: number;
}

interface PreloadPollingTick {
  startedAt: number;
  snapshot: WatchlistPreloadJob | null;
  attempts: number;
}

export function useWatchlistPreloadPolling() {
  const qc = useQueryClient();
  const toast = useToast();
  const [active, setActive] = useState<ActivePreloadJob | null>(null);
  const attemptsRef = useRef(0);
  const fundCode = active?.job.fund_code ?? "";
  const jobId = active?.job.job_id ?? "";
  const pollingKey = queryKeys.watchlist.preloadJob(fundCode, jobId);

  const invalidateFundCaches = useCallback((code: string) => {
    qc.invalidateQueries({ queryKey: queryKeys.watchlist.all });
    qc.invalidateQueries({ queryKey: queryKeys.fund.summaryForFund(code) });
    qc.invalidateQueries({ queryKey: queryKeys.fund.detail(code) });
    qc.invalidateQueries({ queryKey: queryKeys.fund.navForFund(code) });
    qc.invalidateQueries({ queryKey: queryKeys.fund.navHistoryForFund(code) });
    qc.invalidateQueries({ queryKey: queryKeys.fund.metrics(code) });
    qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([code]) });
    qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([]) });
    qc.invalidateQueries({ queryKey: queryKeys.fund.diagnosisForFund(code) });
  }, [qc]);

  const poll = useQuery<PreloadPollingTick>({
    queryKey: pollingKey,
    enabled: active !== null,
    queryFn: async () => {
      if (!active) {
        return { startedAt: 0, snapshot: null, attempts: 0 };
      }
      if (Date.now() - active.startedAt < queryPolicy.watchlistPreload.intervalMs) {
        return { startedAt: active.startedAt, snapshot: null, attempts: attemptsRef.current };
      }
      attemptsRef.current += 1;
      const snapshot = await api.watchlistPreloadJob(active.job.fund_code, active.job.job_id);
      return { startedAt: active.startedAt, snapshot, attempts: attemptsRef.current };
    },
    refetchInterval: active ? queryPolicy.watchlistPreload.intervalMs : false,
    ...queryPolicy.pollingObserver,
    retry: queryPolicy.watchlistPreload.retry,
  });

  useEffect(() => {
    if (!active || !poll.data || poll.data.startedAt !== active.startedAt) return;
    const snapshot = poll.data.snapshot;
    const exhausted = hasReachedMaxAttempts(
      poll.data.attempts,
      queryPolicy.watchlistPreload.maxAttempts,
    );
    if (!snapshot || (!isWatchlistPreloadTerminal(snapshot.status) && !exhausted)) return;

    setActive(null);
    invalidateFundCaches(active.job.fund_code);
    if (snapshot.status === "done") {
      toast.push(`${active.job.fund_code} 基金数据已同步`, "success");
    } else if (snapshot.status === "partial") {
      toast.push(`${active.job.fund_code} 基金数据部分同步完成，仍有字段缺失`, "info");
    } else if (snapshot.status === "failed") {
      toast.push(`${active.job.fund_code} 自动同步失败，可稍后刷新`, "error");
    }
  }, [active, invalidateFundCaches, poll.data, poll.dataUpdatedAt, toast]);

  useEffect(() => {
    if (!active || !poll.error) return;
    setActive(null);
    invalidateFundCaches(active.job.fund_code);
    toast.push(`同步状态查询失败：${String(poll.error)}`, "error");
  }, [active, invalidateFundCaches, poll.error, toast]);

  const startPreloadPolling = useCallback((job: WatchlistPreloadJob) => {
    qc.removeQueries({
      queryKey: queryKeys.watchlist.preloadJob(job.fund_code, job.job_id),
      exact: true,
    });
    attemptsRef.current = 0;
    setActive({ job, startedAt: Date.now() });
  }, [qc]);

  return { startPreloadPolling };
}
