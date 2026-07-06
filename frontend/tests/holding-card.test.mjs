import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

test("holding card renders an empty state instead of disappearing when no holding exists", async () => {
  const source = await fs.readFile(new URL("../src/components/HoldingCard.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(source, /if\s*\(!item\)\s*return\s+null/);
  assert.match(source, /const missing = "--"/);
  assert.match(source, /暂无持仓记录/);
});

test("holding card shows pending buy amount separately from confirmed market value", async () => {
  const source = await fs.readFile(new URL("../src/components/HoldingCard.tsx", import.meta.url), "utf8");

  assert.match(source, /api\.pendingBuys/);
  assert.match(source, /申购中金额/);
  assert.match(source, /pendingAmount/);
});
