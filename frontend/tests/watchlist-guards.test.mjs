import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadModule(relativePath, contextOverrides = {}) {
  const source = await fs.readFile(new URL(relativePath, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const exports = {};
  const context = {
    exports,
    module: { exports },
    URL,
    process: { env: { NEXT_PUBLIC_API_BASE: "http://api.test" } },
    ...contextOverrides,
  };
  vm.runInNewContext(compiled, context, { filename: relativePath });
  return context.module.exports;
}

test("shouldUseInitialHoldingEndpoint only true for add/convert path with no tx history", async () => {
  const { shouldUseInitialHoldingEndpoint } = await loadModule(
    "../src/lib/watchlist-guards.ts",
  );

  // add + is_holding=true + 无历史 → true
  assert.equal(
    shouldUseInitialHoldingEndpoint({ mode: "add", formIsHolding: true }),
    true,
  );

  // add + is_holding=false → false
  assert.equal(
    shouldUseInitialHoldingEndpoint({ mode: "add", formIsHolding: false }),
    false,
  );

  // edit + row.is_holding=true (已持仓) + form 仍勾 is_holding → false
  // (前端应保持 is_holding=true,走 /transactions 加仓,不能调 initial-holding)
  assert.equal(
    shouldUseInitialHoldingEndpoint({
      mode: "edit",
      formIsHolding: true,
      rowIsHolding: true,
    }),
    false,
  );

  // edit + row.is_holding=false + form 勾 is_holding=true (从关注转持仓) → true
  assert.equal(
    shouldUseInitialHoldingEndpoint({
      mode: "edit",
      formIsHolding: true,
      rowIsHolding: false,
    }),
    true,
  );

  // 已有 1 笔交易 → 任何路径都 false,避免把首笔 buy 静默合并
  assert.equal(
    shouldUseInitialHoldingEndpoint({
      mode: "edit",
      formIsHolding: true,
      rowIsHolding: true,
      rowTransactionCount: 1,
    }),
    false,
  );
  // add 模式时如果 row 已存在且有交易(不可能的 add,但 defensive) → false
  assert.equal(
    shouldUseInitialHoldingEndpoint({
      mode: "add",
      formIsHolding: true,
      rowTransactionCount: 1,
    }),
    false,
  );

  // row.is_holding=null/undefined 的 edit + form.is_holding=true → 保守:false
  // (后端 409 兜底,前端少发一次错误请求)
  assert.equal(
    shouldUseInitialHoldingEndpoint({
      mode: "edit",
      formIsHolding: true,
      rowIsHolding: null,
    }),
    false,
  );
  assert.equal(
    shouldUseInitialHoldingEndpoint({
      mode: "edit",
      formIsHolding: true,
    }),
    false,
  );
});
