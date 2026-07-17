import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

test("watchlist table refreshes one fund at a time from row actions", async () => {
  const source = await fs.readFile(new URL("../src/components/WatchlistTable.tsx", import.meta.url), "utf8");

  assert.match(source, /aria-label=\{`更新 \$\{r\.fund_code\}`\}/);
  assert.match(source, /api\.refreshFund\(row\.fund_code\)/);
  assert.match(source, /handleRefresh/);
  assert.doesNotMatch(source, /Promise\.all\(/);
});

test("watchlist row refresh invalidates fund-specific and portfolio query caches", async () => {
  const source = await fs.readFile(new URL("../src/components/WatchlistTable.tsx", import.meta.url), "utf8");

  assert.match(source, /queryKeys\.fund\.summaryForFund\(code\)/);
  assert.match(source, /queryKeys\.fund\.diagnosisForFund\(code\)/);
  assert.match(source, /queryKeys\.portfolio\.pnl\(\[code\]\)/);
  assert.match(source, /queryKeys\.portfolio\.pnl\(\[\]\)/);
});

test("watchlist page has a full refresh button that updates funds sequentially", async () => {
  const source = await fs.readFile(new URL("../app/watchlist/page.tsx", import.meta.url), "utf8");

  assert.match(source, /全量更新/);
  assert.match(source, /handleRefreshAll/);
  assert.match(source, /for \(const row of rowsToRefresh\)/);
  assert.match(source, /await api\.refreshFund\(row\.fund_code\)/);
  assert.match(source, /setRefreshAllProgress/);
  assert.doesNotMatch(source, /Promise\.all\(/);
});

test("watchlist page displays portfolio total pnl from portfolio pnl endpoint", async () => {
  const source = await fs.readFile(new URL("../app/watchlist/page.tsx", import.meta.url), "utf8");

  assert.match(source, /queryKey: queryKeys\.portfolio\.pnl\(\[\]\)/);
  assert.match(source, /queryFn: \(\) => api\.portfolioPnl\(\)/);
  assert.match(source, /总盈亏/);
  assert.match(source, /portfolioPnl\.data\?\.totals\.pnl_abs/);
  assert.match(source, /formatSignedMoney/);
});
