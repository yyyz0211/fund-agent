# Phase 3A React Query Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-cut every frontend query/cache key to one typed factory, make the existing Query Client policies explicit, and replace the Market and Watchlist handwritten polling loops with behavior-compatible React Query observers.

**Architecture:** `query-keys.ts` is the only production source of query-key tuples; `query-policy.ts` owns the existing effective timing/retry values; `polling.ts` owns pure completion predicates. Market keeps its public refresh hooks but composes mutation state with internal polling queries, while Watchlist moves preload polling into a dedicated domain hook.

**Tech Stack:** Next.js 14.2.5, React 18.3.1, TypeScript 5.5 strict, TanStack React Query 5.51, Node `node:test`, TypeScript compiler API/VM.

## Global Constraints

- Preserve every existing query-key tuple value, element order, nesting, and prefix invalidation relationship.
- Hard cut the whole frontend in one implementation commit; do not keep raw-key constants, wrappers, re-exports, or dual paths.
- Preserve effective defaults exactly: `staleTime=60_000`, `gcTime=300_000`, `retry=3`, `refetchOnWindowFocus=false`.
- Preserve Market data policy exactly: `staleTime=300_000`, `retry=1`.
- Preserve evidence status polling at 5 seconds, briefing polling at 30 seconds, and active diagnosis-job polling at 1 second.
- Preserve Market snapshot refresh at 4-second intervals through the first tick at or after 30 seconds.
- Preserve Market evidence refresh at 3-second intervals through the first tick at or after 60 seconds.
- Preserve Watchlist preload polling at 1.5-second intervals for at most 120 returned snapshots.
- Preserve request URLs, headers, mutation names, public hook APIs, button pending/disabled behavior, toast text/tone/order, terminal states, and invalidation sets.
- Drawer close must not cancel preload polling; route/component unmount must cancel it.
- Do not introduce Zustand, Redux, a global background-job Provider, a generic polling framework, new dependencies, or a new test framework.
- Do not include Phase 3B LangGraph event typing, API error parsing, discriminated unions, or unrelated UI changes.
- Do not edit, stage, or commit `backend/db/session.py`, `backend/db/types.py`, or `backend/integrations/market_evidence.py`.
- Tasks 1–5 are RED/GREEN checkpoints only. Create exactly one implementation commit in Task 6.

---

## File Map

**Create**

- `frontend/src/lib/query-keys.ts` — the only production tuple definitions.
- `frontend/src/lib/query-policy.ts` — effective Query Client/query/polling policies.
- `frontend/src/lib/polling.ts` — pure fingerprints, terminal and boundary predicates.
- `frontend/src/components/watchlist-drawer/hooks/useWatchlistPreloadPolling.ts` — preload query observer, cache invalidation and toast lifecycle.
- `frontend/tests/query-keys.test.mjs` — exact key-value and prefix contracts.
- `frontend/tests/query-structure.test.mjs` — AST hard-cut and timer-boundary contracts.
- `frontend/tests/polling.test.mjs` — pure policy/polling boundary contracts.

**Modify**

- `frontend/app/providers.tsx`
- `frontend/app/briefing/page.tsx`
- `frontend/app/compare/page.tsx`
- `frontend/app/funds/[code]/page.tsx`
- `frontend/app/portfolio/page.tsx`
- `frontend/app/watchlist/page.tsx`
- `frontend/src/components/HoldingCard.tsx`
- `frontend/src/components/MarketIndexCard.tsx`
- `frontend/src/components/NavChart.tsx`
- `frontend/src/components/WatchlistTable.tsx`
- `frontend/src/components/qa/QaWorkbench.tsx`
- `frontend/src/components/watchlist-drawer/hooks/useInvestmentPlanActions.ts`
- `frontend/src/components/watchlist-drawer/hooks/usePendingBuyActions.ts`
- `frontend/src/components/watchlist-drawer/hooks/useTransactionActions.ts`
- `frontend/src/components/watchlist-drawer/hooks/useWatchlistDrawerData.ts`
- `frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts`
- `frontend/src/lib/market.ts`
- `frontend/tests/market-lib.test.mjs`
- `frontend/tests/watchlist-drawer-structure.test.mjs`
- `frontend/tests/watchlist-refresh.test.mjs`

**Do not modify**

- Backend files, API contracts, Watchlist/Market presentation components, or Phase 3B type files.

---

### Task 1: Establish the RED query-governance gates

**Files:**

- Create: `frontend/tests/query-keys.test.mjs`
- Create: `frontend/tests/query-structure.test.mjs`
- Create: `frontend/tests/polling.test.mjs`
- Modify: `frontend/tests/watchlist-drawer-structure.test.mjs`
- Modify: `frontend/tests/watchlist-refresh.test.mjs`

**Interfaces:**

- Consumes: current raw query arrays and handwritten polling code.
- Produces: exact contracts for Tasks 2–5.

- [ ] **Step 1: Record the frontend baseline**

Run:

```bash
cd frontend
npm test
npx tsc --noEmit
npm run build
```

Expected before new tests: 94 tests pass, TypeScript exits 0, and Next generates 11 pages including `/qa`.

- [ ] **Step 2: Add the exact query-key contract test**

Create `frontend/tests/query-keys.test.mjs` with a VM loader and these assertions:

```js
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadQueryKeys() {
  const path = "../src/lib/query-keys.ts";
  const source = await fs.readFile(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  const context = { exports, module: { exports } };
  vm.runInNewContext(compiled, context, { filename: path });
  return context.module.exports.queryKeys;
}

function normalize(value) {
  return JSON.parse(JSON.stringify(value));
}

function isPrefix(prefix, value) {
  return prefix.every((part, index) =>
    JSON.stringify(part) === JSON.stringify(value[index]),
  );
}

test("query key factory preserves every existing tuple", async () => {
  const keys = await loadQueryKeys();
  assert.deepEqual(normalize(keys.watchlist.all), ["watchlist"]);
  assert.deepEqual(normalize(keys.watchlist.transactions("110011")), ["watchlistTransactions", "110011"]);
  assert.deepEqual(normalize(keys.watchlist.investmentPlans("110011")), ["investmentPlans", "110011"]);
  assert.deepEqual(normalize(keys.watchlist.pendingBuys("110011")), ["pendingBuys", "110011"]);
  assert.deepEqual(normalize(keys.watchlist.preloadJob("110011", "job-1")), ["watchlistPreloadJob", "110011", "job-1"]);
  assert.deepEqual(normalize(keys.fund.detail("110011")), ["fund", "110011"]);
  assert.deepEqual(normalize(keys.fund.navForFund("110011")), ["nav", "110011"]);
  assert.deepEqual(normalize(keys.fund.nav("110011", "2026-07-17")), ["nav", "110011", "2026-07-17"]);
  assert.deepEqual(normalize(keys.fund.navHistoryForFund("110011")), ["navHistory", "110011"]);
  assert.deepEqual(normalize(keys.fund.navHistory("110011", undefined)), ["navHistory", "110011", null]);
  assert.equal(keys.fund.navHistory("110011", undefined)[2], undefined);
  assert.deepEqual(normalize(keys.fund.metrics("110011")), ["metrics", "110011"]);
  assert.deepEqual(normalize(keys.fund.summaryForFund("110011")), ["fundSummary", "110011"]);
  assert.deepEqual(normalize(keys.fund.summary("110011", "1m", "2026-06-17")), ["fundSummary", "110011", "1m", "2026-06-17"]);
  assert.deepEqual(normalize(keys.fund.diagnosisForFund("110011")), ["fundDiagnosis", "110011"]);
  assert.deepEqual(normalize(keys.fund.diagnosis("110011", "1m")), ["fundDiagnosis", "110011", "1m"]);
  assert.deepEqual(normalize(keys.fund.diagnosisRefreshJob("110011", null)), ["fundDiagnosisRefreshJob", "110011", null]);
  assert.deepEqual(normalize(keys.portfolio.pnl([])), ["portfolioPnl", []]);
  assert.deepEqual(normalize(keys.portfolio.pnl(["110011"])), ["portfolioPnl", ["110011"]]);
  assert.deepEqual(normalize(keys.market.all), ["market"]);
  assert.deepEqual(normalize(keys.market.latest), ["market", "latest"]);
  assert.deepEqual(normalize(keys.market.snapshots), ["market", "snapshot"]);
  assert.deepEqual(normalize(keys.market.snapshot("2026-07-17", "post_market")), ["market", "snapshot", "2026-07-17", "post_market"]);
  assert.deepEqual(normalize(keys.market.evidence.all), ["market", "evidence"]);
  assert.deepEqual(normalize(keys.market.evidence.list("2026-07-17", "", 20)), ["market", "evidence", "2026-07-17", "", 20]);
  assert.deepEqual(normalize(keys.market.evidence.refreshStatuses), ["market", "evidence", "refresh-status"]);
  assert.deepEqual(normalize(keys.market.evidence.refreshStatus("post_market")), ["market", "evidence", "refresh-status", "post_market"]);
  assert.deepEqual(normalize(keys.market.refreshPolling.snapshot(undefined)), ["marketRefreshPolling", "snapshot", ""]);
  assert.deepEqual(normalize(keys.market.refreshPolling.evidence("2026-07-17")), ["marketRefreshPolling", "evidence", "2026-07-17"]);
  assert.deepEqual(normalize(keys.briefing.all), ["briefing"]);
  assert.deepEqual(normalize(keys.briefing.latest), ["briefing", "latest"]);
  assert.deepEqual(normalize(keys.briefing.list(30)), ["briefing", "list", 30]);
  assert.deepEqual(normalize(keys.briefing.evidence("2026-07-17")), ["briefing", "evidence", "2026-07-17"]);
  assert.deepEqual(normalize(keys.compare(["110011", "000001"])), ["compare", ["110011", "000001"]]);
  assert.deepEqual(normalize(keys.langgraph.health), ["langgraph", "health"]);
});

test("query key factory preserves prefix invalidation relationships", async () => {
  const keys = await loadQueryKeys();
  assert.equal(isPrefix(keys.market.all, keys.market.snapshot("2026-07-17", "post_market")), true);
  assert.equal(isPrefix(keys.market.evidence.all, keys.market.evidence.refreshStatus("post_market")), true);
  assert.equal(isPrefix(keys.market.evidence.refreshStatuses, keys.market.evidence.refreshStatus("post_market")), true);
  assert.equal(isPrefix(keys.fund.summaryForFund("110011"), keys.fund.summary("110011", "1m", "2026-06-17")), true);
  assert.notDeepEqual(normalize(keys.portfolio.pnl([])), normalize(keys.portfolio.pnl(["110011"])));
});
```

Note: JSON normalization represents an array element whose runtime value is `undefined` as `null`; the factory still returns `undefined` at runtime.

- [ ] **Step 3: Add the AST hard-cut test**

Create `frontend/tests/query-structure.test.mjs`. Recursively collect `.ts/.tsx` files under `app` and `src`, exclude `src/lib/query-keys.ts`, parse them with `ts.createSourceFile`, and report:

```js
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

function findViolations(source, path) {
  const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const violations = [];
  const cacheMethods = new Set([
    "getQueryData", "setQueryData", "invalidateQueries", "refetchQueries",
    "removeQueries", "cancelQueries",
  ]);

  function visit(node) {
    if (
      ts.isPropertyAssignment(node) &&
      node.name.getText(file) === "queryKey" &&
      ts.isArrayLiteralExpression(node.initializer)
    ) {
      violations.push(`${path}:${file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1}: raw queryKey`);
    }
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      const method = node.expression.name.text;
      if (cacheMethods.has(method)) {
        const first = node.arguments[0];
        if (first && ts.isArrayLiteralExpression(first)) {
          violations.push(`${path}:${file.getLineAndCharacterOfPosition(first.getStart(file)).line + 1}: raw ${method}`);
        }
        if (first && ts.isObjectLiteralExpression(first)) {
          for (const property of first.properties) {
            if (
              ts.isPropertyAssignment(property) &&
              property.name.getText(file) === "queryKey" &&
              ts.isArrayLiteralExpression(property.initializer)
            ) {
              violations.push(`${path}:${file.getLineAndCharacterOfPosition(property.getStart(file)).line + 1}: raw ${method} queryKey`);
            }
          }
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return violations;
}

async function sourceFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const url = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directory);
    if (entry.isDirectory()) return sourceFiles(url);
    return /\.(?:ts|tsx)$/.test(entry.name) ? [url] : [];
  }));
  return nested.flat();
}

test("production query consumers use the central key factory", async () => {
  const roots = [
    new URL("../app/", import.meta.url),
    new URL("../src/", import.meta.url),
  ];
  const files = (await Promise.all(roots.map(sourceFiles))).flat().filter(
    (file) => !file.pathname.endsWith("/src/lib/query-keys.ts"),
  );
  const violations = [];
  for (const file of files) {
    const source = await fs.readFile(file, "utf8");
    violations.push(...findViolations(source, file.pathname));
    if (/queryKey\s*:|\.(?:getQueryData|setQueryData|invalidateQueries|refetchQueries|removeQueries|cancelQueries)\s*\(/.test(source)) {
      assert.match(source, /from "@\/lib\/query-keys"/);
    }
  }
  assert.deepEqual(violations, []);
});

test("handwritten polling timers are removed", async () => {
  const market = await fs.readFile(new URL("../src/lib/market.ts", import.meta.url), "utf8");
  const save = await fs.readFile(
    new URL("../src/components/watchlist-drawer/hooks/useWatchlistSave.ts", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(market, /while\s*\(|window\.setTimeout/);
  assert.doesNotMatch(save, /setInterval|clearInterval/);
});
```

- [ ] **Step 4: Add policy and polling pure-function tests**

Create `frontend/tests/polling.test.mjs` with this loader, followed by the assertions below:

```js
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadModule(path) {
  const source = await fs.readFile(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  const context = { exports, module: { exports }, JSON };
  vm.runInNewContext(compiled, context, { filename: path });
  return context.module.exports;
}

function normalize(value) {
  return JSON.parse(JSON.stringify(value));
}

test("query policies preserve current effective timing", async () => {
  const policy = await loadModule("../src/lib/query-policy.ts");
  assert.deepEqual(normalize(policy.queryDefaults), {
    staleTime: 60_000,
    gcTime: 300_000,
    retry: 3,
    refetchOnWindowFocus: false,
  });
  assert.deepEqual(normalize(policy.queryPolicy.marketData), { staleTime: 300_000, retry: 1 });
  assert.equal(policy.queryPolicy.evidenceStatus.refetchInterval, 5_000);
  assert.equal(policy.queryPolicy.briefingLatest.refetchInterval, 30_000);
  assert.equal(policy.queryPolicy.diagnosisRefreshJob.intervalMs, 1_000);
  assert.deepEqual(normalize(policy.queryPolicy.marketSnapshotRefresh), { intervalMs: 4_000, timeoutMs: 30_000 });
  assert.deepEqual(normalize(policy.queryPolicy.marketEvidenceRefresh), { intervalMs: 3_000, timeoutMs: 60_000 });
  assert.deepEqual(normalize(policy.queryPolicy.watchlistPreload), { intervalMs: 1_500, maxAttempts: 120, retry: false });
  assert.equal(policy.queryPolicy.pollingObserver.refetchIntervalInBackground, true);
});

test("polling predicates preserve completion and boundary behavior", async () => {
  const polling = await loadModule("../src/lib/polling.ts");
  assert.equal(polling.marketSnapshotFingerprint({ trade_date: "2026-07-17" }), '"2026-07-17"');
  assert.equal(polling.hasFingerprintChanged('"2026-07-17"', '"2026-07-17"'), false);
  assert.equal(polling.hasFingerprintChanged('"2026-07-17"', '"2026-07-18"'), true);
  assert.equal(polling.marketEvidenceFingerprint({ items: [{ id: 1 }] }), '[{"id":1}]');
  assert.equal(polling.marketEvidenceFingerprint({ groups: { policy: [{ id: 1 }] } }), '{"policy":[{"id":1}]}');
  for (const status of ["done", "partial", "failed", "missing"]) {
    assert.equal(polling.isWatchlistPreloadTerminal(status), true);
  }
  assert.equal(polling.isWatchlistPreloadTerminal("running"), false);
  assert.equal(polling.hasPollingTimedOut(1_000, 30_999, 30_000), false);
  assert.equal(polling.hasPollingTimedOut(1_000, 31_000, 30_000), true);
  assert.equal(polling.hasReachedMaxAttempts(119, 120), false);
  assert.equal(polling.hasReachedMaxAttempts(120, 120), true);
});
```

- [ ] **Step 5: Extend existing source contracts**

Add `hooks/useWatchlistPreloadPolling.ts` to `requiredFiles` in `watchlist-drawer-structure.test.mjs`. Change `watchlist-refresh.test.mjs` raw-array expectations to:

```js
assert.match(source, /queryKeys\.fund\.summaryForFund\(code\)/);
assert.match(source, /queryKeys\.fund\.diagnosisForFund\(code\)/);
assert.match(source, /queryKeys\.portfolio\.pnl\(\[code\]\)/);
assert.match(source, /queryKeys\.portfolio\.pnl\(\[\]\)/);
```

Change the portfolio query assertion to `queryKeys.portfolio.pnl([])`.

- [ ] **Step 6: Verify RED is specific**

Run:

```bash
cd frontend
node --test tests/query-keys.test.mjs tests/query-structure.test.mjs tests/polling.test.mjs tests/watchlist-drawer-structure.test.mjs tests/watchlist-refresh.test.mjs
```

Expected: failures only because the three lib modules and preload hook do not exist, raw query arrays/timers remain, and source contracts still target the old implementation. No syntax or VM-helper failures are allowed.

---

### Task 2: Implement key, policy and polling pure modules

**Files:**

- Create: `frontend/src/lib/query-keys.ts`
- Create: `frontend/src/lib/query-policy.ts`
- Create: `frontend/src/lib/polling.ts`
- Test: `frontend/tests/query-keys.test.mjs`
- Test: `frontend/tests/polling.test.mjs`

**Interfaces:**

- Produces: `queryKeys`, `queryDefaults`, `queryPolicy`, fingerprint and boundary predicates.
- Consumed by: every later task.

- [ ] **Step 1: Implement the exact query key factory**

Create `query-keys.ts` with the complete `queryKeys` object from design section 5. Use these signatures without transforming input arrays/objects:

```ts
export interface PortfolioPnlSeriesKeyParams {
  period: string;
  start: string;
  end: string;
  codes: string[];
}

export const queryKeys = {
  watchlist: {
    all: ["watchlist"] as const,
    transactions: (fundCode: string) => ["watchlistTransactions", fundCode] as const,
    investmentPlans: (fundCode: string) => ["investmentPlans", fundCode] as const,
    pendingBuys: (fundCode: string) => ["pendingBuys", fundCode] as const,
    preloadJob: (fundCode: string, jobId: string) => ["watchlistPreloadJob", fundCode, jobId] as const,
  },
  fund: {
    detail: (code: string) => ["fund", code] as const,
    navForFund: (code: string) => ["nav", code] as const,
    nav: (code: string, date: string) => ["nav", code, date] as const,
    navHistoryForFund: (code: string) => ["navHistory", code] as const,
    navHistory: (code: string, start: string | undefined) => ["navHistory", code, start] as const,
    metrics: (code: string) => ["metrics", code] as const,
    summaryForFund: (code: string) => ["fundSummary", code] as const,
    summary: (code: string, period: string, start: string | undefined) => ["fundSummary", code, period, start] as const,
    diagnosisForFund: (code: string) => ["fundDiagnosis", code] as const,
    diagnosis: (code: string, period: string) => ["fundDiagnosis", code, period] as const,
    diagnosisRefreshJob: (code: string, jobId: string | null) => ["fundDiagnosisRefreshJob", code, jobId] as const,
  },
  portfolio: {
    pnl: (codes: string[]) => ["portfolioPnl", codes] as const,
    pnlSeries: (params: PortfolioPnlSeriesKeyParams) => ["portfolioPnlSeries", params] as const,
  },
  market: {
    all: ["market"] as const,
    latest: ["market", "latest"] as const,
    snapshots: ["market", "snapshot"] as const,
    snapshot: (date: string, type: string) => ["market", "snapshot", date, type] as const,
    evidence: {
      all: ["market", "evidence"] as const,
      list: (date: string, category: string, limit: number) => ["market", "evidence", date, category, limit] as const,
      refreshStatuses: ["market", "evidence", "refresh-status"] as const,
      refreshStatus: (briefType: string) => ["market", "evidence", "refresh-status", briefType] as const,
    },
    refreshPolling: {
      snapshot: (date: string | undefined) => ["marketRefreshPolling", "snapshot", date ?? ""] as const,
      evidence: (date: string) => ["marketRefreshPolling", "evidence", date] as const,
    },
  },
  briefing: {
    all: ["briefing"] as const,
    latest: ["briefing", "latest"] as const,
    list: (limit: number) => ["briefing", "list", limit] as const,
    evidence: (date: string) => ["briefing", "evidence", date] as const,
  },
  compare: (codes: string[]) => ["compare", codes] as const,
  langgraph: { health: ["langgraph", "health"] as const },
} as const;
```

- [ ] **Step 2: Implement explicit policy objects**

Create `query-policy.ts`:

```ts
export const queryDefaults = {
  staleTime: 60_000,
  gcTime: 5 * 60_000,
  retry: 3,
  refetchOnWindowFocus: false,
} as const;

export const queryPolicy = {
  marketData: { staleTime: 5 * 60_000, retry: 1 },
  evidenceStatus: { staleTime: 5_000, refetchInterval: 5_000, retry: 1 },
  briefingLatest: { refetchInterval: 30_000 },
  diagnosisRefreshJob: { intervalMs: 1_000 },
  langgraphHealth: { retry: false },
  pollingObserver: {
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchIntervalInBackground: true,
  },
  marketSnapshotRefresh: { intervalMs: 4_000, timeoutMs: 30_000 },
  marketEvidenceRefresh: { intervalMs: 3_000, timeoutMs: 60_000 },
  watchlistPreload: { intervalMs: 1_500, maxAttempts: 120, retry: false },
} as const;
```

- [ ] **Step 3: Implement pure polling predicates**

Create `polling.ts`:

```ts
import type { MarketEvidenceResponse, WatchlistPreloadStatus } from "@/types/api";

interface SnapshotLike { trade_date?: string | null }

export function marketSnapshotFingerprint(snapshot: SnapshotLike | null | undefined): string {
  return JSON.stringify(snapshot?.trade_date ?? "");
}

export function marketEvidenceFingerprint(
  response: Pick<MarketEvidenceResponse, "items" | "groups"> | null | undefined,
): string {
  return JSON.stringify(response?.items ?? response?.groups ?? null);
}

export function hasFingerprintChanged(baseline: string, latest: string): boolean {
  return latest !== baseline;
}

export function isWatchlistPreloadTerminal(status: WatchlistPreloadStatus): boolean {
  return status === "done" || status === "partial" || status === "failed" || status === "missing";
}

export function hasPollingTimedOut(startedAt: number, now: number, timeoutMs: number): boolean {
  return now - startedAt >= timeoutMs;
}

export function hasReachedMaxAttempts(attempts: number, maxAttempts: number): boolean {
  return attempts >= maxAttempts;
}
```

- [ ] **Step 4: Verify the pure modules GREEN**

Run:

```bash
cd frontend
node --test tests/query-keys.test.mjs tests/polling.test.mjs
npx tsc --noEmit
```

Expected: query-key and polling tests pass. TypeScript may still pass because no consumer has switched; any error in the three new modules must be fixed before Task 3.

---

### Task 3: Hard-cut every frontend query/cache consumer

**Files:**

- Modify: every production consumer in the File Map except Market polling and Watchlist preload internals handled in Tasks 4–5.
- Modify: `frontend/app/providers.tsx`
- Test: `frontend/tests/query-structure.test.mjs`
- Test: `frontend/tests/watchlist-refresh.test.mjs`

**Interfaces:**

- Consumes: `queryKeys`, `queryDefaults`, query policy fragments.
- Produces: no production raw key arrays.

- [ ] **Step 1: Switch the Query Client defaults**

In `app/providers.tsx`, import `queryDefaults` and replace the inline query defaults:

```ts
import { queryDefaults } from "@/lib/query-policy";

const [qc] = useState(
  () => new QueryClient({ defaultOptions: { queries: queryDefaults } }),
);
```

- [ ] **Step 2: Apply the exact key replacement table**

Add `import { queryKeys } from "@/lib/query-keys";` to every key consumer and perform these replacements without changing query functions, enabled conditions, mutation order or JSX:

| Existing tuple | Replacement |
|---|---|
| `["watchlist"]` | `queryKeys.watchlist.all` |
| `["watchlistTransactions", code]` | `queryKeys.watchlist.transactions(code)` |
| `["investmentPlans", code]` | `queryKeys.watchlist.investmentPlans(code)` |
| `["pendingBuys", code]` | `queryKeys.watchlist.pendingBuys(code)` |
| `["fund", code]` | `queryKeys.fund.detail(code)` |
| `["nav", code]` | `queryKeys.fund.navForFund(code)` |
| `["nav", code, date]` | `queryKeys.fund.nav(code, date)` |
| `["navHistory", code]` | `queryKeys.fund.navHistoryForFund(code)` |
| `["navHistory", code, start]` | `queryKeys.fund.navHistory(code, start)` |
| `["metrics", code]` | `queryKeys.fund.metrics(code)` |
| `["fundSummary", code]` | `queryKeys.fund.summaryForFund(code)` |
| `["fundSummary", code, period, start]` | `queryKeys.fund.summary(code, period, start)` |
| `["fundDiagnosis", code]` | `queryKeys.fund.diagnosisForFund(code)` |
| `["fundDiagnosis", code, period]` | `queryKeys.fund.diagnosis(code, period)` |
| `["fundDiagnosisRefreshJob", code, jobId]` | `queryKeys.fund.diagnosisRefreshJob(code, jobId)` |
| `["portfolioPnl", codes]` | `queryKeys.portfolio.pnl(codes)` |
| `["portfolioPnl", [code]]` | `queryKeys.portfolio.pnl([code])` |
| `["portfolioPnl", []]` | `queryKeys.portfolio.pnl([])` |
| `["portfolioPnlSeries", params]` | `queryKeys.portfolio.pnlSeries(params)` |
| `["market", "latest"]` | `queryKeys.market.latest` |
| `["market", "snapshot", date, type]` | `queryKeys.market.snapshot(date, type)` |
| `["market", "evidence", date, category, limit]` | `queryKeys.market.evidence.list(date, category, limit)` |
| `["market", "evidence", "refresh-status", briefType]` | `queryKeys.market.evidence.refreshStatus(briefType)` |
| `["briefing"]` | `queryKeys.briefing.all` |
| `["briefing", "latest"]` | `queryKeys.briefing.latest` |
| `["briefing", "list", limit]` | `queryKeys.briefing.list(limit)` |
| `["briefing", "evidence", date]` | `queryKeys.briefing.evidence(date)` |
| `["compare", codes]` | `queryKeys.compare(codes)` |
| `["langgraph", "health"]` | `queryKeys.langgraph.health` |

For prefix calls, use the explicit prefix members (`market.all`, `market.snapshots`, `market.evidence.all`, `market.evidence.refreshStatuses`) rather than slicing a detail key.

- [ ] **Step 3: Switch existing local policies without changing values**

Use:

```ts
...queryPolicy.marketData
...queryPolicy.evidenceStatus
refetchInterval: queryPolicy.briefingLatest.refetchInterval
refetchInterval: refreshJobId ? queryPolicy.diagnosisRefreshJob.intervalMs : false
retry: queryPolicy.langgraphHealth.retry
```

Only replace existing values; do not add a local policy to queries that currently inherit global defaults.

- [ ] **Step 4: Update Market VM test dependencies**

`market-lib.test.mjs` loads `market.ts` outside Next resolution. Extend its `require` stub so type-independent pure Market tests can load after imports are added:

```js
if (specifier === "@/lib/query-keys") {
  return { queryKeys: { market: {} } };
}
if (specifier === "@/lib/query-policy") {
  return { queryPolicy: {} };
}
if (specifier === "@/lib/polling") {
  return {
    marketEvidenceFingerprint: () => "",
    marketSnapshotFingerprint: () => "",
    hasFingerprintChanged: () => false,
    hasPollingTimedOut: () => false,
  };
}
```

If `market.ts` evaluates nested key/policy properties during module load, provide the exact minimal nested functions/objects required; do not copy production tuple arrays into the test.

- [ ] **Step 5: Verify the key hard cut GREEN**

Run:

```bash
cd frontend
node --test tests/query-keys.test.mjs tests/query-structure.test.mjs tests/watchlist-refresh.test.mjs tests/market-lib.test.mjs
npx tsc --noEmit
```

Expected: key/AST/source/Market tests and TypeScript pass except the two timer assertions may remain RED until Tasks 4–5. No raw query array violation may remain.

---

### Task 4: Replace Market handwritten loops with query observers

**Files:**

- Modify: `frontend/src/lib/market.ts`
- Test: `frontend/tests/query-structure.test.mjs`
- Test: `frontend/tests/market-lib.test.mjs`

**Interfaces:**

- Preserves: `useRefreshMarket(date?)` and `useRefreshEvidence(date)` mutation-like return values.
- Consumes: Market resource keys, internal polling keys, policies and pure fingerprints.

- [ ] **Step 1: Add Market polling source assertions**

In `market-lib.test.mjs`, read the source separately and assert:

```js
test("market refresh uses React Query polling observers", async () => {
  const source = await fs.readFile(new URL("../src/lib/market.ts", import.meta.url), "utf8");
  assert.match(source, /queryKeys\.market\.refreshPolling\.snapshot/);
  assert.match(source, /queryKeys\.market\.refreshPolling\.evidence/);
  assert.match(source, /refetchInterval/);
  assert.match(source, /mutation\.isPending \|\| polling\.active/);
  assert.doesNotMatch(source, /while\s*\(/);
  assert.doesNotMatch(source, /window\.setTimeout/);
});
```

Run this one test and confirm it fails against the loop implementation.

- [ ] **Step 2: Implement a local typed polling state**

Inside `market.ts`, define only the Market-specific state/result types:

```ts
interface RefreshPollingState {
  active: boolean;
  startedAt: number;
  baseline: string;
}

interface RefreshPollingTick {
  startedAt: number;
  fingerprint: string;
}

const idlePolling: RefreshPollingState = {
  active: false,
  startedAt: 0,
  baseline: "",
};
```

Do not export or generalize these types.

- [ ] **Step 3: Replace `useRefreshMarket` loop**

Use `useEffect`/`useState` plus an always-declared polling query. The observer must be disabled while idle, use `queryPolicy.pollingObserver`, schedule the interval only while active, and make its immediate enabled fetch a no-op fingerprint until one interval has elapsed so the first resource refetch still occurs after 4 seconds.

Implement the snapshot observer and mutation with this complete state transition:

```ts
const [polling, setPolling] = useState<RefreshPollingState>(idlePolling);
const resourceKey = date
  ? queryKeys.market.snapshot(date, "post_market")
  : queryKeys.market.snapshots;

const pollQuery = useQuery<RefreshPollingTick>({
  queryKey: queryKeys.market.refreshPolling.snapshot(date),
  queryFn: async () => {
    if (Date.now() - polling.startedAt < queryPolicy.marketSnapshotRefresh.intervalMs) {
      return { startedAt: polling.startedAt, fingerprint: polling.baseline };
    }
    try {
      await qc.refetchQueries({ queryKey: resourceKey });
    } catch {
      // Preserve the current single-refetch failure tolerance.
    }
    const latest = qc.getQueryData<MarketSnapshot>(resourceKey);
    return {
      startedAt: polling.startedAt,
      fingerprint: marketSnapshotFingerprint(latest),
    };
  },
  enabled: polling.active,
  refetchInterval: polling.active
    ? queryPolicy.marketSnapshotRefresh.intervalMs
    : false,
  ...queryPolicy.pollingObserver,
});

useEffect(() => {
  const tick = pollQuery.data;
  if (!polling.active || !tick || tick.startedAt !== polling.startedAt) return;
  const changed = hasFingerprintChanged(polling.baseline, tick.fingerprint);
  const timedOut = hasPollingTimedOut(
    polling.startedAt,
    Date.now(),
    queryPolicy.marketSnapshotRefresh.timeoutMs,
  );
  if (!changed && !timedOut) return;
  setPolling(idlePolling);
  void qc.invalidateQueries({ queryKey: queryKeys.market.all });
}, [pollQuery.data, polling, qc]);

const mutation = useMutation({
  mutationFn: () =>
    fetch(`/api/market/refresh${date ? `?date=${encodeURIComponent(date)}` : ""}`, {
      method: "POST",
      headers: { "X-Local-Trigger": "1" },
    }).then((response) => {
      if (!response.ok) throw new Error("failed");
      return response.json();
    }),
  onSuccess: () => {
    const startedAt = Date.now();
    setPolling({
      active: true,
      startedAt,
      baseline: marketSnapshotFingerprint(
        qc.getQueryData<MarketSnapshot>(resourceKey),
      ),
    });
  },
});

return {
  ...mutation,
  isPending: mutation.isPending || polling.active,
};
```

Do not add a toast or change the POST request.

- [ ] **Step 4: Replace `useRefreshEvidence` loop**

Use these exact resource/control keys:

```ts
const resourceKey = queryKeys.market.evidence.list(date, "", 20);
const statusKey = queryKeys.market.evidence.refreshStatus("post_market");
const controlKey = queryKeys.market.refreshPolling.evidence(date);
```

Implement the evidence transitions in full:

```ts
const [polling, setPolling] = useState<RefreshPollingState>(idlePolling);
const resourceKey = queryKeys.market.evidence.list(date, "", 20);
const statusKey = queryKeys.market.evidence.refreshStatus("post_market");

const pollQuery = useQuery<RefreshPollingTick>({
  queryKey: controlKey,
  queryFn: async () => {
    if (Date.now() - polling.startedAt < queryPolicy.marketEvidenceRefresh.intervalMs) {
      return { startedAt: polling.startedAt, fingerprint: polling.baseline };
    }
    try {
      await qc.refetchQueries({ queryKey: resourceKey });
      await qc.refetchQueries({ queryKey: statusKey });
    } catch {
      // Preserve the current single-refetch failure tolerance.
    }
    return {
      startedAt: polling.startedAt,
      fingerprint: marketEvidenceFingerprint(
        qc.getQueryData<MarketEvidenceResponse>(resourceKey),
      ),
    };
  },
  enabled: polling.active,
  refetchInterval: polling.active
    ? queryPolicy.marketEvidenceRefresh.intervalMs
    : false,
  ...queryPolicy.pollingObserver,
});

useEffect(() => {
  const tick = pollQuery.data;
  if (!polling.active || !tick || tick.startedAt !== polling.startedAt) return;
  const changed = hasFingerprintChanged(polling.baseline, tick.fingerprint);
  const timedOut = hasPollingTimedOut(
    polling.startedAt,
    Date.now(),
    queryPolicy.marketEvidenceRefresh.timeoutMs,
  );
  if (!changed && !timedOut) return;
  setPolling(idlePolling);
  void qc.invalidateQueries({ queryKey: queryKeys.market.evidence.all });
  void qc.invalidateQueries({
    queryKey: queryKeys.market.evidence.refreshStatuses,
  });
}, [pollQuery.data, polling, qc]);

const mutation = useMutation({
  mutationFn: () =>
    fetch("/api/market/evidence/refresh?brief_type=post_market", {
      method: "POST",
      headers: { "X-Local-Trigger": "1" },
    }).then((response) => {
      if (!response.ok) throw new Error("failed");
      return response.json();
    }),
  onSuccess: () => {
    const startedAt = Date.now();
    setPolling({
      active: true,
      startedAt,
      baseline: marketEvidenceFingerprint(
        qc.getQueryData<MarketEvidenceResponse>(resourceKey),
      ),
    });
  },
});

return {
  ...mutation,
  isPending: mutation.isPending || polling.active,
};
```

- [ ] **Step 5: Verify Market GREEN**

Run:

```bash
cd frontend
node --test tests/market-lib.test.mjs tests/query-structure.test.mjs tests/polling.test.mjs
npx tsc --noEmit
```

Expected: Market source/pure tests and TypeScript pass; the Watchlist interval assertion is the only allowed remaining structure failure.

---

### Task 5: Replace Watchlist preload interval with a domain query hook

**Files:**

- Create: `frontend/src/components/watchlist-drawer/hooks/useWatchlistPreloadPolling.ts`
- Modify: `frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts`
- Modify: `frontend/tests/watchlist-drawer-structure.test.mjs`
- Test: `frontend/tests/query-structure.test.mjs`
- Test: `frontend/tests/polling.test.mjs`

**Interfaces:**

- Produces: `useWatchlistPreloadPolling(): { startPreloadPolling(job): void }`.
- Consumed by: `useWatchlistSave` only.

- [ ] **Step 1: Add Watchlist polling source assertions**

Extend `watchlist-drawer-structure.test.mjs`:

```js
test("watchlist preload polling is owned by a React Query hook", async () => {
  const polling = await read("hooks/useWatchlistPreloadPolling.ts");
  const save = await read("hooks/useWatchlistSave.ts");
  assert.match(polling, /useQuery/);
  assert.match(polling, /queryKeys\.watchlist\.preloadJob/);
  assert.match(polling, /queryPolicy\.watchlistPreload/);
  assert.match(save, /useWatchlistPreloadPolling/);
  assert.doesNotMatch(save, /setInterval|clearInterval/);
});
```

Run the test and confirm it fails because the hook does not exist.

- [ ] **Step 2: Implement preload polling state and query**

Create the hook with these local types:

```ts
interface PreloadPollingState {
  job: WatchlistPreloadJob;
  startedAt: number;
}

type PreloadPollingTick =
  | { kind: "armed"; startedAt: number }
  | {
      kind: "snapshot";
      startedAt: number;
      snapshot: WatchlistPreloadJob;
      attempts: number;
    };
```

The hook owns `polling`, an `attemptsRef`, QueryClient and toast. Its always-declared query uses the real job key while active and `queryKeys.watchlist.preloadJob("", "")` while idle. On the immediate enabled fetch, return `{ kind: "armed" }` until 1.5 seconds has elapsed. On each real tick increment attempts and call the existing API. `refetchIntervalInBackground=true` preserves the current bare interval while the tab is backgrounded:

```ts
const query = useQuery<PreloadPollingTick>({
  queryKey: polling
    ? queryKeys.watchlist.preloadJob(polling.job.fund_code, polling.job.job_id)
    : queryKeys.watchlist.preloadJob("", ""),
  queryFn: async () => {
    if (!polling) return { kind: "armed", startedAt: 0 };
    if (
      attemptsRef.current === 0 &&
      Date.now() - polling.startedAt < queryPolicy.watchlistPreload.intervalMs
    ) {
      return { kind: "armed", startedAt: polling.startedAt };
    }
    attemptsRef.current += 1;
    return {
      kind: "snapshot",
      startedAt: polling.startedAt,
      snapshot: await api.watchlistPreloadJob(
        polling.job.fund_code,
        polling.job.job_id,
      ),
      attempts: attemptsRef.current,
    };
  },
  enabled: polling !== null,
  ...queryPolicy.pollingObserver,
  retry: queryPolicy.watchlistPreload.retry,
  refetchInterval: polling
    ? queryPolicy.watchlistPreload.intervalMs
    : false,
});
```

- [ ] **Step 3: Implement terminal/error effects exactly**

Move the existing fund cache invalidations into this hook using `queryKeys`. Define it as a stable callback with the exact existing set:

```ts
const invalidateFundCaches = useCallback((code: string) => {
  void qc.invalidateQueries({ queryKey: queryKeys.watchlist.all });
  void qc.invalidateQueries({ queryKey: queryKeys.fund.summaryForFund(code) });
  void qc.invalidateQueries({ queryKey: queryKeys.fund.detail(code) });
  void qc.invalidateQueries({ queryKey: queryKeys.fund.navForFund(code) });
  void qc.invalidateQueries({ queryKey: queryKeys.fund.navHistoryForFund(code) });
  void qc.invalidateQueries({ queryKey: queryKeys.fund.metrics(code) });
  void qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([code]) });
  void qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([]) });
  void qc.invalidateQueries({ queryKey: queryKeys.fund.diagnosisForFund(code) });
}, [qc]);
```

The data effect uses this complete guard and transition:

```ts
useEffect(() => {
  const tick = query.data;
  if (
    !polling ||
    !tick ||
    tick.startedAt !== polling.startedAt ||
    tick.kind !== "snapshot"
  ) return;
  const { snapshot, attempts } = tick;
  const terminal = isWatchlistPreloadTerminal(snapshot.status);
  const exhausted = hasReachedMaxAttempts(
    attempts,
    queryPolicy.watchlistPreload.maxAttempts,
  );
  if (!terminal && !exhausted) return;
  setPolling(null);
  invalidateFundCaches(snapshot.fund_code);
  if (snapshot.status === "done") {
    toast.push(`${snapshot.fund_code} 基金数据已同步`, "success");
  } else if (snapshot.status === "partial") {
    toast.push(`${snapshot.fund_code} 基金数据部分同步完成，仍有字段缺失`, "info");
  } else if (snapshot.status === "failed") {
    toast.push(`${snapshot.fund_code} 自动同步失败，可稍后刷新`, "error");
  }
}, [invalidateFundCaches, polling, query.data, toast]);
```

The separate error effect is:

```ts
useEffect(() => {
  if (!polling || !query.error) return;
  const code = polling.job.fund_code;
  setPolling(null);
  invalidateFundCaches(code);
  toast.push(`同步状态查询失败：${String(query.error)}`, "error");
}, [invalidateFundCaches, polling, query.error, toast]);
```

Do not toast for `missing` or exhausted non-terminal status. Clear stale cache state and establish a new polling epoch when starting:

```ts
const startPreloadPolling = useCallback((job: WatchlistPreloadJob) => {
  qc.removeQueries({
    queryKey: queryKeys.watchlist.preloadJob(job.fund_code, job.job_id),
    exact: true,
  });
  attemptsRef.current = 0;
  setPolling({ job, startedAt: Date.now() });
}, [qc]);
```

React Query observer teardown on unmount provides the approved lifecycle cleanup.

- [ ] **Step 4: Simplify `useWatchlistSave`**

At hook initialization:

```ts
const { startPreloadPolling } = useWatchlistPreloadPolling();
```

Delete its local `invalidateFundCaches` and `startPreloadPolling` timer functions. Keep the existing save flow unchanged:

```ts
if (preloadJob) {
  toast.push(`${fundCode} 正在后台同步基金数据`, "info");
  startPreloadPolling(preloadJob);
}
onClose();
```

- [ ] **Step 5: Verify all focused Phase 3A tests GREEN**

Run:

```bash
cd frontend
node --test tests/query-keys.test.mjs tests/query-structure.test.mjs tests/polling.test.mjs tests/market-lib.test.mjs tests/watchlist-drawer-structure.test.mjs tests/watchlist-refresh.test.mjs
npx tsc --noEmit
```

Expected: all focused tests and TypeScript pass; no raw key or handwritten polling violation remains.

---

### Task 6: Full verification, review and atomic implementation commit

**Files:**

- Review: every file in the File Map.
- Stage: frontend Phase 3A production/tests only.
- Preserve unstaged: the three backend user files.

**Interfaces:**

- Consumes: completed Tasks 1–5.
- Produces: one reviewed, verified implementation commit.

- [ ] **Step 1: Run full frontend verification sequentially**

Do not run `tsc` concurrently with `next build`, because both read/write `.next/types`.

```bash
cd frontend
npm test
npx tsc --noEmit
npm run build
```

Expected: baseline 94 tests plus new tests all pass with 0 failures; TypeScript exits 0; Next compiles and generates 11 pages.

- [ ] **Step 2: Run hard-cut audits**

```bash
git diff --check
rg -n 'queryKey:\s*\[' frontend/app frontend/src --glob '*.{ts,tsx}' --glob '!src/lib/query-keys.ts'
rg -n 'invalidateQueries\(\{\s*queryKey:\s*\[|refetchQueries\(\{\s*queryKey:\s*\[|getQueryData[^\n]*\(\[' frontend/app frontend/src --glob '*.{ts,tsx}'
rg -n 'while\s*\(|setTimeout' frontend/src/lib/market.ts
rg -n 'setInterval|clearInterval' frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts
git status --short
```

Expected: `git diff --check` exits 0; all four `rg` commands have no matches; status contains only the File Map plus the three unrelated unstaged backend modifications.

- [ ] **Step 3: Compare behavior against the base implementation**

Use `git show 19dff0a:<path>` for the base files and verify line-by-line:

- all old key tuple values and prefix invalidations;
- Query Client and local stale/retry/refetch values;
- Market POST URLs/headers, baseline fingerprints, first polling delay, tick intervals, timeout boundaries, single-failure continuation and broad invalidation;
- composite Market `isPending` used by all existing buttons;
- Watchlist save/toast/close order, first polling delay, 120-attempt boundary, four terminal statuses, error-stop behavior, invalidation set and toast text/tone;
- drawer-close continuation and route-unmount cleanup;
- no Phase 3B or UI change.

- [ ] **Step 4: Request independent code review**

Use `superpowers:requesting-code-review`. Give the reviewer design
`docs/superpowers/specs/2026-07-17-react-query-governance-design.md`, this plan, base `19dff0a`, and the uncommitted frontend diff. The review is read-only and must ignore the three backend files.

Fix all Critical and Important findings. Evaluate Minor findings against the behavior-compatible scope. After any change, rerun Step 1 and Step 2 sequentially.

- [ ] **Step 5: Stage only the approved frontend scope**

```bash
git add frontend/app/providers.tsx frontend/app/briefing/page.tsx \
  frontend/app/compare/page.tsx 'frontend/app/funds/[code]/page.tsx' \
  frontend/app/portfolio/page.tsx frontend/app/watchlist/page.tsx \
  frontend/src/components/HoldingCard.tsx frontend/src/components/MarketIndexCard.tsx \
  frontend/src/components/NavChart.tsx frontend/src/components/WatchlistTable.tsx \
  frontend/src/components/qa/QaWorkbench.tsx \
  frontend/src/components/watchlist-drawer/hooks \
  frontend/src/lib/market.ts frontend/src/lib/query-keys.ts \
  frontend/src/lib/query-policy.ts frontend/src/lib/polling.ts \
  frontend/tests/market-lib.test.mjs frontend/tests/watchlist-drawer-structure.test.mjs \
  frontend/tests/watchlist-refresh.test.mjs frontend/tests/query-keys.test.mjs \
  frontend/tests/query-structure.test.mjs frontend/tests/polling.test.mjs
git diff --cached --check
git status --short
```

Expected: all frontend Phase 3A files are staged; `backend/db/session.py`, `backend/db/types.py`, and `backend/integrations/market_evidence.py` remain unstaged (` M`, not `M `).

- [ ] **Step 6: Create the unique implementation commit**

```bash
git commit -m "refactor: hard cut frontend query governance"
```

Expected: one implementation commit after the design and plan commits. Do not push, merge, create a PR, or clean the current `refactore` branch.
