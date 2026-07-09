import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

async function read(path) {
  return fs.readFile(new URL(path, import.meta.url), "utf8");
}

test("market page renders a market evidence panel", async () => {
  const page = await read("../app/market/page.tsx");

  assert.match(page, /useMarketEvidence/);
  assert.match(page, /MarketEvidencePanel/);
  assert.doesNotMatch(page, /title="证据面板"/);
});

test("briefing page renders evidence quality beside latest brief", async () => {
  const page = await read("../app/briefing/page.tsx");

  assert.match(page, /api\\.marketEvidence/);
  assert.match(page, /证据来源/);
  assert.match(page, /数据质量/);
});

test("market evidence component preserves source links and empty state", async () => {
  const component = await read("../src/components/market/MarketEvidencePanel.tsx");

  assert.match(component, /source_url/);
  assert.match(component, /href=/);
  assert.match(component, /暂无可验证证据/);
});

test("market evidence empty state can show remote refresh failures", async () => {
  const component = await read("../src/components/market/MarketEvidencePanel.tsx");
  const marketLib = await read("../src/lib/market.ts");

  assert.match(component, /useEvidenceRefreshStatus/);
  assert.match(component, /远程证据获取失败/);
  assert.match(component, /最近一次拉取未写入数据/);
  assert.match(marketLib, /evidence\/refresh\/status/);
});

test("market evidence component is a single compact scrollable card", async () => {
  const component = await read("../src/components/market/MarketEvidencePanel.tsx");

  assert.match(component, /h-\[520px\].*flex-col/);
  assert.match(component, /min-h-0 flex-1 divide-y divide-gray-100 overflow-y-auto/);
  assert.match(component, /overflow-y-auto/);
  assert.match(component, /证据面板/);
  assert.doesNotMatch(component, /<section key=\{cat\}/);
  assert.doesNotMatch(component, /分类概览/);
});

test("market page places evidence and sector strength in one desktop row", async () => {
  const page = await read("../app/market/page.tsx");
  const sectorTable = await read("../src/components/market/SectorTabbedTable.tsx");

  assert.match(page, /lg:grid-cols-\[minmax\(500px,0\.95fr\)_minmax\(0,1\.05fr\)\]/);
  assert.match(page, /<MarketEvidencePanel date=\{date\} \/>[\s\S]*<SectorTabbedTable snap=\{snap\} \/>/);
  assert.doesNotMatch(page, /title="板块强弱"/);
  assert.match(sectorTable, /板块强弱/);
  assert.doesNotMatch(sectorTable, /行内 sparkline · 净流入亿/);
  assert.doesNotMatch(sectorTable, /flex flex-col gap-2/);
  // 同一行布局: header 必须用单层 flex,而非 justify-between 双行布局
  assert.match(sectorTable, /<div className="flex min-w-0 flex-wrap items-center gap-2 border-b border-gray-100 px-3 py-2">/);
  // 重新抓取按钮仍在 header 末尾
  assert.match(sectorTable, /<div className="ml-auto shrink-0">[\s\S]*RefreshCw/);
});

test("market evidence and sector cards use equal-height internal scrolling", async () => {
  const page = await read("../app/market/page.tsx");
  const evidence = await read("../src/components/market/MarketEvidencePanel.tsx");
  const sectorTable = await read("../src/components/market/SectorTabbedTable.tsx");

  assert.match(page, /<div className="min-w-0 lg:h-full">[\s\S]*<MarketEvidencePanel date=\{date\} \/>/);
  assert.match(page, /<div className="min-w-0 lg:h-full">[\s\S]*<SectorTabbedTable snap=\{snap\} \/>/);
  assert.match(evidence, /h-\[520px\].*flex-col/);
  assert.match(sectorTable, /h-\[520px\].*flex-col/);
  assert.match(sectorTable, /className="flex min-h-0 flex-1 flex-col"/);
  assert.match(sectorTable, /min-h-0 flex-1 overflow-y-auto/);
  assert.match(sectorTable, /sticky top-0/);
});

test("sector mover chips render in the card header", async () => {
  const sectorTable = await read("../src/components/market/SectorTabbedTable.tsx");

  // chips 必须在外层 header 容器内出现(同行布局)
  assert.match(sectorTable, /<h2[^>]*>板块强弱<\/h2>[\s\S]*<SectorMoverChips strongest=\{strongest\} weakest=\{weakest\} \/>/);
  assert.match(sectorTable, /function SectorMoverChips/);
  // 不要回到老的两行结构(独立 chips 行)
  assert.doesNotMatch(sectorTable, /<div className="flex items-center gap-2 px-3 py-2 text-xs">/);
});

test("market evidence rows prioritize visible evidence titles", async () => {
  const component = await read("../src/components/market/MarketEvidencePanel.tsx");

  assert.match(component, /line-clamp-2 text-sm font-semibold/);
  assert.match(component, /aria-label=\{`打开证据：\$\{item\.title\}`\}/);
  assert.match(component, /mt-1 flex flex-wrap items-center gap-x-2/);
  assert.doesNotMatch(component, /lg:grid-cols-\[minmax\(0,1fr\)_auto\]/);
  assert.doesNotMatch(component, /truncate text-sm font-medium/);
});

test("market evidence labels reflect actual source and reliability", async () => {
  const component = await read("../src/components/market/MarketEvidencePanel.tsx");

  assert.match(component, /function isClsTelegraphEvidence/);
  assert.match(component, /function evidenceCategoryLabel/);
  assert.match(component, /function evidenceSummaryCategoryLabel/);
  assert.match(component, /item\.metrics\?\.cls_id/);
  assert.match(component, /source_url\.includes\("https:\/\/www\.cls\.cn\/detail\/"\)/);
  assert.match(component, /财联社电报/);
  assert.match(component, /媒体源/);
  assert.match(component, /市场资讯 \/ 公告 \/ 宏观等/);
  assert.match(component, /政策 \/ 公告 \/ 宏观 \/ 行业 \/ 市场资讯/);
  assert.doesNotMatch(component, /财联社快讯/);
  assert.doesNotMatch(component, /聚合/);
  assert.doesNotMatch(component, /normalized === "财联社"\) return "财联社电报"/);
});

test("sector table hides trend column when history is unavailable and uses compact rows", async () => {
  const sectorTable = await read("../src/components/market/SectorTabbedTable.tsx");

  assert.match(sectorTable, /const hasHistory = sorted\.some/);
  assert.match(sectorTable, /\{hasHistory \? \(/);
  assert.match(sectorTable, /px-3 py-2/);
  assert.doesNotMatch(sectorTable, /<span className="text-xs text-gray-300">—<\/span>/);
});

test("sector tables display net flow values as yi units without extra scaling", async () => {
  const sectorTable = await read("../src/components/market/SectorTabbedTable.tsx");
  // 旧 SectorTable.tsx 已被 SectorTabbedTable 取代,不要走 /* 10000 */ 那条换算路径
  assert.doesNotMatch(sectorTable, /\/\s*10000/);
  assert.match(sectorTable, /toFixed\(2\)\}亿/);
});
