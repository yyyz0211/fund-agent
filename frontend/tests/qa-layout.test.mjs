import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

test("qa page uses workbench layout with textarea composer and query evidence label", async () => {
  const source = await fs.readFile(new URL("../app/qa/page.tsx", import.meta.url), "utf8");

  assert.match(source, /data-testid="qa-workbench"/);
  assert.match(source, /<textarea/);
  assert.match(source, /已查询的数据/);
  assert.match(source, /常用查询/);
});
