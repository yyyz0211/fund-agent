import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

async function read(path) {
  return fs.readFile(new URL(path, import.meta.url), "utf8");
}

test("market page uses a centered dashboard container", async () => {
  const source = await read("../app/market/page.tsx");

  assert.match(source, /max-w-7xl/);
  assert.match(source, /mx-auto/);
  assert.match(source, /市场情报中心/);
});

test("market UI follows A-share red-up green-down convention", async () => {
  const overview = await read("../src/components/market/MarketOverviewCards.tsx");
  const tableUtils = await read("../src/components/market/MarketTableUtils.tsx");
  const breadth = await read("../src/components/market/MarketBreadthBanner.tsx");

  assert.match(overview, /positive \? "red"/);
  assert.match(tableUtils, /pct > 0 \? "text-red/);
  assert.match(tableUtils, /pct < 0 \? "text-green/);
  assert.match(breadth, /text-red-700[^\\n]+上涨/);
  assert.match(breadth, /text-green-700[^\\n]+下跌/);
});

test("market sector change bar is centered around zero", async () => {
  const tableUtils = await read("../src/components/market/MarketTableUtils.tsx");

  assert.ok(tableUtils.includes("left-1/2"));
  assert.ok(tableUtils.includes("translate-x-[1px]"));
  assert.match(tableUtils, /-translate-x-full/);
});
