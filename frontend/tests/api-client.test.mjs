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

test("api.fundSummary calls summary endpoint with period and start params", async () => {
  const urls = [];
  const fetch = async (url) => {
    urls.push(String(url));
    return {
      ok: true,
      status: 200,
      json: async () => ({ fund_code: "110011" }),
    };
  };
  const { api } = await loadModule("../src/lib/api.ts", { fetch });

  await api.fundSummary("110011", "1m", "2026-06-01");

  assert.equal(
    urls[0],
    "http://api.test/api/funds/110011/summary?period=1m&start=2026-06-01",
  );
});

test("api.fundDiagnosis calls diagnosis endpoint with period", async () => {
  const urls = [];
  const fetch = async (url) => {
    urls.push(String(url));
    return {
      ok: true,
      status: 200,
      json: async () => ({ fund_code: "110011", decision_label: "观察" }),
    };
  };
  const { api } = await loadModule("../src/lib/api.ts", { fetch });

  await api.fundDiagnosis("110011", "1y");

  assert.equal(
    urls[0],
    "http://api.test/api/funds/110011/diagnosis?period=1y",
  );
});

test("api.refreshFundDiagnosis posts to refresh endpoint", async () => {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return {
      ok: true,
      status: 202,
      json: async () => ({ job_id: "job-1" }),
    };
  };
  const { api } = await loadModule("../src/lib/api.ts", { fetch });

  await api.refreshFundDiagnosis("110011");

  assert.equal(calls[0].url, "http://api.test/api/funds/110011/diagnosis/refresh?force=true");
  assert.equal(calls[0].init.method, "POST");
});

test("api.fundDiagnosisRefreshJob calls job status endpoint", async () => {
  const urls = [];
  const fetch = async (url) => {
    urls.push(String(url));
    return {
      ok: true,
      status: 200,
      json: async () => ({ job_id: "job-1", status: "done" }),
    };
  };
  const { api } = await loadModule("../src/lib/api.ts", { fetch });

  await api.fundDiagnosisRefreshJob("110011", "job-1");

  assert.equal(
    urls[0],
    "http://api.test/api/funds/110011/diagnosis/refresh/job-1",
  );
});
