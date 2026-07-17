# Phase 3A React Query 治理设计

**版本**：1.0

**日期**：2026-07-17

**状态**：已确认，待书面复核

## 1. 背景与目标

Phase 2 已完成 Repository、Services、Integrations、Briefing、Scheduler、WatchlistDrawer 和
QA Workbench 的领域硬切换。前端仍有以下状态治理问题：

- query key 以数组字面量分散在 page、component 和 hook 中；
- 同一个基金刷新操作在多个位置重复维护相同的 invalidation 列表；
- 全局和局部 query policy 没有统一的命名入口；
- Market refresh 与 Watchlist preload 使用手写 `setTimeout` / `setInterval` polling；
- key、polling 完成条件和失效边界主要依赖源码约定，缺少独立契约测试。

本阶段对整个前端进行一次 React Query 治理硬切换：所有 query、cache read 和 invalidation
统一使用 typed query key factory；明确当前有效 query policy；把两处手写 polling 迁移为由
React Query observer 驱动的领域 polling hook。

本阶段以行为兼容为主。现有 key 数组结构、prefix matching、缓存时长、retry、polling 间隔、
超时、完成判定、toast、按钮 pending 状态和最终 invalidation 保持不变。唯一有意行为修复是：
页面真正卸载时停止 polling，不再让裸定时器泄漏到其他页面继续请求或弹出 toast。

## 2. 范围

### 2.1 本次包含

- 建立整个前端唯一的 `queryKeys` factory；
- 一次替换全部 `useQuery`、`invalidateQueries`、`refetchQueries` 和 `getQueryData` key；
- 集中当前 Query Client 默认值和所有现有 refetch/polling 数值；
- 抽取无 React 副作用的 polling 完成判定；
- Market snapshot/evidence refresh 改为 mutation + query polling；
- Watchlist preload polling 从 `useWatchlistSave` 提取为独立领域 hook；
- 保留现有对外 hook 名称和页面调用方式；
- 增加 query key、结构边界和 polling 纯函数测试；
- 保留全量前端测试、TypeScript strict 和 production build 门禁。

### 2.2 本次不包含

- 不改变任何后端 API、请求参数、响应结构或 job 状态；
- 不改变 query key 数组的既有值或 prefix invalidation 语义；
- 不调整 staleTime、gcTime、retry、refetchInterval、polling interval 或 timeout；
- 不新增乐观更新、prefetch、SSR hydration 或持久化 query cache；
- 不引入 Zustand、Redux、全局 Background Job Provider 或通用任务注册表；
- 不引入 React Testing Library、Vitest、jsdom 或新依赖；
- 不治理 LangGraph event `any`、API error `unknown` 或 discriminated union；这些属于 Phase 3B；
- 不修改 backend、数据库、Scheduler 或现有三个未提交 backend 文件；
- 不顺带调整页面文案、toast、loading、disabled 或导航行为；
- 不让 polling 在页面卸载后继续运行。

## 3. 方案选择

采用“统一 key factory + 领域 polling hooks + 纯判定函数”。

未采用：

1. **只统一 key，保留手写 polling**：改动较小，但无法完成 Phase 3A 的 polling 治理目标，
   同一文件后续还要再次修改。
2. **全局 Background Job Provider**：可以跨路由继续 polling，但当前场景不足以支撑全局任务
   注册表的复杂度，并会保留现有裸定时器跨页面泄漏的错误生命周期。
3. **通用 `usePollingJob<T>`**：Market 的变化检测、失败继续规则和 Watchlist 的终态/toast
   差异较大，过早抽象会把领域分支塞入一个难以理解的通用 hook。

## 4. 文件与职责

### 4.1 新增文件

```text
frontend/src/lib/
├── query-keys.ts       # typed key factory，唯一数组 key 定义位置
├── query-policy.ts     # Query Client 默认值、局部 policy 和 polling 数值
└── polling.ts          # 完成、终态、超时等纯判定

frontend/src/components/watchlist-drawer/hooks/
└── useWatchlistPreloadPolling.ts

frontend/tests/
├── query-keys.test.mjs
├── query-structure.test.mjs
└── polling.test.mjs
```

### 4.2 修改范围

- `frontend/app/providers.tsx` 使用统一默认 policy；
- `frontend/app/**` 中所有 React Query key 消费者；
- `frontend/src/components/**` 中所有 React Query key 消费者；
- `frontend/src/lib/market.ts` 的 key、policy 和 refresh polling；
- `frontend/src/components/watchlist-drawer/hooks/useWatchlistSave.ts`；
- 与 Market、Watchlist 源码契约有关的现有测试。

不创建旧 key wrapper、第二套 constants 或兼容入口。

## 5. Query Key Factory

`frontend/src/lib/query-keys.ts` 是生产代码中唯一允许声明 React Query 数组 key 的文件。
所有 tuple 使用 `as const`，参数数组和对象保持调用方传入的现有结构。

工厂按领域组织，但不重写 key 的根名称：

```ts
export const queryKeys = {
  watchlist: {
    all: ["watchlist"] as const,
    transactions: (fundCode: string) =>
      ["watchlistTransactions", fundCode] as const,
    investmentPlans: (fundCode: string) =>
      ["investmentPlans", fundCode] as const,
    pendingBuys: (fundCode: string) =>
      ["pendingBuys", fundCode] as const,
    preloadJob: (fundCode: string, jobId: string) =>
      ["watchlistPreloadJob", fundCode, jobId] as const,
  },
  fund: {
    detail: (code: string) => ["fund", code] as const,
    navForFund: (code: string) => ["nav", code] as const,
    nav: (code: string, date: string) => ["nav", code, date] as const,
    navHistoryForFund: (code: string) => ["navHistory", code] as const,
    navHistory: (code: string, start: string | undefined) =>
      ["navHistory", code, start] as const,
    metrics: (code: string) => ["metrics", code] as const,
    summaryForFund: (code: string) => ["fundSummary", code] as const,
    summary: (code: string, period: string, start: string | undefined) =>
      ["fundSummary", code, period, start] as const,
    diagnosisForFund: (code: string) => ["fundDiagnosis", code] as const,
    diagnosis: (code: string, period: string) =>
      ["fundDiagnosis", code, period] as const,
    diagnosisRefreshJob: (code: string, jobId: string | null) =>
      ["fundDiagnosisRefreshJob", code, jobId] as const,
  },
  portfolio: {
    pnl: (codes: string[]) => ["portfolioPnl", codes] as const,
    pnlSeries: (params: {
      period: string;
      start: string;
      end: string;
      codes: string[];
    }) => ["portfolioPnlSeries", params] as const,
  },
  market: {
    all: ["market"] as const,
    latest: ["market", "latest"] as const,
    snapshots: ["market", "snapshot"] as const,
    snapshot: (date: string, type: string) =>
      ["market", "snapshot", date, type] as const,
    evidence: {
      all: ["market", "evidence"] as const,
      list: (date: string, category: string, limit: number) =>
        ["market", "evidence", date, category, limit] as const,
      refreshStatuses: ["market", "evidence", "refresh-status"] as const,
      refreshStatus: (briefType: string) =>
        ["market", "evidence", "refresh-status", briefType] as const,
    },
    refreshPolling: {
      snapshot: (date: string | undefined) =>
        ["marketRefreshPolling", "snapshot", date ?? ""] as const,
      evidence: (date: string) =>
        ["marketRefreshPolling", "evidence", date] as const,
    },
  },
  briefing: {
    all: ["briefing"] as const,
    latest: ["briefing", "latest"] as const,
    list: (limit: number) => ["briefing", "list", limit] as const,
    evidence: (date: string) => ["briefing", "evidence", date] as const,
  },
  compare: (codes: string[]) => ["compare", codes] as const,
  langgraph: {
    health: ["langgraph", "health"] as const,
  },
} as const;
```

实施前必须以源码实际参数类型校准 `period/start/end/jobId` 的 TypeScript 类型，但不得改变
tuple 的元素数量、顺序和值。类型校准不属于 key schema 变更。

### 5.1 Prefix 规则

- `queryKeys.market.all` 继续匹配全部 market query；
- `queryKeys.market.evidence.all` 继续同时匹配 evidence list 和 refresh status；
- `queryKeys.market.evidence.refreshStatuses` 只匹配 refresh status；
- `queryKeys.market.refreshPolling.*` 只标识 polling observer，不替代资源 cache key；
- `queryKeys.fund.summaryForFund(code)` 继续匹配该基金所有 period/start summary；
- `queryKeys.fund.navForFund(code)` 和 `navHistoryForFund(code)` 继续用于基金级失效；
- `queryKeys.portfolio.pnl([])` 与 `pnl([code])` 保持两个不同 cache entry；
- 不通过重新排列 key 来追求表面上的领域层级一致性。

## 6. Query Policy

`frontend/src/lib/query-policy.ts` 显式表达当前有效值。数值只移动，不优化。

全局默认值：

```ts
export const queryDefaults = {
  staleTime: 60_000,
  gcTime: 5 * 60_000,
  retry: 3,
  refetchOnWindowFocus: false,
} as const;
```

局部 policy：

| 用途 | staleTime | retry | refetch/polling |
|---|---:|---:|---:|
| Market snapshot/evidence | 5 分钟 | 1 | 无固定刷新 |
| Evidence refresh status | 5 秒 | 1 | 5 秒 |
| Briefing latest | 继承全局 | 继承全局 | 30 秒 |
| Fund diagnosis refresh job | 继承全局 | 继承全局 | active job 时 1 秒 |
| LangGraph health | 继承全局 | 0 (`false`) | 无固定刷新 |
| Market snapshot refresh | — | 复用资源 query | 4 秒，最多 30 秒 |
| Market evidence refresh | — | 复用资源 query | 3 秒，最多 60 秒 |
| Watchlist preload | — | 0 (`false`) | 1.5 秒，最多 120 次 |

`query-policy.ts` 导出命名 policy object；调用方不得重新写这些数值。`gcTime=5 分钟` 和
`retry=3` 是 TanStack Query 当前有效默认值，本次将其显式化，不改变运行行为。

## 7. Polling 纯函数

`frontend/src/lib/polling.ts` 不导入 React、QueryClient、toast 或 API client。它负责：

- snapshot baseline/latest 的 `trade_date` 比较，保持现有判定；
- evidence baseline/latest 的 `items ?? groups ?? null` 序列化比较；
- Watchlist preload 的 `done/partial/failed/missing` 终态判断；
- elapsed time 是否达到 timeout；
- preload attempt 是否达到 120 次。

不得“修复”当前 snapshot 在相同 `trade_date` 下通常等待到超时的行为；改变完成标识需要后端
提供稳定 revision/job status，属于独立行为设计。

## 8. Market Refresh 数据流

`useRefreshMarket(date?)` 和 `useRefreshEvidence(date)` 保留现有公开名称与 `mutate/isPending`
消费方式。

### 8.1 Snapshot

1. mutation 发送现有 POST，请求头和 URL 不变；
2. 成功时记录当前 query data baseline、开始时间并激活 polling；
3. polling observer 使用 `queryKeys.market.refreshPolling.snapshot(date)` 作为内部控制 key；
4. observer query function 每次通过 QueryClient refetch 原 snapshot key，并返回可比较 fingerprint；
5. active 时每 4 秒 refetch；
6. 单次失败沿用资源 query 的 retry，并在下一 interval 继续；
7. `trade_date` 变化或 30 秒到期时停止；
8. 停止后 invalidates `queryKeys.market.all`；
9. 对外 `isPending = mutation.isPending || pollingActive`。

未传 date 时继续以 snapshot prefix 为资源刷新/读取边界；内部控制 key 使用空字符串规范化
undefined。该路径和当前实现一样通常等待至 timeout，不新增 snapshot 资源 cache entry。

### 8.2 Evidence

流程与 snapshot 相同，内部控制 key 使用
`queryKeys.market.refreshPolling.evidence(date)`，但：

- key 精确为当前 date、空 category、limit 20 的 evidence list；
- baseline 和 latest 继续比较 `items ?? groups ?? null`；
- interval 为 3 秒，timeout 为 60 秒；
- polling 时继续刷新 post-market refresh status；
- 结束后继续失效 evidence all 和 refresh-status prefix。

Market mutation POST 失败仍由 mutation 暴露 error；polling 单次失败不新增 toast。

## 9. Watchlist Preload 数据流

新增 `useWatchlistPreloadPolling`，持有当前 preload job、attempt 和 active 状态。

1. `useWatchlistSave` 保存成功后保持现有 success/info toast 顺序；
2. 如响应含 preload job，将 job 交给 polling hook，然后关闭 drawer；
3. drawer 关闭只返回 `null`，组件和 hook 仍挂载，因此 polling 继续；
4. query key 使用 `queryKeys.watchlist.preloadJob(fundCode, jobId)`；
5. active 时每 1.5 秒调用现有 `api.watchlistPreloadJob`；
6. query 使用 `retry: false`，第一次请求异常立即停止；
7. `done/partial/failed/missing` 或第 120 次结果返回后停止；
8. 停止时执行与现有 `invalidateFundCaches` 等价的 key 失效；
9. `done/partial/failed` toast 文案和 tone 不变；`missing` 和非终态超限不新增 toast；
10. 请求异常继续显示 `同步状态查询失败：${String(error)}`；
11. 页面卸载时 observer 自动停止，不在其他路由继续 polling 或 toast。

`useWatchlistSave` 继续拥有表单校验、保存顺序、初始持仓路径和 close 时机；polling hook 不读取
表单、不提交保存 mutation。

## 10. Cache Invalidation

本阶段只把现有 invalidation 数组替换为 factory，不主动缩减列表。重复的基金 cache 失效可通过
小型纯 helper 复用，但 helper 必须接受 QueryClient 和 fund code，并逐项使用 `queryKeys`；不得
用过宽的根 key 替代现有精确列表。

以下行为保持：

- Watchlist save/transaction/pending buy 后更新相同 cache 集合；
- 单基金 refresh 同时失效 fund、NAV、history、metrics、summary、diagnosis 和两种 portfolio PnL；
- Briefing mutation 继续失效 briefing prefix；
- Market refresh 结束后继续执行现有 broad market/evidence invalidation；
- 不新增 mutation optimistic cache patch，也不删除现有 WatchlistTable optimistic update。

## 11. Hard-Cut Contract

迁移完成后：

- `query-keys.ts` 是生产源码唯一数组 query key 定义位置；
- `queryKey: [...]` 不得出现在其他 `frontend/app` 或 `frontend/src` 文件；
- QueryClient cache 方法不得直接接收数组字面量；
- 不存在旧 key constants、兼容 re-export 或双实现；
- `market.ts` 不再包含 polling `while`、polling `setTimeout`；
- `useWatchlistSave.ts` 不再包含 `setInterval` / `clearInterval`；
- 展示组件不接管 polling 状态机；
- backend 三个用户未提交文件保持未暂存、未提交。

## 12. 测试策略

### 12.1 Query key tests

`query-keys.test.mjs` 用 TypeScript `transpileModule` + Node VM 精确断言：

- 每个 factory 返回当前生产代码的原数组值；
- summary/nav/history/market/evidence prefix 是目标 key 的真实前缀；
- `portfolioPnl([])` 与 `portfolioPnl([code])` 不相等；
- preload job key 包含 fund code 和 job ID；
- 参数对象和 codes 数组没有被排序、复制成不同 schema 或改名。

### 12.2 Structure tests

`query-structure.test.mjs` 使用 TypeScript AST 扫描 `frontend/app` 和 `frontend/src`：

- 排除 `query-keys.ts` 本身；
- 禁止 `queryKey` property 使用数组字面量；
- 禁止 `getQueryData`、`setQueryData`、`invalidateQueries`、`refetchQueries`、
  `removeQueries` 和 `cancelQueries` 直接使用数组字面量；
- 禁止 `market.ts` 的 polling timer/while；
- 禁止 `useWatchlistSave.ts` 的 interval timer；
- 要求所有现有 React Query 消费文件导入 `queryKeys`。

### 12.3 Polling tests

`polling.test.mjs` 覆盖：

- snapshot 未变化、变化和 timeout；
- evidence items 变化、groups fallback 变化、相同内容；
- preload 四个终态和非终态；
- attempt 119/120 边界；
- policy 数值精确等于当前实现；
- polling query error 的 retry policy 分别为 Market 继续、Watchlist 立即结束。

### 12.4 Existing regression

更新现有 Market/Watchlist 源码契约测试，使其读取新 hook/key 入口，但不删除原有 UI、toast、
刷新与 invalidation 断言。最终运行：

```bash
cd frontend
npm test
npx tsc --noEmit
npm run build
```

实施前记录当前测试数；最终必须 0 fail，TypeScript 和 11 个 Next.js 页面 build 成功。

## 13. 验收标准

- [ ] 全部生产 query/cache key 来自 `queryKeys`；
- [ ] 所有 factory 生成的现有 key 值与迁移前一致；
- [ ] Query Client 默认 policy 显式化且运行值不变；
- [ ] 所有现有局部 stale/retry/refetch policy 数值不变；
- [ ] Market 不再使用手写 polling loop/timer；
- [ ] Watchlist preload 不再使用裸 interval；
- [ ] Market 按钮 pending、disabled 和完成 invalidation 时机保持；
- [ ] Watchlist preload 间隔、次数、终态、toast 和 invalidation 保持；
- [ ] drawer 关闭后 polling 继续，页面卸载后 polling 停止；
- [ ] 不新增依赖、Provider、全局任务 store 或 TypeScript Phase 3B 工作；
- [ ] query key、structure、polling 和既有前端测试全部通过；
- [ ] `npx tsc --noEmit` 和 production build 通过；
- [ ] 独立代码审查无 Critical/Important 未解决项；
- [ ] backend 用户修改未暂存、未提交。

## 14. 交付与提交边界

采用三个原子提交：

1. `docs: design react query governance`；
2. `docs: plan react query governance`；
3. `refactor: hard cut frontend query governance`。

实现阶段的 RED/GREEN 检查点不单独提交。实现提交只包含本设计列出的 frontend 文件和测试；
不推送、不合并、不创建 PR，继续保留当前 `refactore` 分支。
