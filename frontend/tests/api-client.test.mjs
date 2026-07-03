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

test("api.nav can request an exact NAV date", async () => {
  const urls = [];
  const fetch = async (url) => {
    urls.push(String(url));
    return {
      ok: true,
      status: 200,
      json: async () => ({ fund_code: "110011", nav_date: "2026-06-01" }),
    };
  };
  const { api } = await loadModule("../src/lib/api.ts", { fetch });

  await api.nav("110011", "2026-06-01");

  assert.equal(
    urls[0],
    "http://api.test/api/funds/110011/nav?date=2026-06-01",
  );
});

test("api investment plan methods call watchlist plan endpoints", async () => {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return {
      ok: true,
      status: 200,
      json: async () => ({ id: 7, fund_code: "110011" }),
    };
  };
  const { api } = await loadModule("../src/lib/api.ts", { fetch });

  await api.investmentPlans("110011");
  await api.investmentPlanAdd("110011", {
    amount: 1000,
    frequency: "monthly",
    day_rule: "5",
    start_date: "2026-07-01",
  });
  await api.investmentPlanUpdate("110011", 7, { status: "paused" });
  await api.investmentPlanRemove("110011", 7);

  assert.equal(calls[0].url, "http://api.test/api/watchlist/110011/investment-plans");
  assert.equal(calls[1].url, "http://api.test/api/watchlist/110011/investment-plans");
  assert.equal(calls[1].init.method, "POST");
  assert.equal(
    calls[2].url,
    "http://api.test/api/watchlist/110011/investment-plans/7",
  );
  assert.equal(calls[2].init.method, "PATCH");
  assert.equal(
    calls[3].url,
    "http://api.test/api/watchlist/110011/investment-plans/7",
  );
  assert.equal(calls[3].init.method, "DELETE");
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

test("api.watchlistPreloadJob calls watchlist preload endpoint", async () => {
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

  await api.watchlistPreloadJob("110011", "job-1");

  assert.equal(
    urls[0],
    "http://api.test/api/watchlist/110011/preload/job-1",
  );
});
