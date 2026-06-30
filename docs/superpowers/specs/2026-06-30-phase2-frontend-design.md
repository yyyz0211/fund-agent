# 第五阶段设计：Next.js 前端基础页面

> 阶段 2 / 6。前置依赖：阶段一（后端基础 + 薄 Agent，已完成）、阶段三（LangChain Tools，已完成）、阶段四（LangGraph QA，已完成）。
> 本阶段交付一个**只读 MVP 前端**：首页、自选基金、基金详情、公告占位页、QA 聊天。
> 公告 RAG、风险扫描、日报、写入操作、鉴权等留到后续阶段。

## 1. 目标

把阶段一/三/四已经完工的后端能力以网页形式呈现，让用户可以：

- 在首页看到主要指数行情与自选池概览
- 浏览自选池列表与每只基金的最新净值/阶段收益
- 查看单只基金的详情页（基础信息 + 净值曲线 + 阶段收益）
- 在 QA 页面与 Phase 4 的 LangGraph 流式对话（含来源/日期展示）
- 浏览公告列表（占位页，RAG 检索留到阶段 5）

不包含：

- 买入/卖出/加减仓等任何交易操作
- 自选池的增删改（写入操作延后）
- 用户登录、鉴权、多用户隔离（单用户本地应用）
- 公告摘要与 RAG 检索（阶段 5）
- 风险扫描、日报、推送（阶段 6）

## 2. 范围

**包含**：

- 新增 `backend/api/` —— FastAPI thin wrapper，直接调用现有的 `services/` 与 `graph/qa_graph`
- 新增 `frontend/` —— Next.js (App Router) + TypeScript + Tailwind + shadcn/ui
- 五个页面：`/`（首页）、`/watchlist`、`/funds/[code]`、`/announcements`（占位）、`/qa`
- Recharts 渲染净值曲线
- `@langchain/langgraph-sdk` 的 `useStream` 接 Phase 4 的 LangGraph Server
- `.env` 与 CORS 配置
- README 增补前端启动说明
- 离线 pytest 覆盖 API 路由 happy path

**不包含**：

- FastAPI 之外的自建问答协议（统一走 LangGraph Server）
- Next.js Server Components 之外的 SSR 数据获取策略（统一 CSR + TanStack Query 缓存）
- 任何写入 API（自选池写入仍走 CLI/Python 工具）
- 任何状态管理库（Redux/Zustand）；用 TanStack Query 即可
- e2e 测试（Playwright）—— 只做 API + 组件单测 + 手测

## 3. 核心约定

### 3.1 后端 API 层

- 新增 `backend/api/app.py`，FastAPI 实例，挂载路由。
- 新增 `backend/api/routes/`：
  - `funds.py`：`GET /api/funds/{code}`、`GET /api/funds/{code}/nav`、`GET /api/funds/{code}/nav-history`、`GET /api/funds/{code}/metrics`
  - `watchlist.py`：`GET /api/watchlist`
  - `market.py`：`GET /api/market/latest`
  - `announcements.py`：`GET /api/announcements?fund_code=&limit=`（阶段 5 接入 RAG 前先返回空列表 + 占位说明）
  - `qa.py`：不暴露新协议；前端直接连 LangGraph Server
- 每个路由是薄函数：参数校验 → 调用 service → 返回 dict（已是 JSON-ready）。
- 错误用 HTTP 状态码：`404`（基金不存在）、`400`（参数错误）、`502`（数据源错误）、`500`（其他）。
- 失败响应统一格式：`{"error": str, "detail"?: str}`。
- 启动方式：`.venv/bin/python -m uvicorn backend.api.app:app --reload --port 8000`。
- CORS：允许 `http://localhost:3000`（前端开发端口）。

### 3.2 前端栈

- Next.js 14 App Router、TypeScript strict、Tailwind CSS、shadcn/ui（Button/Card/Table/Input 等基础件）。
- TanStack Query 做数据获取与缓存。
- Recharts 做净值曲线（折线图）。
- `@langchain/langgraph-sdk/react` 的 `useStream` 钩子做 QA 流式。
- 包管理：`npm`；锁文件 `package-lock.json` 入仓。

### 3.3 环境变量

- 前端 `.env.local`：`NEXT_PUBLIC_API_BASE=http://localhost:8000`、`NEXT_PUBLIC_LANGGRAPH_URL=http://localhost:2024`（LangGraph dev 默认端口）、`NEXT_PUBLIC_LANGGRAPH_ASSISTANT=fund_agent`。
- 后端 `.env` 不变；新增 `CORS_ORIGINS=http://localhost:3000` 可选配置，默认写死。

### 3.4 类型共享

- Python service 返回 dict；前端通过 `frontend/src/types/api.ts` 定义对应 TS 类型，手动维护（避免 monorepo 复杂度）。
- Fund / Nav / Metrics / MarketIndex / Announcement 五个核心类型。

### 3.5 合规边界（前端 prompt）

- 页面顶部小字 disclaimer："本工具为公开信息整理助手，不构成投资建议。"
- QA 页面展示 `source` 与 `as_of`（后端字典里有这两个字段，前端必须原样展示）。
- 不展示"涨跌幅预测"、"推荐基金"、"买入信号"等文案。

## 4. API 契约（FastAPI thin）

| Method | Path | 返回（成功） | 失败 |
|--------|------|-------------|------|
| GET | `/api/funds/{code}` | `{fund_code, fund_name, fund_type, manager, company, source, as_of}` | 404 |
| GET | `/api/funds/{code}/nav` | `{fund_code, nav_date, accumulated_nav, source, as_of}` | 404 |
| GET | `/api/funds/{code}/nav-history?start=&end=` | `{fund_code, navs:[{nav_date, accumulated_nav, daily_return}], count, source, as_of}` | 404 |
| GET | `/api/funds/{code}/metrics?period=1m` | `{fund_code, period, period_return, max_drawdown, volatility, source, as_of}` 或 `{error, ...}` | 400/404 |
| GET | `/api/watchlist` | `[{fund_code, fund_name, fund_type, manager, latest_nav, nav_date, as_of}, ...]` | 200（空列表） |
| GET | `/api/market/latest` | `{rows:[{symbol, name, close, change_pct, market_date, source}], source, as_of}` | 502 |
| GET | `/api/announcements?fund_code=&limit=20` | `{announcements:[], note:"公告 RAG 检索将在阶段 5 接入"}` | 200 |

QA 流式**不**走 FastAPI；前端直接用 `useStream` 连 LangGraph Server，assistant=`fund_agent`。

## 5. 页面规范

### 5.1 首页 `/`

- 顶部：标题 "基金信息助手" + disclaimer 小字
- 主要指数卡片网格（上证指数、深证成指、创业板指等）
- 自选池概览表格（取 watchlist API 前 10 条，点击进入详情）
- "进入问答"按钮 → `/qa`

### 5.2 自选页 `/watchlist`

- 完整 watchlist 表格（基金代码/名称/最新净值/净值日期/操作）
- 顶部 search input（前端过滤，不打 API）
- 操作列只有"查看详情"链接（无编辑/删除，写入留到后续阶段）
- 空状态：提示 "请运行 `python -m backend.scripts.add_to_watchlist 110011` 添加基金"

### 5.3 详情页 `/funds/[code]`

- 顶部基础信息卡片（名称、类型、经理、公司）
- 净值曲线图（默认 1m，period selector 切换 1w/1m/3m/6m/1y）
- 阶段指标卡片网格（period_return / max_drawdown / volatility）
- "向助手提问此基金"按钮 → `/qa?prefill=110011 净值`

### 5.4 公告页 `/announcements`（占位）

- 标题 + 说明文字："公告 RAG 检索将在阶段 5 接入；当前展示空列表"
- 表格预留 columns：基金代码、标题、发布日期、摘要、链接
- 数据为空，显示 empty state

### 5.5 问答页 `/qa`

- 左侧聊天流（消息列表 + 输入框）
- 右侧 collapsible 面板：显示每条 AI 回答的 `source` 与 `as_of`
- 使用 `useStream({assistantId: "fund_agent", apiUrl: ...})`
- 输入框带 placeholder："试试：基金 110011 净值"
- 加载态：streaming cursor
- 错误态：网络错误 + LangGraph 错误分别提示

## 6. 文件结构

```
backend/
├── api/                           # 新增
│   ├── __init__.py
│   ├── app.py                     # FastAPI app + CORS + router 注册
│   ├── deps.py                    # session 注入
│   └── routes/
│       ├── __init__.py
│       ├── funds.py
│       ├── watchlist.py
│       ├── market.py
│       └── announcements.py
├── tests/
│   ├── test_api_funds.py          # 新增
│   ├── test_api_watchlist.py
│   ├── test_api_market.py
│   └── test_api_announcements.py
└── README.md                      # 增补 API 启动说明

frontend/                          # 新增
├── package.json
├── package-lock.json
├── tsconfig.json
├── next.config.mjs
├── tailwind.config.ts
├── postcss.config.mjs
├── components.json                # shadcn/ui config
├── .env.local.example
├── app/
│   ├── layout.tsx
│   ├── page.tsx                   # 首页
│   ├── watchlist/page.tsx
│   ├── funds/[code]/page.tsx
│   ├── announcements/page.tsx
│   ├── qa/page.tsx
│   └── providers.tsx              # QueryClient + StreamProvider
├── src/
│   ├── components/
│   │   ├── ui/                   # shadcn 生成
│   │   ├── NavChart.tsx          # Recharts 包装
│   │   ├── MetricCard.tsx
│   │   └── Disclaimer.tsx
│   ├── lib/
│   │   ├── api.ts                # fetch wrapper
│   │   └── format.ts             # 日期/百分比格式化
│   └── types/
│       └── api.ts                # Fund/Nav/Metrics/MarketIndex/Announcement
└── README.md                      # 新增
```

根目录 `README.md` 增补整体启动顺序（venv → init_db → 后端 uvicorn → langgraph dev → 前端 npm run dev）。

## 7. 测试策略

- **后端**：pytest 覆盖每个 API 路由 happy path + 主要错误路径（404 基金不存在、400 period 非法）。使用 `fastapi.testclient.TestClient`，service 层用 fake session 注入。
- **前端**：不写 e2e；可选 Vitest 覆盖 `format.ts` 与 `api.ts` 工具函数。组件渲染测试不写（依赖太重，ROI 低）。
- **手测 checklist**：README 列出 5 个页面的浏览器验证步骤。

## 8. LangGraph Server 接入

- 开发期：用户在两个终端分别跑 `langgraph dev`（端口 2024）和 `npm run dev`（端口 3000）
- 前端通过 `NEXT_PUBLIC_LANGGRAPH_URL` 连 LangGraph Server
- assistant 名称固定 `fund_agent`（与 `langgraph.json` 一致）
- 不做生产部署（生产留给后续阶段）

## 9. 验收标准

1. `uvicorn backend.api.app:app` 启动成功；Swagger UI 可访问 `/docs`。
2. 五个 API 路由 happy path 通过 pytest。
3. `npm run dev` 启动前端；首页能看到主要指数与自选池。
4. 详情页 Recharts 净值曲线能渲染（用 `refresh_fund` 拉过的真实数据）。
5. QA 页能通过 `useStream` 与 LangGraph Server 流式对话，AI 回答显示 `source` 与 `as_of`。
6. 自选池为空时，自选页与首页都有合理的 empty state 提示。
7. 公告页有 RAG 待接入说明。
8. 全量后端 pytest 通过（已有 96 + 新增约 12 = 108+）。
9. 根 README 给出端到端启动命令。

## 10. 新增依赖

**后端**（`backend/requirements.txt`）：

- `fastapi>=0.110`
- `uvicorn[standard]>=0.27`
- `pydantic>=2.5`（FastAPI 间接依赖，确认版本即可）

**前端**（`frontend/package.json`）：

- `next@14`、`react@18`、`react-dom@18`
- `typescript@5`、`tailwindcss@3`
- `@tanstack/react-query@5`
- `recharts@2`
- `@langchain/langgraph-sdk@0.6`（与后端 langgraph 同版本号段）
- `shadcn/ui` 通过 `components.json` + CLI 生成（运行时依赖 `class-variance-authority`、`clsx`、`tailwind-merge`、`lucide-react`）
- devDeps：`@types/react`、`@types/node`、`eslint`、`prettier`

## 11. 不做的事（明确边界）

- 不接 WebSocket；只走 `useStream` 默认的 HTTP streaming。
- 不做 ISR/SSR；首页与列表页都是 CSR（数据小、缓存友好）。
- 不接用户系统；前端假设"本地单用户"。
- 不引入 Redux/Zustand；TanStack Query 足够。
- 不做 i18n；只中文。
- 不部署；只本地开发。