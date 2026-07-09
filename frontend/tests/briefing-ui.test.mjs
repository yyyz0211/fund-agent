import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

test("briefing page uses a dashboard layout with side rail", async () => {
  const source = await fs.readFile(new URL("../app/briefing/page.tsx", import.meta.url), "utf8");

  assert.match(source, /max-w-7xl/);
  assert.match(source, /简报工作台/);
  assert.match(source, /lg:grid-cols-\[minmax\(0,1fr\)_360px\]/);
  assert.match(source, /简报状态/);
  assert.match(source, /历史简报/);
});

test("briefing markdown is rendered inside a readable document surface", async () => {
  const source = await fs.readFile(new URL("../app/briefing/page.tsx", import.meta.url), "utf8");

  assert.match(source, /md-body/);
  assert.match(source, /rounded-2xl/);
  assert.match(source, /ReactMarkdown/);
});

test("briefing api helpers forward brief type", async () => {
  const source = await fs.readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");

  assert.match(source, /briefingLatest:\s*\(type = "post_market"\)/);
  assert.match(source, /get<BriefingLatestResponse>\("\/api\/briefing\/latest", \{ type \}\)/);
  assert.match(source, /briefingList:\s*\(limit = 30, type = "post_market"\)/);
  assert.match(source, /JSON\.stringify\(\{ brief_type: briefType \}\)/);
});
