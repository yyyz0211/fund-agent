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
  return prefix.every(
    (part, index) => JSON.stringify(part) === JSON.stringify(value[index]),
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
  assert.deepEqual(
    normalize(keys.portfolio.pnlSeries({ period: "1m", start: "2026-06-17", end: "2026-07-17", codes: ["110011"] })),
    ["portfolioPnlSeries", { period: "1m", start: "2026-06-17", end: "2026-07-17", codes: ["110011"] }],
  );
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
