import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

test("watchlist drawer exposes pending buy tab and market value disclaimer", async () => {
  const source = await fs.readFile(
    new URL("../src/components/WatchlistDrawer.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /申购中/);
  assert.match(source, /申购中金额不计入当前市值/);
  assert.match(source, /pendingBuys/);
});
