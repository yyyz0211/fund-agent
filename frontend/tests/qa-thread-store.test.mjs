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

function makeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      data.set(key, value);
    },
    removeItem(key) {
      data.delete(key);
    },
  };
}

function normalize(value) {
  return JSON.parse(JSON.stringify(value));
}

const sampleMessage = {
  id: "m1",
  role: "user",
  content: "110011 最新净值",
  ts: "2026-07-01T00:00:00.000Z",
  toolSteps: [],
};

test("qa thread store saves and reloads messages by thread id", async () => {
  const {
    loadThreadHistory,
    saveThreadHistory,
  } = await loadModule("../src/lib/qa-thread-store.ts");
  const storage = makeStorage();

  saveThreadHistory("thread-a", [sampleMessage], storage);

  assert.deepEqual(normalize(loadThreadHistory("thread-a", storage)), [sampleMessage]);
  assert.deepEqual(normalize(loadThreadHistory("thread-b", storage)), []);
});

test("qa thread store removes one thread without affecting others", async () => {
  const {
    loadThreadHistory,
    removeThreadHistory,
    saveThreadHistory,
  } = await loadModule("../src/lib/qa-thread-store.ts");
  const storage = makeStorage();

  saveThreadHistory("thread-a", [sampleMessage], storage);
  saveThreadHistory("thread-b", [{ ...sampleMessage, id: "m2" }], storage);
  removeThreadHistory("thread-a", storage);

  assert.deepEqual(normalize(loadThreadHistory("thread-a", storage)), []);
  assert.deepEqual(normalize(loadThreadHistory("thread-b", storage)), [{ ...sampleMessage, id: "m2" }]);
});

test("qa thread store treats corrupted storage as empty history", async () => {
  const {
    QA_THREAD_MESSAGES_STORAGE_KEY,
    loadThreadHistories,
    loadThreadHistory,
  } = await loadModule("../src/lib/qa-thread-store.ts");
  const storage = makeStorage({ [QA_THREAD_MESSAGES_STORAGE_KEY]: "not json" });

  assert.deepEqual(normalize(loadThreadHistories(storage)), {});
  assert.deepEqual(normalize(loadThreadHistory("thread-a", storage)), []);
});
