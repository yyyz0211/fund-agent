import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadModule() {
  const path = "../src/components/qa/stream-events.ts";
  const source = await fs.readFile(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  const context = { exports, module: { exports }, JSON, Object, Array };
  vm.runInNewContext(compiled, context, { filename: path });
  return context.module.exports;
}

function normalize(value) {
  return JSON.parse(JSON.stringify(value));
}

const history = [{
  id: "assistant-1",
  role: "assistant",
  content: "",
  ts: "2026-07-16T00:00:00.000Z",
  toolSteps: [],
}];

test("stream events deduplicate tool calls and preserve completed replay result", async () => {
  const { appendPendingToolCalls, completeToolStep } = await loadModule();
  const call = { id: "call-1", name: "get_latest_fund_nav", args: { fund_code: "110011" } };
  const once = appendPendingToolCalls(history, "assistant-1", [call]);
  const twice = appendPendingToolCalls(once, "assistant-1", [call]);
  assert.equal(twice[0].toolSteps.length, 1);
  const done = completeToolStep(twice, "assistant-1", "call-1", "first");
  const replay = completeToolStep(done, "assistant-1", "call-1", "second");
  assert.equal(replay[0].toolSteps[0].status, "done");
  assert.equal(replay[0].toolSteps[0].result, "first");
});

test("stream events normalize assistant and tool content", async () => {
  const { readAssistantContent, readToolResult } = await loadModule();
  assert.equal(readAssistantContent(["A", { text: "B" }, { other: true }]), "AB");
  assert.equal(readAssistantContent({ text: "ignored" }), "");
  assert.equal(readToolResult(["A", { text: "B" }]), "AB");
  assert.equal(readToolResult({ ok: true }), JSON.stringify({ ok: true }));
});

test("stream events replace only the target assistant content", async () => {
  const { replaceAssistantContent } = await loadModule();
  const next = replaceAssistantContent(history, "assistant-1", "chunk");
  assert.equal(next[0].content, "chunk");
  assert.equal(replaceAssistantContent(history, "other", "ignored"), history);
  assert.deepEqual(normalize(history), [{ ...history[0], content: "" }]);
});

test("parseStreamMessage picks last array element and rejects non-records", async () => {
  const { parseStreamMessage } = await loadModule();
  assert.deepEqual(
    parseStreamMessage([{ type: "ai" }, { type: "tool", tool_call_id: "c1" }]),
    { type: "tool", tool_call_id: "c1" },
  );
  assert.deepEqual(parseStreamMessage({ type: "ai" }), { type: "ai" });
  assert.equal(parseStreamMessage([]), null);
  assert.equal(parseStreamMessage("hi"), null);
  assert.equal(parseStreamMessage(null), null);
});

test("stream message predicates match branch conditions", async () => {
  const { isAssistantMessage, isToolMessage, readToolCalls } = await loadModule();
  assert.equal(isAssistantMessage({ type: "ai" }), true);
  assert.equal(isAssistantMessage({ role: "assistant" }), true);
  assert.equal(isAssistantMessage({ type: "tool" }), false);
  assert.equal(isToolMessage({ type: "tool", tool_call_id: "c1" }), true);
  assert.equal(isToolMessage({ type: "tool" }), false);
  assert.equal(isToolMessage({ type: "tool", tool_call_id: 1 }), false);
  assert.equal(readToolCalls({ tool_calls: [{ id: "c1", name: "x" }] }).length, 1);
  assert.equal(readToolCalls({ tool_calls: [] }), null);
  assert.equal(readToolCalls({}), null);
});
