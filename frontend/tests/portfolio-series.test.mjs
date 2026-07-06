import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadModule(relativePath) {
  const source = await fs.readFile(new URL(relativePath, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const exports = {};
  const context = { exports, module: { exports }, URL, Date };
  vm.runInNewContext(compiled, context, { filename: relativePath });
  return context.module.exports;
}

test("periodStartForEnd subtracts the right number of days", async () => {
  const { periodStartForEnd } = await loadModule("../src/lib/portfolio-series.ts");
  assert.equal(periodStartForEnd("1m", "2026-07-06"), "2026-06-06");
  assert.equal(periodStartForEnd("3m", "2026-07-06"), "2026-04-07");
  assert.equal(periodStartForEnd("1y", "2026-07-06"), "2025-07-06");
});

test("periodStartForEnd returns empty string for 'all'", async () => {
  const { periodStartForEnd } = await loadModule("../src/lib/portfolio-series.ts");
  assert.equal(periodStartForEnd("all", "2026-07-06"), "");
});

test("periodLabel maps 'all' to 全部 and uppercases others", async () => {
  const { periodLabel } = await loadModule("../src/lib/portfolio-series.ts");
  assert.equal(periodLabel("all"), "全部");
  assert.equal(periodLabel("1y"), "1Y");
});

test("compactPnlSummary flattens summary fields", async () => {
  const { compactPnlSummary } = await loadModule("../src/lib/portfolio-series.ts");
  const out = compactPnlSummary({
    start: "2026-01-01",
    end: "2026-07-06",
    as_of: "2026-07-06",
    source: "akshare",
    dates: [],
    per_fund: [],
    summary: {
      invested: 5000,
      market_value: 5450,
      pnl_abs: 450,
      pnl_pct: 0.09,
      daily_points: 180,
    },
    uncovered_funds: [],
  });
  assert.equal(out.invested, 5000);
  assert.equal(out.market, 5450);
  assert.equal(out.pnl, 450);
  assert.equal(out.pnlPct, 0.09);
});
