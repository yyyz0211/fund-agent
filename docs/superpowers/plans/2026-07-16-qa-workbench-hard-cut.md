# QA Workbench Hard Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `frontend/app/qa/page.tsx` 与 `frontend/src/lib/qa-thread-store.ts` 硬切换为 QA 领域组件、controller hooks、统一 storage 和可测试 stream 事件纯函数，同时保持全部现有行为。

**Architecture:** `QaWorkbench` 组合 health query、`useQaThreads` 和 `useQaStream`；线程与消息持久化统一由 `storage.ts` 管理，LangGraph 事件转换由 `stream-events.ts` 纯函数完成。route 只转发 `searchParams.prefill`，展示组件只接收 props。

**Tech Stack:** Next.js 14 App Router、React 18、TypeScript 5.5 strict、TanStack React Query 5、LangGraph SDK、Node `node:test`、TypeScript `transpileModule` + Node VM。

## Global Constraints

- 硬切换：删除 `frontend/src/lib/qa-thread-store.ts` 和 page 内旧实现，不保留 wrapper、re-export、弃用文件、兼容导入层或双实现。
- 三个 key 精确保持：`qa_threads_v1`、`qa_active_thread_v1`、`qa_thread_messages_v1`。
- localStorage 数据结构、thread ID、排序、active fallback、删除和历史更新行为不变。
- LangGraph URL、assistant、`ensureLangGraphThread`、`streamMode: "messages"`、tool-call 去重、ToolMessage replay 和 assistant content 替换语义不变。
- health query 继续使用 `queryKey: ["langgraph", "health"]`、`${LANGGRAPH_URL}/ok` 和 `retry: false`。
- URL `prefill` 只作为 input 首次初值，不在 prop 变化时同步。
- DOM、className、文案、Markdown/GFM、工具链接、截断长度、Enter/Shift+Enter 和按钮状态不变。
- 不新增 AbortController、重连、retry、resume、context、Zustand、测试框架或其他依赖。
- 展示组件不得导入 LangGraph、React Query、storage 或 controller hooks。
- 当前 backend 三个未提交修改不属于本次范围，不得暂存、修改或提交。
- 用户要求实现保持一个原子提交；Task 之间只做 RED/GREEN 检查点，Task 7 才创建实现提交。
- 实施基线（2026-07-16）：84 tests PASS，`npx tsc --noEmit` PASS，`npm run build` PASS，11 个页面生成成功。

---

## File Map

**Create**

- `frontend/src/components/qa/index.ts`
- `frontend/src/components/qa/QaWorkbench.tsx`
- `frontend/src/components/qa/types.ts`
- `frontend/src/components/qa/storage.ts`
- `frontend/src/components/qa/stream-events.ts`
- `frontend/src/components/qa/hooks/useQaThreads.ts`
- `frontend/src/components/qa/hooks/useQaStream.ts`
- `frontend/src/components/qa/ThreadSidebar.tsx`
- `frontend/src/components/qa/ServiceStatusCard.tsx`
- `frontend/src/components/qa/MessageList.tsx`
- `frontend/src/components/qa/ChatMessage.tsx`
- `frontend/src/components/qa/ToolStepList.tsx`
- `frontend/src/components/qa/Composer.tsx`
- `frontend/tests/qa-structure.test.mjs`
- `frontend/tests/qa-storage.test.mjs`
- `frontend/tests/qa-stream-events.test.mjs`

**Modify**

- `frontend/app/qa/page.tsx`
- `frontend/tests/qa-layout.test.mjs`

**Delete**

- `frontend/src/lib/qa-thread-store.ts`
- `frontend/tests/qa-thread-store.test.mjs`

---

### Task 1: 建立 QA 硬切换 RED 门禁

**Files:**

- Create: `frontend/tests/qa-structure.test.mjs`
- Create: `frontend/tests/qa-storage.test.mjs`
- Create: `frontend/tests/qa-stream-events.test.mjs`
- Modify: `frontend/tests/qa-layout.test.mjs`
- Delete later: `frontend/tests/qa-thread-store.test.mjs`

**Interfaces:**

- Consumes: 当前 page/store 和 Node 原生测试工具。
- Produces: 新目录、公开入口、storage、stream 纯函数和 layout 内容契约。

- [ ] **Step 1: 编写结构契约**

`qa-structure.test.mjs` 必须检查：

```js
const required = [
  "index.ts", "QaWorkbench.tsx", "types.ts", "storage.ts", "stream-events.ts",
  "hooks/useQaThreads.ts", "hooks/useQaStream.ts", "ThreadSidebar.tsx",
  "ServiceStatusCard.tsx", "MessageList.tsx", "ChatMessage.tsx",
  "ToolStepList.tsx", "Composer.tsx",
];
```

测试断言：旧 store `fs.access` 必须以 ENOENT 拒绝；全部 required 文件存在；`index.ts`
精确等于以下两行；route 包含新入口且不包含 localStorage、LangGraph、React Query；展示文件
不包含禁止依赖。

```ts
export { QaWorkbench } from "./QaWorkbench";
export type { QaWorkbenchProps } from "./types";
```

- [ ] **Step 2: 迁移 storage 测试并先指向新路径**

复制现有三个 `qa-thread-store.test.mjs` 测试到 `qa-storage.test.mjs`，读取路径改为
`../src/components/qa/storage.ts`，保留 `normalize` 和 `makeStorage`。增加以下行为：

```js
assert.equal(QA_THREADS_STORAGE_KEY, "qa_threads_v1");
assert.equal(QA_ACTIVE_THREAD_STORAGE_KEY, "qa_active_thread_v1");
assert.equal(QA_THREAD_MESSAGES_STORAGE_KEY, "qa_thread_messages_v1");
saveThreads([{ id: "t1", title: "问题", updatedAt: "2026-07-16T00:00:00.000Z" }], storage);
assert.deepEqual(normalize(loadThreads(storage)), [
  { id: "t1", title: "问题", updatedAt: "2026-07-16T00:00:00.000Z" },
]);
saveActiveThreadId("t1", storage);
assert.equal(loadActiveThreadId(storage), "t1");
saveActiveThreadId(null, storage);
assert.equal(loadActiveThreadId(storage), null);
```

- [ ] **Step 3: 编写 stream-events 纯函数测试**

`qa-stream-events.test.mjs` 使用同一 transpile + VM helper，覆盖：

```js
const history = [{
  id: "assistant-1", role: "assistant", content: "", ts: "2026-07-16", toolSteps: [],
}];
const once = appendPendingToolCalls(history, "assistant-1", [
  { id: "call-1", name: "get_latest_fund_nav", args: { fund_code: "110011" } },
]);
const twice = appendPendingToolCalls(once, "assistant-1", [
  { id: "call-1", name: "get_latest_fund_nav", args: { fund_code: "110011" } },
]);
assert.equal(twice[0].toolSteps.length, 1);
const done = completeToolStep(twice, "assistant-1", "call-1", "first");
const replay = completeToolStep(done, "assistant-1", "call-1", "second");
assert.equal(replay[0].toolSteps[0].result, "first");
assert.equal(readAssistantContent(["A", { text: "B" }]), "AB");
assert.equal(readToolResult({ ok: true }), JSON.stringify({ ok: true }));
assert.equal(replaceAssistantContent(history, "other", "ignored"), history);
```

- [ ] **Step 4: 迁移 layout 契约目标**

修改 `qa-layout.test.mjs`，把 workbench/test ID 与常用查询读取目标设为 `QaWorkbench.tsx` 或
`MessageList.tsx`，textarea 读取 `Composer.tsx`，“已查询的数据”读取 `ToolStepList.tsx`；
原四个断言全部保留，并增加 route 新入口断言。

- [ ] **Step 5: 验证 RED**

Run:

```bash
cd frontend
node --test tests/qa-structure.test.mjs tests/qa-storage.test.mjs tests/qa-stream-events.test.mjs tests/qa-layout.test.mjs
```

Expected: FAIL，仅因为新目录不存在、旧 store 仍存在和 route 仍为旧实现；不得出现测试语法错误。

---

### Task 2: 提取类型与统一 storage

**Files:**

- Create: `frontend/src/components/qa/types.ts`
- Create: `frontend/src/components/qa/storage.ts`
- Delete: `frontend/src/lib/qa-thread-store.ts`
- Delete: `frontend/tests/qa-thread-store.test.mjs`

**Interfaces:**

- Produces: `QaWorkbenchProps`、`ThreadMeta`、`QaToolStep`、`QaUiMessage`、`StorageLike` 与完整 storage API。

- [ ] **Step 1: 定义领域类型**

```ts
export interface QaWorkbenchProps { prefill?: string; }
export interface ThreadMeta { id: string; title: string; updatedAt: string; }
export interface QaToolStep {
  id: string; name: string; args: Record<string, unknown>; result?: string;
  status: "pending" | "done" | "error";
}
export interface QaUiMessage {
  id: string; role: "user" | "assistant"; content: string; ts: string;
  toolSteps: QaToolStep[];
}
```

- [ ] **Step 2: 合并 storage**

从旧 store 移动 message history 的运行时校验和读写函数，并从 page 移动 metadata/active
读写与 `newThreadId`。所有函数允许可选 `StorageLike`，以便 Node VM 测试：

```ts
export function loadThreads(storage?: StorageLike): ThreadMeta[];
export function saveThreads(threads: ThreadMeta[], storage?: StorageLike): void;
export function loadActiveThreadId(storage?: StorageLike): string | null;
export function saveActiveThreadId(id: string | null, storage?: StorageLike): void;
export function loadThreadHistories(storage?: StorageLike): Record<string, QaUiMessage[]>;
export function loadThreadHistory(id: string, storage?: StorageLike): QaUiMessage[];
export function saveThreadHistory(id: string, messages: QaUiMessage[], storage?: StorageLike): void;
export function removeThreadHistory(id: string, storage?: StorageLike): void;
export function newThreadId(): string;
```

`loadThreads` 继续只过滤具有 string `id/title` 的数组项；message history 继续进行完整运行时
过滤；message 写失败继续 catch，metadata/active 写语义不扩大 catch 范围。

- [ ] **Step 3: 删除旧 store/test 并验证 storage GREEN**

Run: `cd frontend && node --test tests/qa-storage.test.mjs`

Expected: 全部 storage tests PASS。

Run: `cd frontend && npx tsc --noEmit`

Expected: 当前 page 暂时因旧 import 删除而 FAIL；该失败是硬切换中间态，只允许缺少旧 store
import，Task 6 必须恢复全绿。若出现 storage 自身错误，立即修复。

---

### Task 3: 提取可测试 stream 事件函数

**Files:**

- Create: `frontend/src/components/qa/stream-events.ts`

**Interfaces:**

- Consumes: `QaUiMessage`。
- Produces: `readAssistantContent`、`readToolResult`、`appendPendingToolCalls`、`completeToolStep`、`replaceAssistantContent`。

- [ ] **Step 1: 实现内容规范化**

```ts
export function readAssistantContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content.map((item) =>
    typeof item === "string" ? item : isRecord(item) && typeof item.text === "string" ? item.text : "",
  ).join("");
}

export function readToolResult(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return readAssistantContent(content);
  return JSON.stringify(content ?? "");
}
```

- [ ] **Step 2: 实现不可变 history 更新**

`appendPendingToolCalls` 只更新目标 assistant；过滤已有 ID；新 step 使用 `args ?? {}` 和
`status: "pending"`。`completeToolStep` 在 step 已 done 时返回原 message；找不到 step 时不新增。
`replaceAssistantContent` 只替换目标 assistant content；若没有目标，返回原 history 引用。

- [ ] **Step 3: 验证 stream 纯函数 GREEN**

Run: `cd frontend && node --test tests/qa-stream-events.test.mjs`

Expected: 全部 PASS。

---

### Task 4: 提取线程与 streaming controller hooks

**Files:**

- Create: `frontend/src/components/qa/hooks/useQaThreads.ts`
- Create: `frontend/src/components/qa/hooks/useQaStream.ts`

**Interfaces:**

- `useQaThreads()` 返回 `threads/threadId/history` 和线程/历史操作。
- `useQaStream({ prefill, threadId, ensureActiveThread, upsertThread, updateThreadHistory })` 返回 `input/setInput/streaming/error/send/clearError`。

- [ ] **Step 1: 移动线程状态机**

`useQaThreads` 保留 `threadIdRef`。mount effect 使用 `loadThreads` 与 `loadActiveThreadId`；active
无效时按 `updatedAt` 降序选择第一个。`updateThreadHistory` 必须先 load、再 update、save，且
只有 `threadIdRef.current === id` 时 setHistory。

删除行为精确保持：删除 non-active 不切换；删除 active 且有剩余时切到 `next[0]`；删除最后
一个 active 时 `activateThread(null, [])`。

- [ ] **Step 2: 移动发送状态机**

`useQaStream` 初始化 `input` 为 `prefill ?? ""`，不添加同步 effect。`send` 从旧 page 第
202–325 行机械移动，并使用 Task 3 纯函数替换内联 map。调用顺序保持：ensure local thread →
upsert title → user/assistant placeholder → local history → LangGraph ensure → stream → catch → finally。

stream message 继续取 array 最后一项；tool calls、ToolMessage 和 AI content 的分支顺序不变。

- [ ] **Step 3: 检查 hook 边界**

Run:

```bash
cd frontend
rg -n "localStorage" src/components/qa/hooks/useQaStream.ts
rg -n "@/lib/langgraph|@tanstack/react-query" src/components/qa/hooks/useQaThreads.ts
```

Expected: 两个命令均无输出。

---

### Task 5: 移动纯展示组件

**Files:**

- Create: `frontend/src/components/qa/ThreadSidebar.tsx`
- Create: `frontend/src/components/qa/ServiceStatusCard.tsx`
- Create: `frontend/src/components/qa/MessageList.tsx`
- Create: `frontend/src/components/qa/ChatMessage.tsx`
- Create: `frontend/src/components/qa/ToolStepList.tsx`
- Create: `frontend/src/components/qa/Composer.tsx`

**Interfaces:**

- 展示组件只消费数据、状态和 callback props；不得持有领域/服务端状态。

- [ ] **Step 1: 移动 sidebar 与服务状态**

从旧 page 第 350–437 行移动线程卡片和状态卡片。`ThreadSidebar` props：

```ts
{ threads: ThreadMeta[]; activeThreadId: string | null;
  onNew: () => void; onSwitch: (id: string) => void; onDelete: (id: string) => void; }
```

`ServiceStatusCard` props：`loading`、`online`；assistant 与 URL 文案仍从 LangGraph 常量传入
props，不在展示组件导入 client 模块。

- [ ] **Step 2: 移动 messages 与 tool steps**

从旧 page 第 525–660 行移动 Markdown、tool list/item、truncate、chat message。工具白名单、
`extractFundCode`、open state 和 fund detail link 留在 `ToolStepList.tsx`。`MessageList` 负责
error、空状态、三条 suggestions 与 history map，不拥有 input/history state。

- [ ] **Step 3: 移动 composer**

从旧 page 第 485–516 行移动 form/textarea/buttons。props：

```ts
{ input: string; streaming: boolean; onInputChange: (value: string) => void;
  onSend: () => void; }
```

Enter/Shift+Enter、disabled、rows、placeholder、合规提示和 loading icon逐行保持。

- [ ] **Step 4: 验证展示依赖门禁**

Run:

```bash
cd frontend
rg -n "@/lib/langgraph|@tanstack/react-query|components/qa/storage|components/qa/hooks|\./storage|\./hooks" src/components/qa/ThreadSidebar.tsx src/components/qa/ServiceStatusCard.tsx src/components/qa/MessageList.tsx src/components/qa/ChatMessage.tsx src/components/qa/ToolStepList.tsx src/components/qa/Composer.tsx
```

Expected: 无输出。

---

### Task 6: 组合 QaWorkbench 并硬切换 route

**Files:**

- Create: `frontend/src/components/qa/QaWorkbench.tsx`
- Create: `frontend/src/components/qa/index.ts`
- Modify: `frontend/app/qa/page.tsx`

**Interfaces:**

- Consumes: Task 2–5 全部领域模块。
- Produces: `QaWorkbench({ prefill }: QaWorkbenchProps)` 唯一公开入口。

- [ ] **Step 1: 组合 hooks 与 health query**

`QaWorkbench` 保留 `"use client"`，先实例化 threads，再把 callbacks 传给 stream。health query
原样移动。组合 callback 精确保持 error 时机：new/switch 清除；delete 仅在删除 active 且
存在剩余 thread、触发切换时清除。

- [ ] **Step 2: 组合原 workbench DOM**

保留 PageHeader、`data-testid="qa-workbench"`、两栏 grid、sticky aside、conversation card 的
原 DOM/className。只以 Task 5 组件替换对应 JSX，不新增 wrapper DOM。

- [ ] **Step 3: 创建公开入口和薄 route**

`index.ts` 精确两行。`app/qa/page.tsx` 保留 `"use client"` 并只导入 `@/components/qa`、定义
原 searchParams type、返回 `<QaWorkbench prefill={searchParams.prefill} />`。

- [ ] **Step 4: 验证目标 GREEN**

Run:

```bash
cd frontend
node --test tests/qa-structure.test.mjs tests/qa-storage.test.mjs tests/qa-stream-events.test.mjs tests/qa-layout.test.mjs
npx tsc --noEmit
```

Expected: 目标测试全部 PASS，TypeScript PASS。

---

### Task 7: 完整验证、review 与原子实现提交

**Files:**

- Review: File Map 中所有 frontend 文件。

- [ ] **Step 1: 完整测试**

Run: `cd frontend && npm test`

Expected: 基线 84 个测试全部保留，新测试全部 PASS，0 fail。

- [ ] **Step 2: TypeScript 和生产构建**

Run: `cd frontend && npx tsc --noEmit`

Expected: PASS。

Run: `cd frontend && npm run build`

Expected: `Compiled successfully`，11 个页面生成，`/qa` 构建成功。

- [ ] **Step 3: 硬切换审计**

Run:

```bash
git diff --check
rg -n "@/lib/qa-thread-store|src/lib/qa-thread-store" frontend/app frontend/src
rg -n "@/lib/langgraph|@tanstack/react-query|components/qa/storage|components/qa/hooks|\./storage|\./hooks" frontend/src/components/qa/ThreadSidebar.tsx frontend/src/components/qa/ServiceStatusCard.tsx frontend/src/components/qa/MessageList.tsx frontend/src/components/qa/ChatMessage.tsx frontend/src/components/qa/ToolStepList.tsx frontend/src/components/qa/Composer.tsx
git status --short -- frontend/app/qa frontend/src/components/qa frontend/src/lib/qa-thread-store.ts frontend/tests
```

Expected: 两个 rg 均无输出；path-scoped status 只含 File Map 文件；backend 用户改动不在范围。

- [ ] **Step 4: 对照规格 review**

逐项比较 base 版本 page/store 与新模块：三个 storage key、初始化 fallback、排序、删除、
threadIdRef、stream 分支顺序、content 规范化、done replay、错误文字、health query、全部 JSX
文案/className/disabled 条件。发现偏差后修复并从 Step 1 重跑。

- [ ] **Step 5: 创建唯一原子实现提交**

```bash
git add frontend/app/qa/page.tsx frontend/src/components/qa \
  frontend/src/lib/qa-thread-store.ts frontend/tests/qa-layout.test.mjs \
  frontend/tests/qa-thread-store.test.mjs frontend/tests/qa-structure.test.mjs \
  frontend/tests/qa-storage.test.mjs frontend/tests/qa-stream-events.test.mjs
git diff --cached --check
git commit -m "refactor: hard cut qa workbench modules"
```

Expected: 一个提交包含 RED tests、新目录、route 切换和旧 store/test 删除；backend 文件保持未暂存。
