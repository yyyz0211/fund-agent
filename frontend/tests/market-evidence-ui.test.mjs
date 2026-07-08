import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

async function read(path) {
  return fs.readFile(new URL(path, import.meta.url), "utf8");
}

test("market page renders a market evidence panel", async () => {
  const page = await read("../app/market/page.tsx");

  assert.match(page, /useMarketEvidence/);
  assert.match(page, /证据面板/);
  assert.match(page, /MarketEvidencePanel/);
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
