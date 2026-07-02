import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadModule(relativePath) {
  const source = await fs.readFile(new URL(relativePath, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const exports = {};
  const context = { exports, module: { exports } };
  vm.runInNewContext(compiled, context, { filename: relativePath });
  return context.module.exports;
}

test("filterWatchlistRows matches code and note without mutating rows", async () => {
  const { filterWatchlistRows } = await loadModule("../src/lib/watchlist-filter.ts");
  const rows = [
    { fund_code: "110011", fund_name: "易方达优质精选", note: "核心关注" },
    { fund_code: "000300", fund_name: "沪深300ETF", note: "沪深300 对照", peer_category: "指数型" },
    { fund_code: "161725", fund_name: "招商中证白酒", note: null },
  ];

  assert.deepEqual(filterWatchlistRows(rows, "300"), [rows[1]]);
  assert.deepEqual(filterWatchlistRows(rows, "核心"), [rows[0]]);
  assert.deepEqual(filterWatchlistRows(rows, "白酒"), [rows[2]]);
  assert.deepEqual(filterWatchlistRows(rows, "指数"), []);
  assert.deepEqual(filterWatchlistRows(rows, "  "), rows);
  assert.equal(filterWatchlistRows(rows, "300")[0], rows[1]);
});
