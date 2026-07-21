# LangGraph Stream Message Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the single remaining frontend `any` (the LangGraph streamed message in `useQaStream`) by introducing a local typed message model plus runtime narrowing helpers in `stream-events.ts`, consumed by `useQaStream`.

**Architecture:** `stream-events.ts` already owns stream content parsing; it gains a `StreamMessage` interface, a `parseStreamMessage` parser, and three typed predicates. `useQaStream.ts` swaps its `any`-based inline field reads for these typed helpers. Behavior is preserved branch-for-branch. Two `node:test` files gain focused coverage plus a source-level no-`any` gate.

**Tech Stack:** Next.js 14.2.5, React 18.3.1, TypeScript 5.5 strict, `@langchain/langgraph-sdk` 0.0.10 (does not export message types), Node `node:test`, TypeScript compiler API for VM-loading `.ts` in tests.

## Global Constraints

- Preserve every existing stream branch outcome exactly; the only intended tightening is `isToolMessage` requiring `tool_call_id` to be a `string` (was a truthiness check).
- Do not add dependencies; hand-roll the message types locally.
- Do not touch `error: unknown` props anywhere — out of scope.
- Do not restructure `useQaStream`'s control flow; only replace raw field reads with typed helpers.
- Do not modify the backend, other frontend components, or the SDK.
- No production `any` or `as any` may remain in `useQaStream.ts`.
- One implementation commit after all tasks (project hard-cut convention).

---

## File Map

**Modify**

- `frontend/src/components/qa/stream-events.ts` — add `StreamMessage`, `parseStreamMessage`, `isAssistantMessage`, `isToolMessage`, `readToolCalls`; `export` the existing `StreamToolCall`.
- `frontend/src/components/qa/hooks/useQaStream.ts` — consume the typed helpers; delete the `any`.
- `frontend/tests/qa-stream-events.test.mjs` — add parser and predicate tests.
- `frontend/tests/qa-structure.test.mjs` — add the no-`any` source gate.

**Do not modify**

- Backend, other frontend components, `error: unknown` props, SDK, or any other test file.

---

### Task 1: Add typed message model, parser, and predicates to `stream-events.ts`

**Files:**
- Modify: `frontend/src/components/qa/stream-events.ts`
- Test: `frontend/tests/qa-stream-events.test.mjs`

**Interfaces:**
- Consumes: the existing `isRecord(value: unknown): value is Record<string, unknown>` helper already in `stream-events.ts`.
- Produces:
  - `export interface StreamToolCall { id: string; name: string; args?: Record<string, unknown> }`
  - `export interface StreamMessage { type?: string; role?: string; content?: unknown; tool_calls?: StreamToolCall[]; tool_call_id?: string }`
  - `parseStreamMessage(data: unknown): StreamMessage | null`
  - `isAssistantMessage(message: StreamMessage): boolean`
  - `isToolMessage(message: StreamMessage): message is StreamMessage & { tool_call_id: string }`
  - `readToolCalls(message: StreamMessage): StreamToolCall[] | null`

- [ ] **Step 1: Add the parser and predicate tests (failing)**

Append these two tests to `frontend/tests/qa-stream-events.test.mjs`. It already has a `loadModule()` helper that TS-transpiles and VM-loads `../src/components/qa/stream-events.ts`, and `import assert from "node:assert/strict"` / `import test from "node:test"` at the top — reuse them, do not redeclare.

```js
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd frontend && node --test tests/qa-stream-events.test.mjs`
Expected: the two new tests FAIL (e.g. `parseStreamMessage is not a function`); the three pre-existing tests still PASS.

- [ ] **Step 3: Implement the types, parser, and predicates**

In `frontend/src/components/qa/stream-events.ts`, change the existing declaration `interface StreamToolCall {` (near the top) to `export interface StreamToolCall {` (keep its body unchanged). Then, immediately after the existing `isRecord` function, insert:

```ts
export interface StreamMessage {
  type?: string;
  role?: string;
  content?: unknown;
  tool_calls?: StreamToolCall[];
  tool_call_id?: string;
}

export function parseStreamMessage(data: unknown): StreamMessage | null {
  const raw = Array.isArray(data) ? data[data.length - 1] : data;
  return isRecord(raw) ? (raw as StreamMessage) : null;
}

export function isAssistantMessage(message: StreamMessage): boolean {
  return message.type === "ai" || message.role === "assistant";
}

export function isToolMessage(
  message: StreamMessage,
): message is StreamMessage & { tool_call_id: string } {
  return message.type === "tool" && typeof message.tool_call_id === "string";
}

export function readToolCalls(message: StreamMessage): StreamToolCall[] | null {
  const calls = message.tool_calls;
  return Array.isArray(calls) && calls.length > 0 ? calls : null;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && node --test tests/qa-stream-events.test.mjs`
Expected: all five tests PASS (3 pre-existing + 2 new).

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0. (No consumer changed yet; this confirms the new module code is well-typed.)

---

### Task 2: Consume the typed helpers in `useQaStream.ts` and add the no-`any` gate

**Files:**
- Modify: `frontend/src/components/qa/hooks/useQaStream.ts`
- Test: `frontend/tests/qa-structure.test.mjs`

**Interfaces:**
- Consumes: `parseStreamMessage`, `isAssistantMessage`, `isToolMessage`, `readToolCalls` from `../stream-events` (Task 1), plus the already-imported `appendPendingToolCalls`, `completeToolStep`, `readAssistantContent`, `readToolResult`, `replaceAssistantContent`.
- Produces: a `useQaStream.ts` with no `any`/`as any`, importing `parseStreamMessage`.

- [ ] **Step 1: Add the no-`any` source gate (failing)**

Append this test to `frontend/tests/qa-structure.test.mjs`. That file already defines an async `read(path)` helper that reads a file relative to `../src/components/qa/`, and imports `assert` from `node:assert/strict` and `test` from `node:test` — reuse them.

```js
test("useQaStream is fully typed and consumes the stream parser", async () => {
  const source = await read("hooks/useQaStream.ts");
  assert.doesNotMatch(source, /:\s*any\b/);
  assert.doesNotMatch(source, /\bas any\b/);
  assert.match(source, /parseStreamMessage/);
});
```

- [ ] **Step 2: Run the gate to verify it fails**

Run: `cd frontend && node --test tests/qa-structure.test.mjs`
Expected: the new test FAILS (source still contains `const data: any` and no `parseStreamMessage`); pre-existing tests still PASS.

- [ ] **Step 3: Extend the stream-events import**

In `frontend/src/components/qa/hooks/useQaStream.ts`, replace the existing import block:

```ts
import {
  appendPendingToolCalls,
  completeToolStep,
  readAssistantContent,
  readToolResult,
  replaceAssistantContent,
} from "../stream-events";
```

with:

```ts
import {
  appendPendingToolCalls,
  completeToolStep,
  isAssistantMessage,
  isToolMessage,
  parseStreamMessage,
  readAssistantContent,
  readToolCalls,
  readToolResult,
  replaceAssistantContent,
} from "../stream-events";
```

- [ ] **Step 4: Replace the `any`-based loop body**

In the same file, replace the entire `for await` loop body. Change:

```ts
      for await (const event of stream) {
        const data: any = event.data;
        const message = Array.isArray(data) ? data[data.length - 1] : data;
        if (!message) continue;

        if (
          (message.type === "ai" || message.role === "assistant") &&
          Array.isArray(message.tool_calls) &&
          message.tool_calls.length > 0
        ) {
          updateThreadHistory(activeId, (history) =>
            appendPendingToolCalls(history, assistantId, message.tool_calls),
          );
        }

        if (message.type === "tool" && message.tool_call_id) {
          const result = readToolResult(message.content);
          updateThreadHistory(activeId, (history) =>
            completeToolStep(
              history,
              assistantId,
              message.tool_call_id,
              result,
            ),
          );
        }

        if (message.type === "ai" || message.role === "assistant") {
          const chunk = readAssistantContent(message.content);
          if (chunk) {
            updateThreadHistory(activeId, (history) =>
              replaceAssistantContent(history, assistantId, chunk),
            );
          }
        }
      }
```

to:

```ts
      for await (const event of stream) {
        const message = parseStreamMessage(event.data);
        if (!message) continue;

        if (isAssistantMessage(message)) {
          const toolCalls = readToolCalls(message);
          if (toolCalls) {
            updateThreadHistory(activeId, (history) =>
              appendPendingToolCalls(history, assistantId, toolCalls),
            );
          }
        }

        if (isToolMessage(message)) {
          const result = readToolResult(message.content);
          updateThreadHistory(activeId, (history) =>
            completeToolStep(
              history,
              assistantId,
              message.tool_call_id,
              result,
            ),
          );
        }

        if (isAssistantMessage(message)) {
          const chunk = readAssistantContent(message.content);
          if (chunk) {
            updateThreadHistory(activeId, (history) =>
              replaceAssistantContent(history, assistantId, chunk),
            );
          }
        }
      }
```

- [ ] **Step 5: Run the gate to verify it passes**

Run: `cd frontend && node --test tests/qa-structure.test.mjs`
Expected: all tests PASS, including the new no-`any` gate.

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0. In particular, `message.tool_call_id` inside the `isToolMessage` block must type as `string` (the type guard narrowed it), satisfying `completeToolStep`'s `string` parameter.

---

### Task 3: Full verification and the implementation commit

**Files:**
- Review: all four files in the File Map.
- Commit: the frontend Phase 3B production and test changes.

**Interfaces:**
- Consumes: completed Tasks 1–2.
- Produces: one reviewed, verified implementation commit.

- [ ] **Step 1: Run the full frontend verification sequentially**

Do not run `tsc` concurrently with `next build` (both touch `.next/types`).

```bash
cd frontend
npm test
npx tsc --noEmit
npm run build
```

Expected: all `node:test` files pass (including the two new stream-events tests and the new structure gate); TypeScript exits 0; Next compiles and generates 11 pages including `/qa`.

- [ ] **Step 2: Audit for residual `any` in the touched files**

```bash
cd frontend
grep -nE ':\s*any\b|\bas any\b' src/components/qa/hooks/useQaStream.ts src/components/qa/stream-events.ts
```

Expected: no matches (exit code 1).

- [ ] **Step 3: Confirm scope — only the four planned files changed**

```bash
cd /Users/leon/fund-agent
git status --short
```

Expected: exactly `frontend/src/components/qa/stream-events.ts`, `frontend/src/components/qa/hooks/useQaStream.ts`, `frontend/tests/qa-stream-events.test.mjs`, and `frontend/tests/qa-structure.test.mjs` are modified. No `error: unknown` prop file, backend file, or SDK file appears.

- [ ] **Step 4: Stage and commit**

```bash
cd /Users/leon/fund-agent
git add frontend/src/components/qa/stream-events.ts \
  frontend/src/components/qa/hooks/useQaStream.ts \
  frontend/tests/qa-stream-events.test.mjs \
  frontend/tests/qa-structure.test.mjs
git commit -m "refactor: type langgraph stream messages in qa"
```

Expected: one implementation commit after the design (`d5b92d7`) commit. Do not push, merge, or open a PR.

---

## Self-Review Notes

- **Spec coverage:** §5.1 types/parser/predicates → Task 1; §5.2 useQaStream consumption → Task 2 Steps 3–4; §6 behavior equivalence preserved by the exact loop replacement in Task 2 Step 4; §7 tests → Task 1 Step 1 + Task 2 Step 1; §8 verification → Task 3 Step 1; §9 file list → File Map. §10 single commit → Task 3 Step 4.
- **Intended tightening** (`isToolMessage` requiring `string`) is covered by the `isToolMessage({ type: "tool", tool_call_id: 1 })` assertion in Task 1.
- **Type consistency:** `StreamToolCall`/`StreamMessage`/`parseStreamMessage`/`isAssistantMessage`/`isToolMessage`/`readToolCalls` names and signatures are identical across Tasks 1–2 and the spec.
