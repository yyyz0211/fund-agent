# QA Workbench 领域组件硬切换设计

**版本**：1.0

**日期**：2026-07-16

**状态**：已确认

## 1. 背景与目标

当前 `frontend/app/qa/page.tsx` 约 666 行，同时承担路由入口、线程元数据、active thread、
消息历史、localStorage、LangGraph 健康检查、stream 消费、工具调用去重、错误状态和全部
workbench UI。消息历史虽已部分提取到 `frontend/src/lib/qa-thread-store.ts`，但线程元数据与
active thread 仍留在页面，streaming 又直接修改持久化历史，导致页面级状态边界不清晰。

本次把 QA 页面硬切换为领域目录：线程与持久化进入 `useQaThreads`，LangGraph 发送和
streaming 进入 `useQaStream`，事件变换进入可测试纯函数，UI 进入纯展示组件，
`app/qa/page.tsx` 只保留路由参数转发。

迁移完成后删除 `frontend/src/lib/qa-thread-store.ts`，不保留 re-export、wrapper、弃用文件、
兼容导入层或双实现。三个 localStorage key、数据 schema、streaming 状态机、URL prefill、
布局、文案、样式和错误行为全部保持不变。

## 2. 范围

### 2.1 本次包含

- 新建 `frontend/src/components/qa/` 领域目录；
- 将线程元数据、active thread 和消息历史存储统一到 `storage.ts`；
- 将线程初始化、新建、切换、删除、排序和历史更新提取到 `useQaThreads`；
- 将 input、streaming、error、发送与 LangGraph stream 消费提取到 `useQaStream`；
- 将 stream 内容规范化和消息更新提取到 `stream-events.ts` 纯函数；
- 将 sidebar、服务状态、消息列表、消息卡片、工具步骤和 composer 拆成展示组件；
- 把 `app/qa/page.tsx` 变为薄路由入口；
- 迁移并加强 storage、streaming、结构和布局契约测试；
- 删除旧 store 和页面内旧实现。

### 2.2 本次不包含

- 不改变 LangGraph assistant、URL、thread ID 或 `streamMode`；
- 不改变消息事件的识别、文本规范化、tool-call ID 去重或 ToolMessage 回放语义；
- 不把 assistant chunk 从替换改为累加；
- 不新增 AbortController、取消发送、自动重连、retry、resume 或并发 stream；
- 不修复删除正在 streaming 的 thread 后可能被后续事件重新写入历史的既有竞态；
- 不改变 health query key、endpoint、retry 或在线状态判定；
- 不改变三个 localStorage key、消息/线程结构或迁移已有浏览器数据；
- 不新增统一 storage error toast；
- 不改变 PageHeader、布局、DOM、className、文案、按钮状态或响应式行为；
- 不改变 Markdown/GFM、工具详情、基金链接或截断长度；
- 不引入 context、reducer、Zustand、表单库或新的状态管理层；
- 不引入 React Testing Library、Vitest、jsdom 或其他依赖；
- 不在本阶段进行 React Query query-key factory 或 TypeScript 全局类型治理；
- 不修改 backend、LangGraph server、API 或数据库代码。

## 3. 方案决策

采用“领域 controller hooks + 纯事件函数 + 展示组件”的方式：

```text
frontend/src/components/qa/
├── index.ts
├── QaWorkbench.tsx
├── types.ts
├── storage.ts
├── stream-events.ts
├── hooks/
│   ├── useQaThreads.ts
│   └── useQaStream.ts
├── ThreadSidebar.tsx
├── ServiceStatusCard.tsx
├── MessageList.tsx
├── ChatMessage.tsx
├── ToolStepList.tsx
└── Composer.tsx
```

不采用以下方案：

1. **单一 `useQaController`**：移动快，但会把页面单体变成 hook 单体，线程、存储和
   streaming 仍无法独立理解与测试。
2. **展示组件自行管理状态**：局部自包含，但 active thread、history 与 streaming 更新会
   跨组件协调，最终需要 context 或重复状态，增加行为漂移风险。

## 4. 公开入口与硬切换

`frontend/src/components/qa/index.ts` 是唯一公开入口，只导出：

```ts
export { QaWorkbench } from "./QaWorkbench";
export type { QaWorkbenchProps } from "./types";
```

`frontend/app/qa/page.tsx` 保持现有 route props，并变为：

```tsx
"use client";

import { QaWorkbench } from "@/components/qa";

export default function QaPage({
  searchParams,
}: {
  searchParams: { prefill?: string };
}) {
  return <QaWorkbench prefill={searchParams.prefill} />;
}
```

硬切换完成后：

- `frontend/src/lib/qa-thread-store.ts` 不存在；
- `app/qa/page.tsx` 保留现有 `"use client"` 边界；
- `app/qa/page.tsx` 不含 localStorage、LangGraph、React Query 或展示实现；
- 仓库内不存在 `@/lib/qa-thread-store` 导入；
- 新目录不得导入旧 store；
- 不创建旧路径 wrapper 或 re-export；
- QA workbench 只有新目录一份实现。

## 5. 模块职责

### 5.1 `types.ts`

定义 QA 领域稳定类型：

- `QaWorkbenchProps`，只包含可选 `prefill`；
- `ThreadMeta`，保持 `id/title/updatedAt`；
- `QaToolStep`，保持 `id/name/args/result/status`；
- `QaUiMessage`，保持 `id/role/content/ts/toolSteps`。

本阶段不设计通用 chat DTO，不把 LangGraph SDK event 完整建模，也不扩散这些 UI 类型到
其他领域。

### 5.2 `storage.ts`

统一现有三个 key，值必须精确保持：

```ts
export const QA_THREADS_STORAGE_KEY = "qa_threads_v1";
export const QA_ACTIVE_THREAD_STORAGE_KEY = "qa_active_thread_v1";
export const QA_THREAD_MESSAGES_STORAGE_KEY = "qa_thread_messages_v1";
```

模块负责：

- `loadThreads` / `saveThreads`；
- `loadActiveThreadId` / `saveActiveThreadId`；
- `loadThreadHistories` / `loadThreadHistory`；
- `saveThreadHistory` / `removeThreadHistory`；
- `newThreadId`。

消息历史的 `StorageLike` 注入、运行时校验和写失败静默处理从旧 store 原样迁移。线程列表
损坏 JSON 继续返回空数组；active thread 无值继续返回 null。线程列表保存和 active thread
保存保持当前直接 localStorage 语义，不在结构迁移中新增 toast 或统一 catch。

### 5.3 `stream-events.ts`

只包含无 React、SDK、storage 或浏览器副作用的纯函数：

- 从 LangGraph message content 读取字符串；
- 将新 tool calls 追加为 pending steps，并按 ID 去重；
- 将 ToolMessage 对应 step 标记为 done；
- 已 done step 收到回放时保持原对象和原 result；
- 替换指定 assistant message 的 content；
- 非目标 assistant ID 的消息保持不变。

函数必须复刻当前事件语义，不进行协议重写。输入只定义实现所需的最小结构，Phase 3 再
统一 LangGraph DTO 与 unknown 收窄策略。

### 5.4 `useQaThreads`

该 hook 是线程和历史状态的唯一所有者，持有：

- `threads`；
- `threadId` 与 `threadIdRef`；
- `history`。

它提供：

- 初始化 metadata 和 active thread；
- `activateThread`；
- `upsertThread`；
- `switchThread`；
- `newThread`；
- `deleteThread`；
- `ensureActiveThread`；
- `updateThreadHistory`。

行为保持：

- active thread 有效时优先恢复；
- active 无效但有线程时按 `updatedAt` 选择最近一个；
- 新建线程立即保存空历史并以“新对话”登记；
- 第一次发送且无 thread 时创建 thread，再用问题前 24 字更新标题；
- 线程按 `updatedAt` 降序；
- 删除 active thread 后切换到剩余数组首项；无剩余时清空 active；
- async stream 通过 thread ID 更新原 thread；仅当前 `threadIdRef` 相等时刷新画面。

hook 不导入 LangGraph client、React Query 或 UI 组件。

### 5.5 `useQaStream`

该 hook 持有：

- `input`，初值为 `prefill ?? ""`；
- `streaming`；
- `error`。

它消费 `useQaThreads` 提供的 `threadId`、`ensureActiveThread`、`upsertThread` 和
`updateThreadHistory`，提供：

- `setInput`；
- `send`；
- `clearError`；
- `streaming/error`。

发送顺序保持：

1. trim 输入，空输入或 streaming 时返回；
2. 清除 error；
3. 确保 active thread 并更新标题；
4. 创建 user message 和空 assistant message；
5. 清空 input、设置 streaming；
6. 先写入本地历史；
7. 获取 client 并 `ensureLangGraphThread`；
8. 用 `streamMode: "messages"` 消费事件；
9. 通过 `stream-events.ts` 更新 tool steps 和 assistant content；
10. catch 时设置 error，并把同一错误文本写入 assistant message；
11. finally 清除 streaming。

`prefill` 只作为首次 state 初值；prop 后续变化时不自动覆盖用户输入。

### 5.6 `QaWorkbench`

负责：

- 保留 `"use client"` 边界；
- 实例化 `useQaThreads` 和 `useQaStream`；
- 保留 `queryKey: ["langgraph", "health"]`、`${LANGGRAPH_URL}/ok` 与 `retry: false`；
- 组合 PageHeader、两栏 workbench 和展示组件；
- 在 switch/new 组合回调以及删除 active 后切换剩余 thread 时，保持现有 error 清理时机；
- 计算服务状态文案和当前线程标题。

它不重新实现 storage 或 stream 事件算法。

### 5.7 展示组件

- `ThreadSidebar`：线程列表、新建、切换、删除和 metadata 展示；
- `ServiceStatusCard`：LangGraph 在线状态、assistant 和 URL；
- `MessageList`：error、空状态、常用查询和消息列表；
- `ChatMessage`：用户/助手气泡、时间、Markdown 和 tool steps；
- `ToolStepList`：工具步骤折叠、参数、返回、fund code badge 和详情链接；
- `Composer`：textarea、Enter/Shift+Enter、合规提示和发送按钮。

展示层不得导入：

- `@/lib/langgraph`；
- `@tanstack/react-query`；
- `./storage` 或 `../qa/storage`；
- controller hooks。

## 6. 状态与数据流

```text
searchParams.prefill
  → app/qa/page.tsx
  → QaWorkbench
      → useQaThreads（metadata + active + history + localStorage）
      → useQaStream（input + streaming + error + LangGraph events）
      → health query
  → presentational components
```

关键交互：

1. mount 时线程 hook 恢复 metadata、active thread 和消息历史；
2. suggestion 只设置 input；
3. send 确保 thread 存在并持久化 user/assistant 占位消息；
4. stream 每个事件都按 activeId 更新其原 thread 历史；
5. 如果用户已切到另一 thread，旧 stream 不覆盖当前 history；
6. streaming 是 workbench 级状态，切换后 composer 仍保持 disabled，直到原 stream 结束；
7. 新建和切换清除页面 error；删除 active 且存在剩余 thread 时因切换而清除 error；删除
   非 active thread 或最后一个 active thread 时保留当前 error；
8. health query 与聊天 stream 相互独立。

不引入第二份 history、派生 message cache 或跨页面 store。

## 7. Streaming 行为不变量

- `ensureLangGraphThread(activeId)` 发生在 `runs.stream` 之前；
- `client.runs.stream(activeId, LANGGRAPH_ASSISTANT, ...)` 参数不变；
- input message 仍为 `{ role: "human", content: question }`；
- `streamMode` 仍为 `"messages"`；
- array event 仍取最后一项；空 message 跳过；
- AI tool calls 只追加不存在的 ID，状态为 pending；
- ToolMessage content 的 string/array/object 规范化规则不变；
- ToolMessage 只更新已有对应 step；
- 已 done step 的回放不覆盖 result；
- assistant string/array content 提取规则不变；
- 非空 assistant chunk 替换 content，不做 append；
- catch 错误文本格式不变；
- `finally` 必须清除 streaming。

## 8. UI 行为不变量

- PageHeader eyebrow、标题、描述不变；
- `data-testid="qa-workbench"` 保留；
- workbench 宽度、高度、sticky sidebar 和响应式网格不变；
- thread active/inactive class、删除按钮 hover 和时间格式不变；
- “服务状态”、Assistant、URL 和 StatusPill 文案/颜色不变；
- 当前 thread 标题 fallback 为“新对话”；
- error StateBlock、常用查询和三条 suggestion 不变；
- 消息排序和 `streaming` prop 传递不变；
- Markdown 继续使用 `react-markdown` + `remark-gfm`；
- tool step 默认折叠，每个 item 独立持有 open；
- 带 fund code 的工具白名单不变；
- 参数预览截断 80，返回截断 4000；
- 基金详情链接继续 encode fund code；
- textarea rows、placeholder、Enter/Shift+Enter 行为不变；
- 发送 disabled 条件仍为 `!input.trim() || streaming`；
- 合规提示和 loading 图标不变。

## 9. 错误与并发语义

- health fetch 异常返回 false，不抛到页面；
- stream 任意异常由统一 catch 转成页面 error 和 assistant message；
- storage 损坏数据按现有规则过滤或降级为空；
- 消息历史保存失败不阻断内存 UI；
- 本次不新增 metadata storage error UI；
- 不取消切换前启动的 stream；
- 不允许 streaming 时再次发送；
- 删除 streaming thread 的既有竞态明确留给后续行为任务；
- 不新增跨 tab、跨窗口或多设备同步。

## 10. 测试策略

### 10.1 基线

实施前运行：

```bash
cd frontend
npm test
npx tsc --noEmit
npm run build
```

当前已知基线为 84 tests、TypeScript strict 和 production build 全绿。实施时必须重新记录
当时的实际基线。

### 10.2 RED 硬切换契约

新增 `qa-structure.test.mjs`，先验证失败：

- 旧 store 不存在；
- 新目录规定模块全部存在；
- app page 只通过新公开入口组合 workbench；
- `index.ts` 只公开 component 和 props type；
- 仓库无旧 import；
- 展示组件无 LangGraph、React Query、storage 或 controller hook 依赖；
- hooks 不导入旧 store。

### 10.3 Storage 行为测试

将 `qa-thread-store.test.mjs` 迁移为 `qa-storage.test.mjs`，现有断言不得删除或弱化，并新增：

- 三个 key 的精确值；
- metadata 保存/加载；
- active thread 保存/删除；
- corrupted metadata/history 降级；
- 删除单个 history 不影响其他 thread。

继续使用当前 TypeScript transpile + Node VM，不引入浏览器测试依赖。

### 10.4 Stream 纯函数测试

新增 `qa-stream-events.test.mjs` 覆盖：

- tool-call ID 去重；
- pending → done；
- done replay 保持 result；
- string/array content 规范化；
- assistant content 替换；
- 非目标 assistant 保持不变。

### 10.5 Layout 内容契约

迁移 `qa-layout.test.mjs` 的读取目标，保留：

- workbench test ID；
- textarea composer；
- “已查询的数据”；
- “常用查询”。

增加薄 route 与新公开入口断言。不得把原内容断言从测试中删除来让硬切换通过。

### 10.6 完整门禁

- `npm test`；
- `npx tsc --noEmit`；
- `npm run build`；
- `git diff --check`；
- 搜索旧 store、旧实现、兼容层和重复实现；
- 搜索展示层禁止依赖；
- 最终对照 baseline review streaming、storage 和 JSX 不变量。

## 11. 提交边界与回滚

交付分为三个提交：

1. QA workbench 硬切换设计规格；
2. QA workbench 实施计划；
3. 一个原子实现提交，包含 RED tests、领域目录、route 切换与旧 store/页面实现删除。

实现阶段的 RED/GREEN 检查点不单独提交。只有完整前端测试、TypeScript、production build、
硬切换门禁和最终 review 全部通过后才创建实现提交。

回滚整个实现提交即可恢复旧 page/store。本次没有 backend、数据库、API、依赖或
localStorage migration，现有未提交 backend 改动不纳入任何 QA 提交。

## 12. 完成标准

- QA workbench 唯一实现位于 `frontend/src/components/qa/`；
- `app/qa/page.tsx` 是只转发 prefill 的薄入口；
- 旧 store、旧导入、兼容层和双实现全部删除；
- threads、streaming、storage 和展示层依赖方向符合本设计；
- 三个 localStorage key 与数据结构不变；
- thread 初始化、新建、切换、删除和排序行为不变；
- LangGraph 发送、事件去重、内容替换、错误和 streaming 行为不变；
- DOM、className、文案、Markdown、tool details 和 composer 行为不变；
- storage、stream events、structure 和 layout 测试通过；
- 完整 frontend tests、TypeScript strict、production build 和结构门禁通过；
- 最终 diff 不包含 backend、API、依赖、业务算法或视觉调整。
