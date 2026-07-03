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

test("validateInvestmentPlanDraft returns payload for valid monthly plan", async () => {
  const { validateInvestmentPlanDraft } = await loadModule("../src/lib/investment-plan.ts");

  const result = validateInvestmentPlanDraft({
    amount: "1000",
    frequency: "monthly",
    day_rule: "5",
    start_date: "2026-07-01",
    end_date: "2026-12-31",
    note: "  fixed plan  ",
  });

  assert.deepEqual(normalize(result), {
    ok: true,
    payload: {
      amount: 1000,
      frequency: "monthly",
      day_rule: "5",
      start_date: "2026-07-01",
      end_date: "2026-12-31",
      status: "active",
      note: "fixed plan",
    },
  });
});

test("validateInvestmentPlanDraft rejects invalid amount frequency and date range", async () => {
  const { validateInvestmentPlanDraft } = await loadModule("../src/lib/investment-plan.ts");

  assert.equal(validateInvestmentPlanDraft({
    amount: "0",
    frequency: "monthly",
    day_rule: "5",
    start_date: "2026-07-01",
    end_date: "",
    note: "",
  }).ok, false);

  assert.equal(validateInvestmentPlanDraft({
    amount: "1000",
    frequency: "yearly",
    day_rule: "5",
    start_date: "2026-07-01",
    end_date: "",
    note: "",
  }).ok, false);

  assert.equal(validateInvestmentPlanDraft({
    amount: "1000",
    frequency: "monthly",
    day_rule: "5",
    start_date: "2026-12-31",
    end_date: "2026-07-01",
    note: "",
  }).ok, false);
});

test("validateInvestmentPlanDraft accepts daily plan rules", async () => {
  const { validateInvestmentPlanDraft } = await loadModule("../src/lib/investment-plan.ts");

  const result = validateInvestmentPlanDraft({
    amount: "100",
    frequency: "daily",
    day_rule: "交易日",
    start_date: "2026-07-01",
    end_date: "",
    note: "",
  });

  assert.deepEqual(normalize(result), {
    ok: true,
    payload: {
      amount: 100,
      frequency: "daily",
      day_rule: "交易日",
      start_date: "2026-07-01",
      end_date: null,
      status: "active",
      note: null,
    },
  });
});
