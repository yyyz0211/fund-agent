export const queryDefaults = {
  staleTime: 60_000,
  gcTime: 300_000,
  retry: 3,
  refetchOnWindowFocus: false,
} as const;

export const queryPolicy = {
  marketData: {
    staleTime: 300_000,
    retry: 1,
  },
  evidenceStatus: {
    staleTime: 5_000,
    refetchInterval: 5_000,
    retry: 1,
  },
  briefingLatest: {
    refetchInterval: 30_000,
  },
  diagnosisRefreshJob: {
    intervalMs: 1_000,
  },
  langgraphHealth: {
    retry: false,
  },
  pollingObserver: {
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchIntervalInBackground: true,
  },
  marketSnapshotRefresh: {
    intervalMs: 4_000,
    timeoutMs: 30_000,
  },
  marketEvidenceRefresh: {
    intervalMs: 3_000,
    timeoutMs: 60_000,
  },
  watchlistPreload: {
    intervalMs: 1_500,
    maxAttempts: 120,
    retry: false,
  },
} as const;
