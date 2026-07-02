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
  const context = { exports, module: { exports } };
  vm.runInNewContext(compiled, context, { filename: relativePath });
  return context.module.exports;
}

function normalize(value) {
  return JSON.parse(JSON.stringify(value));
}

const navHistory = {
  fund_code: "110011",
  count: 4,
  source: "akshare",
  as_of: "2026-07-01",
  navs: [
    { nav_date: "2026-06-27", accumulated_nav: 1.0, daily_return: null },
    { nav_date: "2026-06-28", accumulated_nav: 1.01, daily_return: 0.01 },
    { nav_date: "2026-06-30", accumulated_nav: 1.005, daily_return: -0.004950495 },
    { nav_date: "2026-07-01", accumulated_nav: 1.02, daily_return: 0.014925373 },
  ],
};

test("toNavChartPoints preserves daily return for tooltip display", async () => {
  const { toNavChartPoints } = await loadModule("../src/lib/nav-daily-return.ts");

  assert.deepEqual(normalize(toNavChartPoints(navHistory)), [
    { date: "2026-06-27", nav: 1.0, dailyReturn: null },
    { date: "2026-06-28", nav: 1.01, dailyReturn: 0.01 },
    { date: "2026-06-30", nav: 1.005, dailyReturn: -0.004950495 },
    { date: "2026-07-01", nav: 1.02, dailyReturn: 0.014925373 },
  ]);
});

test("recentDailyReturnRows returns latest dated rows in reverse chronological order", async () => {
  const { recentDailyReturnRows } = await loadModule("../src/lib/nav-daily-return.ts");

  assert.deepEqual(normalize(recentDailyReturnRows(navHistory, 3)), [
    { date: "2026-07-01", nav: 1.02, dailyReturn: 0.014925373 },
    { date: "2026-06-30", nav: 1.005, dailyReturn: -0.004950495 },
    { date: "2026-06-28", nav: 1.01, dailyReturn: 0.01 },
  ]);
});

test("periodDailyReturnRows returns all dated rows in reverse chronological order", async () => {
  const { periodDailyReturnRows } = await loadModule("../src/lib/nav-daily-return.ts");

  assert.deepEqual(normalize(periodDailyReturnRows(navHistory)), [
    { date: "2026-07-01", nav: 1.02, dailyReturn: 0.014925373 },
    { date: "2026-06-30", nav: 1.005, dailyReturn: -0.004950495 },
    { date: "2026-06-28", nav: 1.01, dailyReturn: 0.01 },
    { date: "2026-06-27", nav: 1.0, dailyReturn: null },
  ]);
});

test("periodDailyReturnRows returns empty array for missing or empty history", async () => {
  const { periodDailyReturnRows } = await loadModule("../src/lib/nav-daily-return.ts");

  assert.deepEqual(normalize(periodDailyReturnRows(null)), []);
  assert.deepEqual(normalize(periodDailyReturnRows(undefined)), []);
  assert.deepEqual(normalize(periodDailyReturnRows({ navs: [] })), []);
});

test("periodDailyReturnRows filters out entries without a date", async () => {
  const { periodDailyReturnRows } = await loadModule("../src/lib/nav-daily-return.ts");

  const history = {
    navs: [
      { nav_date: "2026-07-01", accumulated_nav: 1.02, daily_return: 0.01 },
      { nav_date: "", accumulated_nav: 1.01, daily_return: null },
      { nav_date: "2026-06-30", accumulated_nav: 1.005, daily_return: -0.005 },
    ],
  };

  const rows = periodDailyReturnRows(history);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].date, "2026-07-01");
  assert.equal(rows[1].date, "2026-06-30");
});
