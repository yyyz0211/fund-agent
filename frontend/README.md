# Fund Agent — Frontend (Phase 2)

Next.js 14 App Router + TypeScript strict + Tailwind + shadcn/ui 风格的基础组件 + TanStack Query + Recharts。

## Setup

```bash
cd /Users/leon/fund-agent/frontend
npm install
cp .env.local.example .env.local
```

## Run dev server

```bash
npm run dev    # http://localhost:3000
```

要求后端 `uvicorn backend.api.app:app --port 8000` 已运行；
QA 页面额外要求 `langgraph dev` 已运行（端口 2024）。

## Build

```bash
npm run build
npm start
```

## Manual smoke checklist

启动后打开 `http://localhost:3000`：

1. `/` — 首页应有免责声明 + 主要指数卡片 + 自选池概览。
2. `/watchlist` — 自选表，搜索框可前端过滤。
3. `/funds/110011` — 详情页应有基础信息卡 + 净值曲线（需先跑过 `refresh_fund`）+ period selector。
4. `/announcements` — RAG 待接入说明 + 空表。
5. `/qa` — 输入"基金 110011 净值"应得到流式回答，右栏显示 source/as_of。
