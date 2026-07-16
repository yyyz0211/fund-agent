import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

test("qa page uses workbench layout with textarea composer and query evidence label", async () => {
  const workbench = await fs.readFile(
    new URL("../src/components/qa/QaWorkbench.tsx", import.meta.url),
    "utf8",
  );
  const messages = await fs.readFile(
    new URL("../src/components/qa/MessageList.tsx", import.meta.url),
    "utf8",
  );
  const composer = await fs.readFile(
    new URL("../src/components/qa/Composer.tsx", import.meta.url),
    "utf8",
  );
  const tools = await fs.readFile(
    new URL("../src/components/qa/ToolStepList.tsx", import.meta.url),
    "utf8",
  );
  const route = await fs.readFile(new URL("../app/qa/page.tsx", import.meta.url), "utf8");

  assert.match(workbench, /data-testid="qa-workbench"/);
  assert.match(composer, /<textarea/);
  assert.match(tools, /已查询的数据/);
  assert.match(messages, /常用查询/);
  assert.match(route, /from "@\/components\/qa"/);
});
