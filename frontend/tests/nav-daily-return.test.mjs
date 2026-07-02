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

// ── summarizePeriodReturns ──────────────────────────────────────────────────

test("summarizePeriodReturns empty rows", async () => {
  const { summarizePeriodReturns } = await loadModule("../src/lib/nav-daily-return.ts");

  const s = summarizePeriodReturns([]);
  assert.equal(s.rowsCount, 0);
  assert.equal(s.upCount, 0);
  assert.equal(s.downCount, 0);
  assert.equal(s.flatCount, 0);
  assert.equal(s.bestDay, null);
  assert.equal(s.worstDay, null);
  assert.equal(s.cumulativeReturn, null);
  assert.equal(s.navChange, null);
  assert.equal(s.currentStreak, null);
});

test("summarizePeriodReturns counts up/down/flat", async () => {
  const { summarizePeriodReturns, toNavChartPoints } = await loadModule("../src/lib/nav-daily-return.ts");

  const history = {
    navs: [
      { nav_date: "2026-07-01", accumulated_nav: 1.03, daily_return: 0.02 },   // up
      { nav_date: "2026-06-30", accumulated_nav: 1.01, daily_return: -0.02 },  // down
      { nav_date: "2026-06-28", accumulated_nav: 1.01, daily_return: null },   // flat
    ],
  };
  const rows = toNavChartPoints(history).filter((p) => p.date);

  const s = summarizePeriodReturns(rows);
  assert.equal(s.upCount, 1);
  assert.equal(s.downCount, 1);
  assert.equal(s.flatCount, 1);
});

test("summarizePeriodReturns bestDay and worstDay", async () => {
  const { summarizePeriodReturns, toNavChartPoints } = await loadModule("../src/lib/nav-daily-return.ts");

  const history = {
    navs: [
      { nav_date: "2026-07-01", accumulated_nav: 1.04, daily_return: 0.03 },
      { nav_date: "2026-06-30", accumulated_nav: 1.01, daily_return: -0.02 },
      { nav_date: "2026-06-28", accumulated_nav: 1.00, daily_return: 0.01 },
    ],
  };
  const rows = toNavChartPoints(history).filter((p) => p.date);

  const s = summarizePeriodReturns(rows);
  assert.equal(s.bestDay.date, "2026-07-01");
  assert.equal(s.worstDay.date, "2026-06-30");
});

test("summarizePeriodReturns cumulativeReturn matches compound formula", async () => {
  const { summarizePeriodReturns, toNavChartPoints } = await loadModule("../src/lib/nav-daily-return.ts");

  // two days of exactly +1%: (1.01 * 1.01) - 1 ≈ 0.0201
  const history = {
    navs: [
      { nav_date: "2026-07-02", accumulated_nav: 1.0201, daily_return: 0.01 },
      { nav_date: "2026-07-01", accumulated_nav: 1.01, daily_return: 0.01 },
    ],
  };
  const rows = toNavChartPoints(history).filter((p) => p.date);

  const s = summarizePeriodReturns(rows);
  assert(Math.abs(s.cumulativeReturn - 0.0201) < 0.0001);
  assert(Math.abs(s.navChange - (1.0201 - 1.01) / 1.01) < 0.0001);
});

test("summarizePeriodReturns currentStreak up", async () => {
  const { summarizePeriodReturns, toNavChartPoints } = await loadModule("../src/lib/nav-daily-return.ts");

  // rows are newest-first: 2026-07-01 up, 2026-06-30 up, 2026-06-28 down
  const history = {
    navs: [
      { nav_date: "2026-07-01", accumulated_nav: 1.03, daily_return: 0.01 },
      { nav_date: "2026-06-30", accumulated_nav: 1.02, daily_return: 0.01 },
      { nav_date: "2026-06-28", accumulated_nav: 1.01, daily_return: -0.01 },
    ],
  };
  const rows = toNavChartPoints(history).filter((p) => p.date);

  const s = summarizePeriodReturns(rows);
  assert.equal(s.currentStreak.kind, "up");
  assert.equal(s.currentStreak.length, 2);
});

test("summarizePeriodReturns currentStreak down", async () => {
  const { summarizePeriodReturns, toNavChartPoints } = await loadModule("../src/lib/nav-daily-return.ts");

  const history = {
    navs: [
      { nav_date: "2026-07-01", accumulated_nav: 0.98, daily_return: -0.01 },
      { nav_date: "2026-06-30", accumulated_nav: 0.99, daily_return: -0.01 },
      { nav_date: "2026-06-28", accumulated_nav: 1.00, daily_return: 0.01 },
    ],
  };
  const rows = toNavChartPoints(history).filter((p) => p.date);

  const s = summarizePeriodReturns(rows);
  assert.equal(s.currentStreak.kind, "down");
  assert.equal(s.currentStreak.length, 2);
});

test("summarizePeriodReturns currentStreak flat when latest is null", async () => {
  const { summarizePeriodReturns, toNavChartPoints } = await loadModule("../src/lib/nav-daily-return.ts");

  const history = {
    navs: [
      { nav_date: "2026-07-01", accumulated_nav: 1.00, daily_return: null },
      { nav_date: "2026-06-30", accumulated_nav: 1.01, daily_return: 0.01 },
    ],
  };
  const rows = toNavChartPoints(history).filter((p) => p.date);

  const s = summarizePeriodReturns(rows);
  assert.equal(s.currentStreak.kind, "flat");
  assert.equal(s.currentStreak.length, 1);
});

test("summarizePeriodReturns skips NaN/Inf in cumulativeReturn", async () => {
  const { summarizePeriodReturns, toNavChartPoints } = await loadModule("../src/lib/nav-daily-return.ts");

  // daily_return=0.5 with nav=null → should not poison cumulativeReturn
  const history = {
    navs: [
      { nav_date: "2026-07-01", accumulated_nav: null, daily_return: 0.5 },
      { nav_date: "2026-06-30", accumulated_nav: 1.00, daily_return: 0.01 },
    ],
  };
  const rows = toNavChartPoints(history).filter((p) => p.date);

  const s = summarizePeriodReturns(rows);
  assert(Number.isFinite(s.cumulativeReturn));
  // navChange also skips null nav: only the valid (nav, daily_return) pair contributes
  // but since first row has nav=null, navChange should be null
  assert.equal(s.navChange, null);
});
