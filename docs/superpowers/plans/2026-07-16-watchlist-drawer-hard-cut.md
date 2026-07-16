# WatchlistDrawer Hard Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 1617 行 `WatchlistDrawer.tsx` 硬切换为领域 controller hooks 与纯展示 Tab 组成的目录，同时保持全部现有 UI、状态、请求、缓存、toast 和 polling 行为。

**Architecture:** `WatchlistDrawer.tsx` 只组合抽屉 shell、生命周期和各 controller；`useWatchlistDrawerState` 持有跨 Tab 草稿，`useWatchlistDrawerData` 持有查询与派生数据，四个 action hook 持有写操作。Tab 与 shared 组件只接收 props 并渲染，公开入口只从目录 `index.ts` 导出组件与 props 类型。

**Tech Stack:** Next.js 14 App Router、React 18、TypeScript 5.5 strict、TanStack React Query 5、Node `node:test`、TypeScript `transpileModule` + Node VM。

## Global Constraints

- 硬切换：删除 `frontend/src/components/WatchlistDrawer.tsx`，不保留 wrapper、re-export、弃用文件或旧导入兼容层。
- 纯结构迁移：DOM 语义、className、文案、可访问性属性、按钮状态、API payload、query key、enabled 条件、cache 更新、invalidate 顺序、toast 和回调顺序不变。
- 所有 controller hooks 在抽屉打开期间始终挂载；切换 Tab 不得丢失任何未提交草稿。
- 表单只在打开抽屉，或打开状态下 `row` / `prefillFundCode` 变化时重置，并回到 basic Tab。
- polling 固定每 1500ms、最多 120 次，terminal 状态仍为 `done/partial/failed/missing`。
- tabs/shared 不得导入 `@/lib/api`、`@tanstack/react-query` 或 `@/components/Toast`。
- 不新增依赖，不引入 reducer、context、Zustand、表单框架、RTL、Vitest、jsdom、query-key factory 或统一错误层。
- 用户要求实现保持一个原子提交，因此 Task 之间只做 RED/GREEN 检查点，不创建中间提交；Task 8 在全部门禁通过后一次提交实现。
- 实施前基线（2026-07-16）：`npm test` 为 76/76，`npx tsc --noEmit` 与 `npm run build` 均通过。

---

## File Map

**Create**

- `frontend/src/components/watchlist-drawer/index.ts`：唯一公开入口。
- `frontend/src/components/watchlist-drawer/types.ts`：props、Tab 和三类本地表单类型。
- `frontend/src/components/watchlist-drawer/form-state.ts`：表单默认值、row 转换、正数解析和本地日期纯函数。
- `frontend/src/components/watchlist-drawer/hooks/useWatchlistDrawerState.ts`：跨 Tab 本地状态、重置和字段 setter。
- `frontend/src/components/watchlist-drawer/hooks/useWatchlistDrawerData.ts`：四类查询、NAV 回填和 draft 派生。
- `frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts`：basic 保存和 preload polling。
- `frontend/src/components/watchlist-drawer/hooks/useTransactionActions.ts`：交易新增/删除。
- `frontend/src/components/watchlist-drawer/hooks/useInvestmentPlanActions.ts`：计划增删改、启停、编辑和 plan → pending。
- `frontend/src/components/watchlist-drawer/hooks/usePendingBuyActions.ts`：申购中新增、确认和取消。
- `frontend/src/components/watchlist-drawer/tabs/BasicTab.tsx`：基础资料表单。
- `frontend/src/components/watchlist-drawer/tabs/TransactionsTab.tsx`：交易列表和加仓表单。
- `frontend/src/components/watchlist-drawer/tabs/InvestmentPlansTab.tsx`：定投计划列表和表单。
- `frontend/src/components/watchlist-drawer/tabs/PendingBuysTab.tsx`：申购中列表、录入和确认。
- `frontend/src/components/watchlist-drawer/shared/AutoNavSummary.tsx`：NAV 状态与预计份额。
- `frontend/src/components/watchlist-drawer/shared/HoldingSnapshot.tsx`：当前持仓快照。
- `frontend/src/components/watchlist-drawer/shared/TabButton.tsx`：Tab 按钮。
- `frontend/src/components/watchlist-drawer/shared/CheckboxField.tsx`：复选字段。
- `frontend/src/components/watchlist-drawer/WatchlistDrawer.tsx`：抽屉容器与 controller 组合。
- `frontend/tests/watchlist-drawer-structure.test.mjs`：硬切换与依赖方向契约。
- `frontend/tests/watchlist-drawer-form-state.test.mjs`：纯表单函数测试。

**Modify**

- `frontend/tests/watchlist-drawer-pending.test.mjs`：把内容契约指向新领域文件，断言不弱化。
- `frontend/app/watchlist/page.tsx`：改用目录入口。
- `frontend/app/funds/[code]/page.tsx`：改用目录入口。

**Delete**

- `frontend/src/components/WatchlistDrawer.tsx`：新入口接管后删除旧单体。

---

### Task 1: 建立硬切换与纯函数 RED 门禁

**Files:**

- Create: `frontend/tests/watchlist-drawer-structure.test.mjs`
- Create: `frontend/tests/watchlist-drawer-form-state.test.mjs`
- Modify: `frontend/tests/watchlist-drawer-pending.test.mjs`

**Interfaces:**

- Consumes: 当前旧组件、两个生产消费者与 Node 原生测试工具。
- Produces: 新目录文件清单、唯一公开入口、依赖方向和 `form-state.ts` 导出契约。

- [ ] **Step 1: 编写结构硬切换测试**

创建 `frontend/tests/watchlist-drawer-structure.test.mjs`：

```js
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

const componentRoot = new URL("../src/components/watchlist-drawer/", import.meta.url);
const requiredFiles = [
  "index.ts", "WatchlistDrawer.tsx", "types.ts", "form-state.ts",
  "hooks/useWatchlistDrawerState.ts", "hooks/useWatchlistDrawerData.ts",
  "hooks/useWatchlistSave.ts", "hooks/useTransactionActions.ts",
  "hooks/useInvestmentPlanActions.ts", "hooks/usePendingBuyActions.ts",
  "tabs/BasicTab.tsx", "tabs/TransactionsTab.tsx",
  "tabs/InvestmentPlansTab.tsx", "tabs/PendingBuysTab.tsx",
  "shared/AutoNavSummary.tsx", "shared/HoldingSnapshot.tsx",
  "shared/TabButton.tsx", "shared/CheckboxField.tsx",
];

async function read(relativePath) {
  return fs.readFile(new URL(relativePath, componentRoot), "utf8");
}

test("watchlist drawer hard cut removes the legacy entry and creates every domain module", async () => {
  await assert.rejects(
    fs.access(new URL("../src/components/WatchlistDrawer.tsx", import.meta.url)),
    (error) => error?.code === "ENOENT",
  );
  await Promise.all(requiredFiles.map((path) => fs.access(new URL(path, componentRoot))));
});

test("watchlist drawer exposes one narrow public entry", async () => {
  const source = (await read("index.ts")).trim();
  assert.equal(source, [
    'export { WatchlistDrawer } from "./WatchlistDrawer";',
    'export type { WatchlistDrawerProps } from "./types";',
  ].join("\n"));
});

test("production consumers use the directory entry only", async () => {
  for (const path of ["../app/watchlist/page.tsx", "../app/funds/[code]/page.tsx"]) {
    const source = await fs.readFile(new URL(path, import.meta.url), "utf8");
    assert.match(source, /from "@\/components\/watchlist-drawer"/);
    assert.doesNotMatch(source, /@\/components\/WatchlistDrawer/);
  }
});

test("presentational modules cannot own api query or toast side effects", async () => {
  const paths = requiredFiles.filter((path) => path.startsWith("tabs/") || path.startsWith("shared/"));
  for (const path of paths) {
    const source = await read(path);
    assert.doesNotMatch(source, /@\/lib\/api|@tanstack\/react-query|@\/components\/Toast/);
  }
});

test("new hooks do not depend on the removed entry", async () => {
  const paths = requiredFiles.filter((path) => path.startsWith("hooks/"));
  for (const path of paths) {
    assert.doesNotMatch(await read(path), /@\/components\/WatchlistDrawer/);
  }
});
```

- [ ] **Step 2: 编写纯函数测试**

创建 `frontend/tests/watchlist-drawer-form-state.test.mjs`，沿用仓库的 TypeScript transpile + VM 模式：

```js
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

async function loadModule() {
  const path = "../src/components/watchlist-drawer/form-state.ts";
  const source = await fs.readFile(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  const context = { exports, module: { exports } };
  vm.runInNewContext(compiled, context, { filename: path });
  return context.module.exports;
}

function normalize(value) {
  return JSON.parse(JSON.stringify(value));
}

test("watchlist row maps to an editable form without null values", async () => {
  const { rowToWatchlistForm } = await loadModule();
  assert.deepEqual(
    normalize(rowToWatchlistForm({
      fund_code: "110011", note: null, is_holding: 1, is_focus: 0,
      holding_amount: 1200.5, buy_date: null,
    })),
    {
      fund_code: "110011", note: "", is_holding: true, is_focus: false,
      holding_amount: "1200.5", holding_date: "",
    },
  );
});

test("blank forms preserve fund prefill and exact empty fields", async () => {
  const { blankWatchlistForm, blankTransactionForm, blankPendingBuyForm } = await loadModule();
  assert.deepEqual(normalize(blankWatchlistForm("000001")), {
    fund_code: "000001", note: "", is_holding: false, is_focus: false,
    holding_amount: "", holding_date: "",
  });
  assert.deepEqual(normalize(blankTransactionForm()), { tx_date: "", amount: "", fee: "", note: "" });
  assert.deepEqual(normalize(blankPendingBuyForm()), { request_date: "", amount: "", fee: "", note: "" });
});

test("positive number parsing rejects empty zero negative and non numeric values", async () => {
  const { parsePositiveNumber } = await loadModule();
  assert.equal(parsePositiveNumber("10.25"), 10.25);
  for (const value of ["", "0", "-1", "not-a-number"]) {
    assert.equal(parsePositiveNumber(value), null);
  }
});
```

- [ ] **Step 3: 迁移 pending 内容契约的目标路径**

把 `frontend/tests/watchlist-drawer-pending.test.mjs` 的三个测试分别读取：

```js
const pendingTab = await fs.readFile(
  new URL("../src/components/watchlist-drawer/tabs/PendingBuysTab.tsx", import.meta.url),
  "utf8",
);
const plansTab = await fs.readFile(
  new URL("../src/components/watchlist-drawer/tabs/InvestmentPlansTab.tsx", import.meta.url),
  "utf8",
);
const planActions = await fs.readFile(
  new URL("../src/components/watchlist-drawer/hooks/useInvestmentPlanActions.ts", import.meta.url),
  "utf8",
);
```

原有断言全部保留：pending 文件仍匹配 `申购中`、`申购中金额不计入当前市值`、`pendingBuys`、`预计确认日`、`等待净值/刷新数据`、`确认份额`；plans/action 两份源码合并后仍匹配 `记录本次申购` 和 `startPendingBuyFromPlan`。

- [ ] **Step 4: 运行 RED 测试并确认失败原因**

Run:

```bash
cd frontend
node --test tests/watchlist-drawer-structure.test.mjs tests/watchlist-drawer-form-state.test.mjs tests/watchlist-drawer-pending.test.mjs
```

Expected: FAIL，仅因为新目录文件不存在、旧文件仍存在、消费者仍指向旧入口；不得出现测试语法错误。

---

### Task 2: 提取类型、纯函数与跨 Tab 状态

**Files:**

- Create: `frontend/src/components/watchlist-drawer/types.ts`
- Create: `frontend/src/components/watchlist-drawer/form-state.ts`
- Create: `frontend/src/components/watchlist-drawer/hooks/useWatchlistDrawerState.ts`

**Interfaces:**

- Consumes: `WatchlistRow`、`InvestmentPlanFormState`、`blankInvestmentPlanForm`。
- Produces: `WatchlistDrawerProps`、`Mode`、`WatchlistDrawerTab`、三类表单类型、六个纯函数和 `useWatchlistDrawerState({ open, row, prefillFundCode })`。

- [ ] **Step 1: 定义稳定类型**

在 `types.ts` 写入以下公开类型；把旧 `FormState` / `TxFormState` 名称显式改成领域名称，禁止 tabs 自己重复声明：

```ts
import type { WatchlistRow } from "@/types/api";

export interface WatchlistDrawerProps {
  row?: WatchlistRow | null;
  prefillFundCode?: string;
  open: boolean;
  onClose: () => void;
  onSaved?: (row: WatchlistRow) => void;
}

export type Mode = "add" | "edit";
export type WatchlistDrawerTab = "basic" | "transactions" | "plans" | "pending";

export interface WatchlistFormState {
  fund_code: string;
  note: string;
  is_holding: boolean;
  is_focus: boolean;
  holding_amount: string;
  holding_date: string;
}

export interface TransactionFormState {
  tx_date: string;
  amount: string;
  fee: string;
  note: string;
}

export interface PendingBuyFormState {
  request_date: string;
  amount: string;
  fee: string;
  note: string;
}
```

- [ ] **Step 2: 移动纯函数并通过目标测试**

在 `form-state.ts` 写入以下实现：

```ts
import type { WatchlistRow } from "@/types/api";
import type { PendingBuyFormState, TransactionFormState, WatchlistFormState } from "./types";

export function rowToWatchlistForm(row: WatchlistRow): WatchlistFormState {
  return {
    fund_code: row.fund_code,
    note: row.note ?? "",
    is_holding: !!row.is_holding,
    is_focus: !!row.is_focus,
    holding_amount: row.holding_amount?.toString() ?? "",
    holding_date: row.buy_date ?? "",
  };
}

export function blankWatchlistForm(fundCode = ""): WatchlistFormState {
  return {
    fund_code: fundCode,
    note: "",
    is_holding: false,
    is_focus: false,
    holding_amount: "",
    holding_date: "",
  };
}

export function blankTransactionForm(): TransactionFormState {
  return { tx_date: "", amount: "", fee: "", note: "" };
}

export function blankPendingBuyForm(): PendingBuyFormState {
  return { request_date: "", amount: "", fee: "", note: "" };
}

export function parsePositiveNumber(value: string): number | null {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return null;
  return number;
}

export function todayInputValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}
```

Run: `cd frontend && node --test tests/watchlist-drawer-form-state.test.mjs`

Expected: PASS（3 tests）。

- [ ] **Step 3: 提取状态 hook**

`useWatchlistDrawerState.ts` 必须初始化并返回现有全部 state 与 setter：

```ts
export function useWatchlistDrawerState({
  open, row, prefillFundCode,
}: Pick<WatchlistDrawerProps, "open" | "row" | "prefillFundCode">) {
  const [form, setForm] = useState<WatchlistFormState>(() =>
    row ? rowToWatchlistForm(row) : blankWatchlistForm(prefillFundCode ?? ""));
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<WatchlistDrawerTab>("basic");
  const [txForm, setTxForm] = useState<TransactionFormState>(blankTransactionForm);
  const [txFormOpen, setTxFormOpen] = useState(false);
  const [pendingForm, setPendingForm] = useState<PendingBuyFormState>(blankPendingBuyForm);
  const [pendingFormOpen, setPendingFormOpen] = useState(false);
  const [confirmDates, setConfirmDates] = useState<Record<number, string>>({});
  const [planForm, setPlanForm] = useState<InvestmentPlanFormState>(blankInvestmentPlanForm);
  const [editingPlanId, setEditingPlanId] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(row ? rowToWatchlistForm(row) : blankWatchlistForm(prefillFundCode ?? ""));
    setActiveTab("basic");
    setTxForm(blankTransactionForm());
    setTxFormOpen(false);
    setPendingForm(blankPendingBuyForm());
    setPendingFormOpen(false);
    setConfirmDates({});
    setPlanForm(blankInvestmentPlanForm());
    setEditingPlanId(null);
  }, [open, row, prefillFundCode]);

  return {
    form, setForm, submitting, setSubmitting, activeTab, setActiveTab,
    txForm, setTxForm, txFormOpen, setTxFormOpen,
    pendingForm, setPendingForm, pendingFormOpen, setPendingFormOpen,
    confirmDates, setConfirmDates, planForm, setPlanForm,
    editingPlanId, setEditingPlanId,
    setField, setTxField, setPendingField, setPlanField,
  };
}
```

字段 helper 必须继续使用函数式更新：

```ts
function setField<K extends keyof WatchlistFormState>(key: K, value: WatchlistFormState[K]) {
  setForm((prev) => ({ ...prev, [key]: value }));
}
```

对另外三类表单使用相同的泛型签名；不在该 hook 中调用 API、query client 或 toast。

- [ ] **Step 4: 运行类型检查点**

Run: `cd frontend && npx tsc --noEmit`

Expected: PASS；新模块可独立类型检查，旧组件尚未切换。

---

### Task 3: 提取查询、NAV 回填与派生数据

**Files:**

- Create: `frontend/src/components/watchlist-drawer/hooks/useWatchlistDrawerData.ts`

**Interfaces:**

- Consumes: `open`、`row`、`form`、`txForm`、`txFormOpen`、`activeTab`、`planForm`，以及 `setForm`、`setTxForm`、`setConfirmDates`。
- Produces: `mode`、Tab visibility、fund codes、holding guards、四个 query、三个 draft 和 `saveDisabled` 所需数据。

- [ ] **Step 1: 定义显式输入并移动查询**

```ts
interface UseWatchlistDrawerDataInput {
  open: boolean;
  row?: WatchlistRow | null;
  form: WatchlistFormState;
  txForm: TransactionFormState;
  txFormOpen: boolean;
  activeTab: WatchlistDrawerTab;
  planForm: InvestmentPlanFormState;
  setForm: Dispatch<SetStateAction<WatchlistFormState>>;
  setTxForm: Dispatch<SetStateAction<TransactionFormState>>;
  setConfirmDates: Dispatch<SetStateAction<Record<number, string>>>;
}
```

把旧组件从 `mode` 到三个 NAV/confirm-date effects 的逻辑移入 `useWatchlistDrawerData`。四个 query 必须保留原 key 与 enabled：

```ts
useQuery({
  queryKey: ["watchlistTransactions", fundCodeForTx],
  queryFn: () => api.watchlistTransactions(fundCodeForTx),
  enabled: showTxTab,
});
useQuery({
  queryKey: ["nav", currentFundCode, selectedNavDate],
  queryFn: () => api.nav(currentFundCode, selectedNavDate),
  enabled: shouldLoadLatestNav,
});
useQuery({
  queryKey: ["investmentPlans", fundCodeForTx],
  queryFn: () => api.investmentPlans(fundCodeForTx),
  enabled: showPlanTab && activeTab === "plans",
});
useQuery({
  queryKey: ["pendingBuys", fundCodeForTx],
  queryFn: () => api.pendingBuys(fundCodeForTx),
  enabled: showPendingTab && activeTab === "pending",
});
```

注意：设计表中的 transactions 说明以现有代码为准，即 `enabled: showTxTab`，本次不得趁迁移改成 active-Tab gating。

- [ ] **Step 2: 返回命名数据而非嵌套魔法对象**

返回至少以下字段，容器按原变量名消费：

```ts
return {
  mode, showTxTab, showPlanTab, showPendingTab, hasTabs,
  fundCodeForTx, currentFundCode, needsInitialHolding, isAlreadyHolding,
  txQuery, selectedNavQuery, plansQuery, pendingBuysQuery,
  initialHoldingDraft, txDraft, planDraft,
};
```

保持 effects 的“仅空值回填”条件与依赖数组，不在 data hook 中写 mutation、toast 或关闭抽屉。

- [ ] **Step 3: 运行类型检查点**

Run: `cd frontend && npx tsc --noEmit`

Expected: PASS。

---

### Task 4: 提取三个子域 action hooks

**Files:**

- Create: `frontend/src/components/watchlist-drawer/hooks/useTransactionActions.ts`
- Create: `frontend/src/components/watchlist-drawer/hooks/useInvestmentPlanActions.ts`
- Create: `frontend/src/components/watchlist-drawer/hooks/usePendingBuyActions.ts`

**Interfaces:**

- Consumes: `fundCodeForTx`、对应表单/draft/setter、query client 和 toast（hook 内获取）。
- Produces: 与旧容器同名的 mutations 和 handler，供展示 Tab 直接绑定。

- [ ] **Step 1: 提取交易 action**

```ts
export function useTransactionActions({
  fundCode, txDraft, selectedNavLoading, setTxForm, setTxFormOpen,
}: {
  fundCode: string;
  txDraft: AutoTransactionDraft | null;
  selectedNavLoading: boolean;
  setTxForm: Dispatch<SetStateAction<TransactionFormState>>;
  setTxFormOpen: Dispatch<SetStateAction<boolean>>;
}) {
  return { addTx, removeTx, submitTx };
}
```

从旧文件第 259–299 行提取 `addTx` / `removeTx` 两个完整 mutation，从第 599–610 行提取
`submitTx`。只做以下机械替换：`fundCodeForTx` → `fundCode`、`blankTxForm()` →
`blankTransactionForm()`；其余 `setQueryData`、五类 invalidate、表单清理、校验文案与 toast
顺序逐行保持。hook 内部调用 `useQueryClient()` 与 `useToast()`，不得从容器传入副作用对象。

- [ ] **Step 2: 提取计划 action**

```ts
export function useInvestmentPlanActions({
  fundCode, planDraft, planForm, editingPlanId, setPlanForm, setEditingPlanId,
  setActiveTab, setPendingForm, setPendingFormOpen,
}: {
  fundCode: string;
  planDraft: ReturnType<typeof validateInvestmentPlanDraft>;
  planForm: InvestmentPlanFormState;
  editingPlanId: number | null;
  setPlanForm: Dispatch<SetStateAction<InvestmentPlanFormState>>;
  setEditingPlanId: Dispatch<SetStateAction<number | null>>;
  setActiveTab: Dispatch<SetStateAction<WatchlistDrawerTab>>;
  setPendingForm: Dispatch<SetStateAction<PendingBuyFormState>>;
  setPendingFormOpen: Dispatch<SetStateAction<boolean>>;
}) {
  return {
    addPlan, updatePlan, removePlan, togglePlanStatus,
    editPlan, submitPlan, startPendingBuyFromPlan,
  };
}
```

从旧文件第 300–349 行提取四个 plan mutation，从第 563–598 行提取 `editPlan`、
`submitPlan` 和 `startPendingBuyFromPlan`。只把 `fundCodeForTx` 改为 `fundCode`，并从
`form-state.ts` 导入 `todayInputValue`。`startPendingBuyFromPlan` 必须继续先切换到 `pending`、
打开表单、用计划金额/备注预填，再发送 info toast。

- [ ] **Step 3: 提取 pending action**

```ts
export function usePendingBuyActions({
  fundCode, pendingForm, confirmDates, setPendingForm, setPendingFormOpen,
  setConfirmDates,
}: {
  fundCode: string;
  pendingForm: PendingBuyFormState;
  confirmDates: Record<number, string>;
  setPendingForm: Dispatch<SetStateAction<PendingBuyFormState>>;
  setPendingFormOpen: Dispatch<SetStateAction<boolean>>;
  setConfirmDates: Dispatch<SetStateAction<Record<number, string>>>;
}) {
  return { addPendingBuy, confirmPendingBuy, cancelPendingBuy, confirmPending };
}
```

从旧文件第 350–407 行提取三个 mutation，从第 547–554 行提取 `confirmPending`。只做
`fundCodeForTx` → `fundCode` 和 `blankPendingBuyForm` 导入路径调整。确认成功后保持 watchlist
cache patch、pending/transactions/watchlist/fundSummary/两类 PnL invalidation、confirm date
清理和 toast 顺序。

- [ ] **Step 4: 结构检查 action 层边界**

Run:

```bash
cd frontend
rg -n "function (submitTx|editPlan|submitPlan|startPendingBuyFromPlan|confirmPending)|const (addTx|removeTx|addPlan|updatePlan|removePlan|togglePlanStatus|addPendingBuy|confirmPendingBuy|cancelPendingBuy)" src/components/watchlist-drawer/hooks
npx tsc --noEmit
```

Expected: 每个 handler/mutation 只出现在对应 action hook；TypeScript PASS。

---

### Task 5: 移动纯展示 Tabs 与 shared 组件

**Files:**

- Create: `frontend/src/components/watchlist-drawer/tabs/BasicTab.tsx`
- Create: `frontend/src/components/watchlist-drawer/tabs/TransactionsTab.tsx`
- Create: `frontend/src/components/watchlist-drawer/tabs/InvestmentPlansTab.tsx`
- Create: `frontend/src/components/watchlist-drawer/tabs/PendingBuysTab.tsx`
- Create: `frontend/src/components/watchlist-drawer/shared/AutoNavSummary.tsx`
- Create: `frontend/src/components/watchlist-drawer/shared/HoldingSnapshot.tsx`
- Create: `frontend/src/components/watchlist-drawer/shared/TabButton.tsx`
- Create: `frontend/src/components/watchlist-drawer/shared/CheckboxField.tsx`

**Interfaces:**

- Consumes: 现有 JSX、领域表单类型、API response 类型和 callback props。
- Produces: 八个无 API/query/toast 副作用的命名导出展示组件。

- [ ] **Step 1: 移动四个 shared 组件**

将旧文件第 892–989 行的 `TabButton`、`HoldingSnapshot`、`AutoNavSummary`（包括内部
`SummaryItem`）与第 1586–1617 行的 `CheckboxField` 分别移动到同名文件。保留完整 props、
JSX、DOM 层级、className 和文案，只补齐 import 并添加命名导出：

```ts
export function TabButton({
  active, onClick, children,
}: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      className={cn(
        "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition",
        active
          ? "border-blue-600 text-blue-700"
          : "border-transparent text-gray-500 hover:text-gray-700",
      )}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}
```

- [ ] **Step 2: 移动三个现有领域 Tab**

把旧文件第 990–1172 行的 `TransactionsTab`、第 1173–1384 行的 pending helpers 与
`PendingBuysTab`、第 1385–1585 行的 `InvestmentPlansTab` 移入同名文件。props 结构和 JSX
逐行保持，只把 `TxFormState` 改为 `TransactionFormState` 并从 `../types` 导入；
`pendingStatusLabel` 留在 `PendingBuysTab.tsx`，`frequencyLabel` 留在
`InvestmentPlansTab.tsx`。

- [ ] **Step 3: 从容器基础 JSX 提取 BasicTab**

`BasicTab` 的 props 必须覆盖旧 basic 区块使用的全部值：

```ts
interface BasicTabProps {
  mode: Mode;
  row?: WatchlistRow | null;
  form: WatchlistFormState;
  isAlreadyHolding: boolean;
  needsInitialHolding: boolean;
  initialHoldingDraft: AutoTransactionDraft | null;
  selectedNav: NavPoint | undefined;
  selectedNavError: unknown;
  selectedNavLoading: boolean;
  onChangeField: <K extends keyof WatchlistFormState>(key: K, value: WatchlistFormState[K]) => void;
}
```

把旧 `(!hasTabs || activeTab === "basic")` 内部 JSX 原样放入该组件；fragment 外不增加布局元素。

- [ ] **Step 4: 执行展示层依赖门禁**

Run:

```bash
cd frontend
rg -n "@/lib/api|@tanstack/react-query|@/components/Toast" src/components/watchlist-drawer/tabs src/components/watchlist-drawer/shared
```

Expected: 无输出，exit 1 表示没有禁止依赖。

Run: `cd frontend && npx tsc --noEmit`

Expected: PASS。

---

### Task 6: 提取 basic 保存与 polling

**Files:**

- Create: `frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts`

**Interfaces:**

- Consumes: basic form、mode、holding guard/draft、NAV loading、`onSaved`、`onClose`、`submitting` setter。
- Produces: `submit` 与 `saveDisabled`。

- [ ] **Step 1: 移动缓存失效和 polling**

从旧文件第 408–455 行提取 `invalidateFundCaches` 与 `startPreloadPolling`。只把闭包依赖改为
hook 内部取得的 `qc` 和 `toast`，并保留：

```ts
const terminal = new Set(["done", "partial", "failed", "missing"]);
const maxAttempts = 120;
```

interval 继续由 `window.setInterval` 创建，并直接采用旧文件第 426–451 行的 async callback；
实施时不得改变 callback 分支，只允许移动位置。末尾 interval 参数必须仍为字面量 `1500`。

terminal、超时、查询异常的 clear/invalidate/toast 分支不得重排。

- [ ] **Step 2: 移动 submit 的四条保存路径**

```ts
export function useWatchlistSave(input: {
  mode: Mode;
  form: WatchlistFormState;
  submitting: boolean;
  setSubmitting: Dispatch<SetStateAction<boolean>>;
  needsInitialHolding: boolean;
  selectedNavLoading: boolean;
  initialHoldingDraft: AutoTransactionDraft | null;
  onSaved?: (row: WatchlistRow) => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const saveDisabled = input.submitting || (
    input.needsInitialHolding &&
    (input.selectedNavLoading || input.initialHoldingDraft == null)
  );
  return { submit, saveDisabled };
}
```

在 `saveDisabled` 前加入旧文件第 457–530 行的完整 `submit` 函数，将闭包变量改为上面
`input` 的同名字段，并将 `setSubmitting` 改为 `input.setSubmitting`。逐条核对 add 普通自选、
add initial holding、edit patch、edit convert-to-holding；成功顺序仍是 toast → `onSaved` →
preload info/polling → `onClose`，`finally` 清除 submitting。

- [ ] **Step 3: 运行源代码不变量搜索与类型检查**

Run:

```bash
cd frontend
rg -n "1500|maxAttempts = 120|done.*partial.*failed.*missing|onSaved|startPreloadPolling|onClose" src/components/watchlist-drawer/hooks/useWatchlistSave.ts
npx tsc --noEmit
```

Expected: 搜索命中 polling 常量、terminal、回调与关闭路径；TypeScript PASS。

---

### Task 7: 组合新容器并执行硬切换

**Files:**

- Create: `frontend/src/components/watchlist-drawer/WatchlistDrawer.tsx`
- Create: `frontend/src/components/watchlist-drawer/index.ts`
- Modify: `frontend/app/watchlist/page.tsx`
- Modify: `frontend/app/funds/[code]/page.tsx`
- Delete: `frontend/src/components/WatchlistDrawer.tsx`

**Interfaces:**

- Consumes: `useWatchlistDrawerState`、`useWatchlistDrawerData`、四个 action hooks、四个 Tabs 与 shared `TabButton`。
- Produces: props 完全不变的 `WatchlistDrawer` 目录入口。

- [ ] **Step 1: 组合全部 hooks，保持无条件调用顺序**

新容器顶部顺序固定为：state → data → transaction actions → plan actions → pending actions → save。所有 hooks 必须在 `if (!open) return null` 之前调用：

```ts
export function WatchlistDrawer(props: WatchlistDrawerProps) {
  const state = useWatchlistDrawerState({
    open: props.open,
    row: props.row,
    prefillFundCode: props.prefillFundCode,
  });
  const data = useWatchlistDrawerData({
    open: props.open,
    row: props.row,
    form: state.form,
    txForm: state.txForm,
    txFormOpen: state.txFormOpen,
    activeTab: state.activeTab,
    planForm: state.planForm,
    setForm: state.setForm,
    setTxForm: state.setTxForm,
    setConfirmDates: state.setConfirmDates,
  });
  const transactions = useTransactionActions({
    fundCode: data.fundCodeForTx,
    txDraft: data.txDraft,
    selectedNavLoading: data.selectedNavQuery.isLoading,
    setTxForm: state.setTxForm,
    setTxFormOpen: state.setTxFormOpen,
  });
  const plans = useInvestmentPlanActions({
    fundCode: data.fundCodeForTx,
    planDraft: data.planDraft,
    planForm: state.planForm,
    editingPlanId: state.editingPlanId,
    setPlanForm: state.setPlanForm,
    setEditingPlanId: state.setEditingPlanId,
    setActiveTab: state.setActiveTab,
    setPendingForm: state.setPendingForm,
    setPendingFormOpen: state.setPendingFormOpen,
  });
  const pending = usePendingBuyActions({
    fundCode: data.fundCodeForTx,
    pendingForm: state.pendingForm,
    confirmDates: state.confirmDates,
    setPendingForm: state.setPendingForm,
    setPendingFormOpen: state.setPendingFormOpen,
    setConfirmDates: state.setConfirmDates,
  });
  const save = useWatchlistSave({
    mode: data.mode,
    form: state.form,
    submitting: state.submitting,
    setSubmitting: state.setSubmitting,
    needsInitialHolding: data.needsInitialHolding,
    selectedNavLoading: data.selectedNavQuery.isLoading,
    initialHoldingDraft: data.initialHoldingDraft,
    onSaved: props.onSaved,
    onClose: props.onClose,
  });

  useEffect(() => {
    if (!props.open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !state.submitting) props.onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.open, props.onClose, state.submitting]);

  if (!props.open) return null;
}
```

紧接在 early return 后写入旧文件第 620–890 行的 return JSX：保留最外层 dialog、遮罩
button、aside、header、Tab bar、form、content 与 footer 的原嵌套结构；仅用下一步的四个
Tab 组件替换对应内容区块，不新增 `renderDrawerShell` 等间接渲染函数。

- [ ] **Step 2: 用展示组件替换容器内 JSX**

保持原条件：

四个组件仍使用旧容器第 693–878 行已有的完整 props 映射，只将变量来源机械替换为
`state.*`、`data.*`、`transactions.*`、`plans.*`、`pending.*`。渲染条件精确保持为：

```ts
!data.hasTabs || state.activeTab === "basic"
data.showTxTab && state.activeTab === "transactions"
data.showPlanTab && state.activeTab === "plans"
data.showPendingTab && state.activeTab === "pending"
```

遮罩、header、Tab bar、footer、Escape、关闭按钮与 `submitting` 期间禁止关闭的条件逐行保持。全部 action callback 从对应 hook 传入，不在容器重新实现 mutation。

- [ ] **Step 3: 创建唯一入口并切换消费者**

`index.ts` 必须精确为：

```ts
export { WatchlistDrawer } from "./WatchlistDrawer";
export type { WatchlistDrawerProps } from "./types";
```

两个页面都改为：

```ts
import { WatchlistDrawer } from "@/components/watchlist-drawer";
```

- [ ] **Step 4: 删除旧组件，不保留兼容文件**

使用 `apply_patch` 删除 `frontend/src/components/WatchlistDrawer.tsx`。随后运行：

```bash
cd frontend
rg -n "@/components/WatchlistDrawer|src/components/WatchlistDrawer" app src
```

Expected: 无输出。

- [ ] **Step 5: 运行结构与行为目标测试**

Run:

```bash
cd frontend
node --test tests/watchlist-drawer-structure.test.mjs tests/watchlist-drawer-form-state.test.mjs tests/watchlist-drawer-pending.test.mjs
```

Expected: 全部 PASS。

---

### Task 8: 完整验证、diff review 与原子实现提交

**Files:**

- Review: Task 1–7 的全部新增、修改和删除文件。

**Interfaces:**

- Consumes: 完整硬切换实现。
- Produces: 一个可回滚的实现提交，无兼容层或部分迁移。

- [ ] **Step 1: 运行完整前端测试**

Run: `cd frontend && npm test`

Expected: 84 tests PASS，0 fail（现有 76 个测试保留，新增 8 个结构/纯函数测试）；pending
原有 3 个测试与断言全部保留。

- [ ] **Step 2: 运行 strict TypeScript 与生产构建**

Run: `cd frontend && npx tsc --noEmit`

Expected: PASS，无输出。

Run: `cd frontend && npm run build`

Expected: `Compiled successfully`，11 个页面生成完成，`/watchlist` 与 `/funds/[code]` 构建成功。

- [ ] **Step 3: 执行硬切换与边界审计**

Run:

```bash
git diff --check
rg -n "@/components/WatchlistDrawer|src/components/WatchlistDrawer" frontend/app frontend/src
rg -n "@/lib/api|@tanstack/react-query|@/components/Toast" frontend/src/components/watchlist-drawer/tabs frontend/src/components/watchlist-drawer/shared
git status --short -- frontend/app frontend/src frontend/tests
git diff --stat -- frontend/app frontend/src frontend/tests
```

Expected: 两个 `rg` 均无输出；diff check 无错误；path-scoped status 只包含 File Map 中列出的
实现与测试文件。仓库中任何预先存在的 backend 或其他用户改动不属于本次审计和提交范围。

- [ ] **Step 4: 对照规格逐项 review**

检查 `docs/superpowers/specs/2026-07-16-watchlist-drawer-hard-cut-design.md` 第 7–11 节：

- Tab 可见性、草稿持久化与重置条件不变；
- query key/enabled、API payload、cache patch/invalidation 不变；
- toast 文案、错误路径、`onSaved` / polling / `onClose` 顺序不变；
- JSX 文案、className、disabled/pending 状态不变；
- 新目录之外没有业务修改。

发现偏差时先修复，再从 Step 1 重跑全部门禁。

- [ ] **Step 5: 创建唯一原子实现提交**

```bash
git add frontend/app/watchlist/page.tsx 'frontend/app/funds/[code]/page.tsx' \
  frontend/src/components/WatchlistDrawer.tsx \
  frontend/src/components/watchlist-drawer \
  frontend/tests/watchlist-drawer-structure.test.mjs \
  frontend/tests/watchlist-drawer-form-state.test.mjs \
  frontend/tests/watchlist-drawer-pending.test.mjs
git diff --cached --check
git commit -m "refactor: hard cut watchlist drawer modules"
```

Expected: 一个提交同时包含 RED 契约、新目录、消费者切换与旧文件删除；提交后 `git status --short` 无输出。
