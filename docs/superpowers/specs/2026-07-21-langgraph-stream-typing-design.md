# LangGraph 流式消息类型化设计（Phase 3B）

> 日期：2026-07-21
> 范围：前端 QA 流式消息类型治理，聚焦消除唯一的 `any`

## 1. 背景

QA 问答走 LangGraph SDK 的流式接口（`client.runs.stream(..., { streamMode: "messages" })`）。
SDK 版本 `0.0.10` 老旧，**不导出任何消息 / 事件类型**，`event.data` 本身无类型。
当前 `frontend/src/components/qa/hooks/useQaStream.ts` 用 `const data: any = event.data`
逃逸类型系统，随后裸读 `message.type / role / tool_calls / tool_call_id / content`。

这是整个前端**唯一**一处字面 `any`（`react-query-governance` 设计将其列为 Phase 3B 的遗留项）。
其余 `error: unknown` 是 React Query 的地道写法，且 API 错误解析（`parseError`）已在提交
`3b97a58` 完成，均不在本设计范围内。

## 2. 目标

- 消除 `useQaStream.ts` 中唯一的 `any`，用本地定义的类型化消息模型 + 运行时收窄替代。
- **严格保行为**：分支逻辑逐条等价，不重构控制流。
- 类型定义内聚到已拥有流式内容解析的 `stream-events.ts`。
- 加一条源码级硬门禁，防止 `any` 回流。

## 3. 非目标

- 不加依赖（SDK 不导出消息类型，本地手写）。
- 不动 `error: unknown` props（地道写法，范围外）。
- 不引入 API 错误的类型化模型 / 判别联合（属更大范围，已明确排除）。
- 不重构 `useQaStream` 控制流，只把裸读换成类型化帮助函数。
- 无后端改动；不动其它前端组件或 SDK。

## 4. 现状参照（改造目标循环）

`useQaStream.ts` 的流式循环当前为：

```ts
for await (const event of stream) {
  const data: any = event.data;
  const message = Array.isArray(data) ? data[data.length - 1] : data;
  if (!message) continue;

  // 分支 A：assistant 消息带 tool_calls → 挂 pending 步骤
  if (
    (message.type === "ai" || message.role === "assistant") &&
    Array.isArray(message.tool_calls) &&
    message.tool_calls.length > 0
  ) {
    updateThreadHistory(activeId, (history) =>
      appendPendingToolCalls(history, assistantId, message.tool_calls));
  }

  // 分支 B：tool 消息 → 完成对应步骤
  if (message.type === "tool" && message.tool_call_id) {
    const result = readToolResult(message.content);
    updateThreadHistory(activeId, (history) =>
      completeToolStep(history, assistantId, message.tool_call_id, result));
  }

  // 分支 C：assistant 消息 → 替换正文
  if (message.type === "ai" || message.role === "assistant") {
    const chunk = readAssistantContent(message.content);
    if (chunk) {
      updateThreadHistory(activeId, (history) =>
        replaceAssistantContent(history, assistantId, chunk));
    }
  }
}
```

## 5. 设计

### 5.1 `stream-events.ts` 新增

**类型**

```ts
// 已存在于本文件，改为 export 供 useQaStream 复用
export interface StreamToolCall {
  id: string;
  name: string;
  args?: Record<string, unknown>;
}

// LangGraph messages 模式下每个 chunk 的松散形状。字段全可选：SDK 不给类型，
// 且不同 chunk（ai / tool）字段集合不同。
export interface StreamMessage {
  type?: string;
  role?: string;
  content?: unknown;
  tool_calls?: StreamToolCall[];
  tool_call_id?: string;
}
```

**判别联合 vs 单接口的取舍**：真正的判别联合需要一个稳定判别字段，但现有运行时数据
用 `type === "ai"` **或** `role === "assistant"` 两条路识别 assistant，无法干净判别。
强行造联合会引入现实不存在的约束。因此选**单接口 + 类型化谓词**：既除掉 `any`，
又不虚构契约。

**解析函数**（复刻"数组取末元素 / 否则取对象 / 非 record→null"）

```ts
export function parseStreamMessage(data: unknown): StreamMessage | null {
  const raw = Array.isArray(data) ? data[data.length - 1] : data;
  return isRecord(raw) ? (raw as StreamMessage) : null;
}
```

- `isRecord` 已存在（`typeof === "object" && !== null && !Array.isArray`）。
- 空数组 → `data[-1] === undefined` → `isRecord(undefined) === false` → `null`。
- 字符串 / 数字等真值原始类型 → 非 record → `null`。

**三个类型化谓词**（一一对应旧分支条件）

```ts
export function isAssistantMessage(message: StreamMessage): boolean {
  return message.type === "ai" || message.role === "assistant";
}

export function isToolMessage(
  message: StreamMessage,
): message is StreamMessage & { tool_call_id: string } {
  return message.type === "tool" && typeof message.tool_call_id === "string";
}

// 保留 Array.isArray && length>0 门槛；不满足返回 null。
// 不做逐元素过滤——旧代码把整个数组原样交给 appendPendingToolCalls，
// 后者内部已有 args ?? {} 兜底。
export function readToolCalls(message: StreamMessage): StreamToolCall[] | null {
  const calls = message.tool_calls;
  return Array.isArray(calls) && calls.length > 0 ? calls : null;
}
```

### 5.2 `useQaStream.ts` 改造后循环

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

// ...

for await (const event of stream) {
  const message = parseStreamMessage(event.data);
  if (!message) continue;

  if (isAssistantMessage(message)) {
    const toolCalls = readToolCalls(message);
    if (toolCalls) {
      updateThreadHistory(activeId, (history) =>
        appendPendingToolCalls(history, assistantId, toolCalls));
    }
  }

  if (isToolMessage(message)) {
    const result = readToolResult(message.content);
    updateThreadHistory(activeId, (history) =>
      completeToolStep(history, assistantId, message.tool_call_id, result));
  }

  if (isAssistantMessage(message)) {
    const chunk = readAssistantContent(message.content);
    if (chunk) {
      updateThreadHistory(activeId, (history) =>
        replaceAssistantContent(history, assistantId, chunk));
    }
  }
}
```

- 分支 A 把 tool_calls 门槛嵌进 `if (toolCalls)`，等价于旧的三条 `&&`。
- 分支 B 的 `isToolMessage` 类型守卫把 `message.tool_call_id` 收窄成 `string`。
- 保留两个独立的 `isAssistantMessage(message)`（A 和 C），不合并，与旧结构逐行对应。

## 6. 行为等价对照

| 旧条件 | 新写法 | 等价性 |
|---|---|---|
| `Array.isArray(data)?data.at(-1):data; if(!message)` | `parseStreamMessage`（非 record→null） | 空数组 / 原始值两边都跳过；对象两边都进入 |
| `(type==="ai"‖role==="assistant") && Array.isArray(tool_calls) && length>0` | `isAssistantMessage && readToolCalls!==null` | 逐项拆分，合取不变 |
| `type==="tool" && tool_call_id` | `isToolMessage`（额外要求 `typeof===string`） | 非空字符串两边一致；`tool_call_id===""` 两边都跳过 |
| `type==="ai"‖role==="assistant"` | `isAssistantMessage` | 相同 |

**唯一有意的微收紧**：`isToolMessage` 要求 `tool_call_id` 是 `string`（旧代码只做真值判断）。
实践中 `tool_call_id` 恒为字符串，非字符串真值（数字 / 对象）不会出现；此收紧只增强类型
安全，不改变真实数据下的行为。

## 7. 测试

沿用现有 `node:test` + TS 转译 + VM 加载范式。

**扩展 `frontend/tests/qa-stream-events.test.mjs`**

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

**扩展 `frontend/tests/qa-structure.test.mjs`**（硬门禁）

```js
test("useQaStream is fully typed and consumes the stream parser", async () => {
  const source = await read("hooks/useQaStream.ts");
  assert.doesNotMatch(source, /:\s*any\b/);
  assert.doesNotMatch(source, /\bas any\b/);
  assert.match(source, /parseStreamMessage/);
});
```

（`read()` 对齐该文件已有的读源码辅助的真实签名。）

## 8. 验证命令

```bash
cd frontend
npm test          # node --test，含扩展后的 qa-* 用例
npx tsc --noEmit  # 确认无类型错误、无残留 any
npm run build     # 11 页照常生成
```

## 9. 改动文件清单

**修改**
- `frontend/src/components/qa/stream-events.ts`（+`StreamMessage` +`parseStreamMessage` +3 谓词，`StreamToolCall` 改 export）
- `frontend/src/components/qa/hooks/useQaStream.ts`（消费类型化帮助函数，消除 `any`）
- `frontend/tests/qa-stream-events.test.mjs`（+2 测试）
- `frontend/tests/qa-structure.test.mjs`（+1 硬门禁）

**不动**：后端、其它前端组件、`error: unknown` props、SDK。

## 10. 交付

一个实现提交（沿用项目 hard-cut 惯例）。
