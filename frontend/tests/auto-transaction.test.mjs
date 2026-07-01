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

function normalize(value) {
  return JSON.parse(JSON.stringify(value));
}

const latestNav = {
  fund_code: "110011",
  nav_date: "2026-06-30",
  accumulated_nav: 2.5,
  source: "akshare",
  as_of: "2026-07-01",
};

test("buildAutoTransactionDraft uses latest accumulated NAV and nav_date", async () => {
  const { buildAutoTransactionDraft } = await loadModule("../src/lib/auto-transaction.ts");

  const draft = buildAutoTransactionDraft({
    amountInput: "1000",
    feeInput: "1.5",
    note: "initial holding",
    latestNav,
  });

  assert.deepEqual(normalize(draft), {
    payload: {
      tx_date: "2026-06-30",
      amount: 1000,
      nav: 2.5,
      fee: 1.5,
      note: "initial holding",
    },
    estimatedShare: 400,
  });
});

test("buildAutoTransactionDraft trims optional note and fee", async () => {
  const { buildAutoTransactionDraft } = await loadModule("../src/lib/auto-transaction.ts");

  const draft = buildAutoTransactionDraft({
    amountInput: "250",
    feeInput: " ",
    note: "  ",
    latestNav,
  });

  assert.deepEqual(normalize(draft.payload), {
    tx_date: "2026-06-30",
    amount: 250,
    nav: 2.5,
    fee: null,
    note: null,
  });
  assert.equal(draft.estimatedShare, 100);
});

test("buildAutoTransactionDraft rejects invalid amount or NAV", async () => {
  const { buildAutoTransactionDraft } = await loadModule("../src/lib/auto-transaction.ts");

  assert.equal(buildAutoTransactionDraft({
    amountInput: "",
    latestNav,
  }), null);
  assert.equal(buildAutoTransactionDraft({
    amountInput: "1000",
    latestNav: { ...latestNav, accumulated_nav: null },
  }), null);
  assert.equal(buildAutoTransactionDraft({
    amountInput: "1000",
    latestNav: { ...latestNav, accumulated_nav: 0 },
  }), null);
});
