import type { MarketEvidenceResponse, WatchlistPreloadStatus } from "@/types/api";

export function marketSnapshotFingerprint(snapshot: { trade_date?: string | null } | null | undefined) {
  return JSON.stringify(snapshot?.trade_date ?? null);
}

export function marketEvidenceFingerprint(evidence: MarketEvidenceResponse | null | undefined) {
  return JSON.stringify(evidence?.items ?? evidence?.groups ?? null);
}

export function hasFingerprintChanged(baseline: string, current: string) {
  return baseline !== current;
}

export function isWatchlistPreloadTerminal(status: WatchlistPreloadStatus) {
  return ["done", "partial", "failed", "missing"].includes(status);
}

export function hasPollingTimedOut(startedAt: number, now: number, timeoutMs: number) {
  return now - startedAt >= timeoutMs;
}

export function hasReachedMaxAttempts(attempts: number, maxAttempts: number) {
  return attempts >= maxAttempts;
}
