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
