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
  const context = {
    exports,
    module: { exports },
    encodeURIComponent,
  };
  vm.runInNewContext(compiled, context, { filename: relativePath });
  return context.module.exports;
}

test("riskLightClass maps levels to stable color classes", async () => {
  const { riskLightClass } = await loadModule("../src/lib/diagnosis-ui.ts");

  assert.match(riskLightClass("red"), /red/);
  assert.match(riskLightClass("yellow"), /amber/);
  assert.match(riskLightClass("green"), /green/);
  assert.match(riskLightClass("gray"), /gray/);
});

test("decisionLabelClass maps labels to stable color classes", async () => {
  const { decisionLabelClass } = await loadModule("../src/lib/diagnosis-ui.ts");

  assert.match(decisionLabelClass("暂不碰"), /red/);
  assert.match(decisionLabelClass("观察"), /amber/);
  assert.match(decisionLabelClass("小仓试验"), /blue/);
  assert.match(decisionLabelClass("候选"), /green/);
});

test("compareUrlForPeers includes source code and peer codes", async () => {
  const { compareUrlForPeers } = await loadModule("../src/lib/diagnosis-ui.ts");

  assert.equal(
    compareUrlForPeers("110011", [{ fund_code: "000001" }, { fund_code: "000002" }]),
    "/compare?codes=110011%2C000001%2C000002",
  );
});
