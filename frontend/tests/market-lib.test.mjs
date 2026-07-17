import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadMarketModule() {
  const source = await fs.readFile(new URL("../src/lib/market.ts", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const exports = {};
  const require = (specifier) => {
    if (specifier === "react") {
      return { useEffect: () => undefined, useState: () => [undefined, () => undefined] };
    }
    if (specifier === "@tanstack/react-query") {
      return {
        useMutation: () => undefined,
        useQuery: () => undefined,
        useQueryClient: () => ({ invalidateQueries: () => undefined }),
      };
    }
    if (specifier === "@/lib/query-keys") return { queryKeys: {} };
    if (specifier === "@/lib/query-policy") return { queryPolicy: {} };
    if (specifier === "@/lib/polling") return {};
    throw new Error(`unexpected require: ${specifier}`);
  };
  const context = {
    exports,
    module: { exports },
    require,
    URL,
    fetch: async () => ({ ok: true, json: async () => ({}) }),
    window: { location: { origin: "http://localhost:3000" } },
  };
  vm.runInNewContext(compiled, context, { filename: "market.ts" });
  return context.module.exports;
}

test("flattenMarketEvidence falls back to grouped evidence rows", async () => {
  const { flattenMarketEvidence } = await loadMarketModule();

  const rows = flattenMarketEvidence({
    count: 2,
    groups: {
      policy: [{ id: 1, category: "policy", title: "政策", source_url: "https://example.com/p" }],
      macro: [{ id: 2, category: "macro", title: "宏观", source_url: "https://example.com/m" }],
    },
  });

  assert.equal(rows.map((row) => row.title).join(","), "政策,宏观");
});

test("normalizeMarketBreadth returns numeric fallbacks for error payloads", async () => {
  const { normalizeMarketBreadth } = await loadMarketModule();

  const breadth = normalizeMarketBreadth({
    error: "fetch_market_breadth failed",
    source: "akshare",
  });

  assert.deepEqual(
    {
      up: breadth.up,
      down: breadth.down,
      limit_up: breadth.limit_up,
      limit_down: breadth.limit_down,
      error: breadth.error,
    },
    {
      up: 0,
      down: 0,
      limit_up: 0,
      limit_down: 0,
      error: "fetch_market_breadth failed",
    },
  );
});

test("resolveMarketDate uses Asia Shanghai calendar dates", async () => {
  const { resolveMarketDate } = await loadMarketModule();
  const midnightInShanghai = new Date("2026-07-07T16:30:00.000Z");

  assert.equal(resolveMarketDate("today", midnightInShanghai), "2026-07-08");
  assert.equal(resolveMarketDate("yesterday", midnightInShanghai), "2026-07-07");
});
