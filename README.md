# Fund Agent

公开基金信息整理助手：确定性数据后端 + LangGraph QA 流程 + Next.js 14 前端。

- **Phase 1** — 后端基础（SQLAlchemy + AKShare + 指标 + 薄 Agent）
- **Phase 3** — LangChain Tools（11 个工具）
- **Phase 4** — LangGraph QA Flow
- **Phase 2** — Next.js 前端基础页面（本阶段）

## Phase 2 — 全栈启动

三个终端分别跑：

```bash
# 终端 A：后端 API
cd /Users/leon/fund-agent
.venv/bin/python -m uvicorn backend.api.app:app --reload --port 8000

# 终端 B：LangGraph Server（QA 流式问答）
cd /Users/leon/fund-agent
.venv/bin/python -m pip install "langgraph-cli[inmem]"
langgraph dev

# 终端 C：前端
cd /Users/leon/fund-agent/frontend
npm install   # 第一次需要
cp .env.local.example .env.local
npm run dev
```

打开 `http://localhost:3000`，按 `frontend/README.md` 中的 manual smoke checklist 验证五个页面。

## Boundaries

Information assistant only — no buy/sell advice, no return predictions, no trading.
Numbers come from deterministic Python tools; the LLM only orchestrates and explains.
