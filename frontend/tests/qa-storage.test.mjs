import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadModule() {
  const path = "../src/components/qa/storage.ts";
  const source = await fs.readFile(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  const context = { exports, module: { exports }, Date, JSON, Map, Object };
  vm.runInNewContext(compiled, context, { filename: path });
  return context.module.exports;
}

function makeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem(key) { return data.has(key) ? data.get(key) : null; },
    setItem(key, value) { data.set(key, value); },
    removeItem(key) { data.delete(key); },
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

test("qa storage keeps all existing localStorage keys", async () => {
  const storage = await loadModule();
  assert.equal(storage.QA_THREADS_STORAGE_KEY, "qa_threads_v1");
  assert.equal(storage.QA_ACTIVE_THREAD_STORAGE_KEY, "qa_active_thread_v1");
  assert.equal(storage.QA_THREAD_MESSAGES_STORAGE_KEY, "qa_thread_messages_v1");
});

test("qa storage saves and reloads thread metadata and active id", async () => {
  const { loadThreads, saveThreads, loadActiveThreadId, saveActiveThreadId } =
    await loadModule();
  const storage = makeStorage();
  const threads = [{ id: "t1", title: "问题", updatedAt: "2026-07-16T00:00:00.000Z" }];
  saveThreads(threads, storage);
  assert.deepEqual(normalize(loadThreads(storage)), threads);
  saveActiveThreadId("t1", storage);
  assert.equal(loadActiveThreadId(storage), "t1");
  saveActiveThreadId(null, storage);
  assert.equal(loadActiveThreadId(storage), null);
});

test("qa storage saves and reloads messages by thread id", async () => {
  const { loadThreadHistory, saveThreadHistory } = await loadModule();
  const storage = makeStorage();
  saveThreadHistory("thread-a", [sampleMessage], storage);
  assert.deepEqual(normalize(loadThreadHistory("thread-a", storage)), [sampleMessage]);
  assert.deepEqual(normalize(loadThreadHistory("thread-b", storage)), []);
});

test("qa storage removes one history without affecting others", async () => {
  const { loadThreadHistory, removeThreadHistory, saveThreadHistory } = await loadModule();
  const storage = makeStorage();
  saveThreadHistory("thread-a", [sampleMessage], storage);
  saveThreadHistory("thread-b", [{ ...sampleMessage, id: "m2" }], storage);
  removeThreadHistory("thread-a", storage);
  assert.deepEqual(normalize(loadThreadHistory("thread-a", storage)), []);
  assert.deepEqual(normalize(loadThreadHistory("thread-b", storage)), [
    { ...sampleMessage, id: "m2" },
  ]);
});

test("qa storage treats corrupted metadata and histories as empty", async () => {
  const {
    QA_THREADS_STORAGE_KEY,
    QA_THREAD_MESSAGES_STORAGE_KEY,
    loadThreadHistory,
    loadThreads,
    loadThreadHistories,
  } = await loadModule();
  const storage = makeStorage({
    [QA_THREADS_STORAGE_KEY]: "not json",
    [QA_THREAD_MESSAGES_STORAGE_KEY]: "not json",
  });
  assert.deepEqual(normalize(loadThreads(storage)), []);
  assert.deepEqual(normalize(loadThreadHistories(storage)), {});
  assert.deepEqual(normalize(loadThreadHistory("thread-a", storage)), []);
});
