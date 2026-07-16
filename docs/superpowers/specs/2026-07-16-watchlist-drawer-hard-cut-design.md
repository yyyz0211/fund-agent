# WatchlistDrawer 领域组件硬切换设计

**版本**：1.0

**日期**：2026-07-16

**状态**：已确认

## 1. 背景与目标

当前 `frontend/src/components/WatchlistDrawer.tsx` 约 1600 行，同时承担抽屉布局、四类
Tab、本地表单状态、React Query 查询、多类写操作、缓存更新、NAV 派生、预加载轮询、
toast 和错误展示。虽然交易、申购中和定投计划已经拥有独立业务 API，但前端仍通过一个
组件共享全部状态和副作用，导致修改任一子域都需要理解整份文件。

本次把 WatchlistDrawer 硬切换为领域目录：容器只负责组合和抽屉生命周期，状态、查询
与写操作进入 hooks，Tab 和共享组件只负责展示。迁移完成后删除旧
`frontend/src/components/WatchlistDrawer.tsx`，两个消费者直接导入新目录入口；不保留
re-export、弃用文件、兼容导入层或双实现。

本阶段是纯结构迁移。现有布局、文字、样式、Tab 可见性、表单重置、API 调用、query
key、缓存失效、toast、预加载轮询和保存顺序全部保持不变。

## 2. 范围

### 2.1 本次包含

- 将 WatchlistDrawer 移入 `frontend/src/components/watchlist-drawer/`；
- 提取表单类型、默认值、转换与基础校验纯函数；
- 提取跨 Tab 持久的本地状态 hook；
- 提取 React Query 查询与派生 draft hook；
- 按 basic、transactions、plans、pending 四个子域拆分写操作；
- 把 Basic、Transactions、Investment Plans 和 Pending Buys 拆成展示组件；
- 移动现有共享展示组件；
- 更新 watchlist 页面、fund detail 页面和 source-contract 测试；
- 增加硬切换、依赖方向和纯函数测试；
- 删除旧组件文件。

### 2.2 本次不包含

- 不改变抽屉宽度、DOM 结构语义、样式类、文案或可访问性属性；
- 不改变 add/edit、初始建仓、加仓、定投计划或待确认申购业务流程；
- 不新增、删除或重命名 API 调用；
- 不统一 query-key factory，也不调整 staleTime、gcTime、retry 或 refetch 策略；
- 不改变 query enabled 条件、cache set、invalidate 范围或调用顺序；
- 不改变 toast 文案、tone 或触发时机；
- 不修改 preload polling 的周期、次数或 terminal 状态；
- 不把表单状态改为 reducer、context、Zustand 或表单框架；
- 不引入 React Testing Library、Vitest、jsdom 或其他依赖；
- 不顺带拆分 `frontend/src/types/api.ts`；
- 不修正与本结构迁移无关的既有视觉、业务或性能问题。

## 3. 方案决策

采用“领域 controller hooks + presentational tabs”的拆分方式：

```text
frontend/src/components/watchlist-drawer/
├── index.ts
├── WatchlistDrawer.tsx
├── types.ts
├── form-state.ts
├── hooks/
│   ├── useWatchlistDrawerState.ts
│   ├── useWatchlistDrawerData.ts
│   ├── useWatchlistSave.ts
│   ├── useTransactionActions.ts
│   ├── useInvestmentPlanActions.ts
│   └── usePendingBuyActions.ts
├── tabs/
│   ├── BasicTab.tsx
│   ├── TransactionsTab.tsx
│   ├── InvestmentPlansTab.tsx
│   └── PendingBuysTab.tsx
└── shared/
    ├── AutoNavSummary.tsx
    ├── HoldingSnapshot.tsx
    ├── TabButton.tsx
    └── CheckboxField.tsx
```

不采用以下方案：

1. **单一 controller hook**：移动速度快，但会形成新的数百行 hook，只是把组件单体换成
   hook 单体。
2. **Tab 自己持有全部状态和请求**：局部自包含，但 Tab 切换造成卸载时可能清除未提交
   草稿，并使 query invalidation、toast 和跨 Tab 跳转分散。

## 4. 公开入口与硬切换

`frontend/src/components/watchlist-drawer/index.ts` 是唯一公开入口，只导出：

```ts
export { WatchlistDrawer } from "./WatchlistDrawer";
export type { WatchlistDrawerProps } from "./types";
```

两个生产消费者改为：

```ts
import { WatchlistDrawer } from "@/components/watchlist-drawer";
```

迁移完成后：

- `frontend/src/components/WatchlistDrawer.tsx` 不存在；
- 仓库内没有 `@/components/WatchlistDrawer` 导入；
- 新目录不得导入旧入口；
- 不创建同名 wrapper 或 re-export 文件。

外部 props 契约保持：`row`、`prefillFundCode`、`open`、`onClose` 和 `onSaved` 的可选性、
类型和回调时机不变。

## 5. 模块职责

### 5.1 `types.ts` 与 `form-state.ts`

`types.ts` 定义稳定的 UI 类型：

- `WatchlistDrawerProps`；
- `Mode`；
- `WatchlistDrawerTab`；
- `WatchlistFormState`；
- `TransactionFormState`；
- `PendingBuyFormState`。

`form-state.ts` 只包含无 React、API 或浏览器副作用的纯函数：

- `rowToWatchlistForm(row)`；
- `blankWatchlistForm(fundCode?)`；
- `blankTransactionForm()`；
- `blankPendingBuyForm()`；
- `parsePositiveNumber(value)`；
- `todayInputValue()`。

函数行为从旧组件原样移动。`todayInputValue` 继续按本地 timezone offset 生成
`YYYY-MM-DD`，不改成 UTC 日期或引入日期库。

### 5.2 `useWatchlistDrawerState`

该 hook 是跨 Tab 本地 UI 状态的唯一所有者，保存：

- basic form 与 `submitting`；
- `activeTab`；
- transaction form 与开关；
- pending form、开关和各记录 confirm date；
- investment plan form 与 editing plan ID。

它接收 `open`、`row` 和 `prefillFundCode`，并保持原重置契约：

- 只有抽屉打开，或打开状态下 row/prefill 输入变化时重置；
- 每次重置回到 basic Tab；
- 普通 Tab 切换不重置任何草稿；
- 所有字段 setter 继续使用函数式 state update；
- 从定投计划转为申购中时更新 pending 表单、打开 pending form 并切换 Tab。

hook 不调用 API、React Query 或 toast。

### 5.3 `useWatchlistDrawerData`

该 hook 统一读取现有四类 query，并计算只读派生状态：

- transactions；
- selected NAV；
- investment plans；
- pending buys；
- `mode`、Tab 可见性、当前 fund code；
- `needsInitialHolding`；
- initial-holding、transaction 和 plan draft；
- pending confirm date 默认回填；
- initial-holding/transaction NAV date 自动回填。

query key 和 enabled 条件保持：

| Query | Key | Enabled |
|---|---|---|
| transactions | `["watchlistTransactions", fundCode]` | 已保存且已持仓 |
| selected NAV | `["nav", currentFundCode, selectedNavDate]` | 需要初始建仓，或 transaction Tab 的新增表单已打开 |
| plans | `["investmentPlans", fundCode]` | 已保存且 plans Tab 激活 |
| pending | `["pendingBuys", fundCode]` | 已保存且 pending Tab 激活 |

hook 不执行写操作，不推送 toast，不关闭抽屉。

### 5.4 Action hooks

`useWatchlistSave` 负责基础保存、保存校验、`submitting` 生命周期、preload polling、
`onSaved` 和 `onClose`。它必须保持：

- 空 fund code、NAV loading 和无有效 initial draft 的现有错误提示；
- add 普通自选、add initial holding、edit patch、edit convert-to-holding 四条路径；
- set-initial-holding 后的 transaction/fund/PnL invalidation；
- 成功 toast、`onSaved`、preload toast/polling、`onClose` 的顺序；
- polling 每 1500ms 一次、最多 120 次；
- `done/partial/failed/missing` terminal 语义和查询失败处理；
- `finally` 中清除 submitting。

`useTransactionActions` 负责 add/remove mutation、transaction 表单提交校验、watchlist
cache patch、原 query invalidation、表单清理和 toast。

`useInvestmentPlanActions` 负责 add/update/remove/toggle、plan draft 校验、编辑状态切换、
从计划预填 pending form 的跨 Tab 动作，以及对应 toast/invalidation。

`usePendingBuyActions` 负责 add/confirm/cancel、正数与日期校验、confirm date 清理、
watchlist cache patch、transaction/fund/PnL invalidation 和 toast。

Action hooks 不渲染 JSX。为了纯结构迁移，本阶段允许不同 hook 保留当前重复的精确
invalidate 列表；query-key factory 与缓存策略统一留到 Phase 3。

### 5.5 Container 与展示组件

`WatchlistDrawer.tsx` 负责：

- open=false 时返回 null；
- 抽屉遮罩、header、Tab bar、content 和 footer 组合；
- Escape listener、遮罩关闭和关闭按钮；
- 提交期间阻止关闭；
- 实例化所有 hooks，使各 Tab 未提交状态在切换时保持；
- 把 controller 的 `state/data/actions` 显式传给 Tab。

`BasicTab`、`TransactionsTab`、`InvestmentPlansTab` 和 `PendingBuysTab` 只根据 props
渲染。`shared/` 组件继续保持现有 DOM、className、格式化函数与文案。

展示层不得导入：

- `@/lib/api`；
- `@tanstack/react-query`；
- `@/components/Toast`。

## 6. 状态与数据流

```text
WatchlistDrawer props
  → useWatchlistDrawerState（跨 Tab 本地状态）
  → useWatchlistDrawerData（query + drafts + visibility）
  → action hooks（API + cache + toast）
  → presentational tabs/shared components
```

关键交互保持：

1. 打开抽屉时 state hook 初始化所有表单并回到 basic；
2. data hook 根据 mode、row 和 active Tab 决定请求；
3. selected NAV 到达时只为空日期字段回填，不覆盖用户输入；
4. Tab 切换只改变 activeTab，所有 hook 始终挂载；
5. mutation 成功后按原顺序更新 cache、invalidate、清理局部表单并 toast；
6. basic 保存成功后调用外部 `onSaved`，必要时开始独立 polling，最后关闭抽屉；
7. polling 在抽屉关闭后继续按原行为运行，直到 terminal、超时或查询失败。

## 7. 行为不变量

- add/edit 标题、fund code 锁定、持仓/关注 checkbox 和提示文案不变；
- 已有 transaction 时不得重新走 initial-holding；
- Tab 名称、顺序、badge、可见条件和默认 active Tab 不变；
- 交易、计划、申购中 loading/error/empty 状态不变；
- 所有按钮 disabled/pending 文案不变；
- 初始持仓与加仓继续使用所选日期本地 NAV；
- 申购中金额继续不计入当前市值，确认后才写 transaction；
- 定投计划继续只保存规则，不自动扣款或生成交易；
- `record pending from plan` 的日期、金额、备注和 info toast 不变；
- formatDate、formatNav、formatMoney 和 className 使用不变；
- `onSaved` 仍只由 basic 保存成功触发；Tab mutation 不调用外部 `onSaved`；
- props、API payload、response 访问和 TypeScript strict 行为保持。

## 8. 错误处理

- 表单前置校验继续使用当前中文 toast，不改成 inline error；
- mutation `onError` 继续通过 `String(err)` 拼接现有文案；
- query error 继续交给对应 Tab 的 StateBlock；
- basic save 继续通过 try/catch/finally 管理 toast 与 submitting；
- polling 查询失败时继续停止 timer、invalidate fund caches 并提示错误；
- 单个 action hook 的失败不得重置其他 Tab 草稿；
- 不引入统一 exception 类型、错误边界组件或新的 retry。

## 9. 测试策略

### 9.1 基线

实施前记录：

```bash
cd frontend
npm test
npx tsc --noEmit
npm run build
```

三项必须全绿后才开始结构迁移。

### 9.2 RED 硬切换契约

新增 source/TypeScript AST 契约：

- 旧组件文件不存在；
- 两个消费者使用新目录入口；
- 规定的新模块全部存在；
- `index.ts` 只公开 component 与 props type；
- 仓库无旧 import；
- tabs/shared 不导入 API、React Query 或 Toast；
- hooks 不导入旧入口。

### 9.3 纯函数与现有行为契约

使用当前 TypeScript transpile + Node VM 工具测试 `form-state.ts`：

- row 转 basic form；
- blank basic/transaction/pending form；
- fund code prefill；
- 正数解析的有效与无效输入。

迁移 `watchlist-drawer-pending.test.mjs` 时保持现有断言：

- pending Tab 与市值免责声明位于 `PendingBuysTab.tsx`；
- T-day 状态文案保持；
- plan → pending 入口与动作仍存在于对应新模块。

不得删除或弱化现有内容断言来让硬切换通过。

### 9.4 编译与构建

- `node --test` 运行完整 frontend 测试；
- `npx tsc --noEmit` 验证 strict props/controller 契约；
- `npm run build` 验证 Next.js client boundary、alias、App Router 与生产打包；
- `git diff --check` 与全文搜索验证无旧路径、重复实现和临时兼容文件。

本次不新增可视变化，因此不要求引入截图基线或浏览器端 E2E 框架。

## 10. 提交边界与回滚

交付分为三个提交：

1. WatchlistDrawer 设计规格；
2. WatchlistDrawer 实施计划；
3. 一个原子实现提交，包含测试、新目录、消费者切换和旧文件删除。

实现阶段的 RED/GREEN 检查点不单独提交。只有 frontend 测试、TypeScript strict、
production build、硬切换门禁和最终 review 全部通过后才创建实现提交。

若无法同时保持 TypeScript 编译、现有行为契约和硬切换门禁，则不提交部分迁移。回滚
整个实现提交即可恢复旧组件；本次没有后端、数据库、API 或依赖变更。

## 11. 完成标准

- WatchlistDrawer 的唯一实现位于 `components/watchlist-drawer/`；
- 旧文件、旧 import、兼容层和双实现全部删除；
- container、state、data、actions、tabs 和 shared 的依赖方向符合本设计；
- 四类 Tab 草稿、查询、mutation、cache invalidation、toast 和 preload polling 行为保持；
- 两个生产消费者通过新入口编译；
- 完整 frontend tests、TypeScript strict、production build 和结构门禁通过；
- 最终 diff 不包含业务算法、视觉设计、API、query 策略或依赖调整。
