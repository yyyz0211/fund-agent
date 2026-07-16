import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadModule() {
  const path = "../src/components/watchlist-drawer/form-state.ts";
  const source = await fs.readFile(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const exports = {};
  const context = { exports, module: { exports } };
  vm.runInNewContext(compiled, context, { filename: path });
  return context.module.exports;
}

function normalize(value) {
  return JSON.parse(JSON.stringify(value));
}

test("watchlist row maps to an editable form without null values", async () => {
  const { rowToWatchlistForm } = await loadModule();
  assert.deepEqual(
    normalize(
      rowToWatchlistForm({
        fund_code: "110011",
        note: null,
        is_holding: 1,
        is_focus: 0,
        holding_amount: 1200.5,
        buy_date: null,
      }),
    ),
    {
      fund_code: "110011",
      note: "",
      is_holding: true,
      is_focus: false,
      holding_amount: "1200.5",
      holding_date: "",
    },
  );
});

test("blank forms preserve fund prefill and exact empty fields", async () => {
  const { blankWatchlistForm, blankTransactionForm, blankPendingBuyForm } =
    await loadModule();
  assert.deepEqual(normalize(blankWatchlistForm("000001")), {
    fund_code: "000001",
    note: "",
    is_holding: false,
    is_focus: false,
    holding_amount: "",
    holding_date: "",
  });
  assert.deepEqual(normalize(blankTransactionForm()), {
    tx_date: "",
    amount: "",
    fee: "",
    note: "",
  });
  assert.deepEqual(normalize(blankPendingBuyForm()), {
    request_date: "",
    amount: "",
    fee: "",
    note: "",
  });
});

test("positive number parsing rejects empty zero negative and non numeric values", async () => {
  const { parsePositiveNumber } = await loadModule();
  assert.equal(parsePositiveNumber("10.25"), 10.25);
  for (const value of ["", "0", "-1", "not-a-number"]) {
    assert.equal(parsePositiveNumber(value), null);
  }
});
