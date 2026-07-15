# Fund Agent

公开基金信息整理助手：确定性数据后端 + LangGraph QA 流程 + Next.js 14 前端。

- **Phase 1** — 后端基础（SQLAlchemy + AKShare + 指标 + 薄 Agent）
- **Phase 3** — LangChain Tools（11 个工具）
- **Phase 4** — LangGraph QA Flow
- **Phase 2** — Next.js 前端基础页面（本阶段）

## Phase 2 — 全栈启动

需要三个终端。我们用 `.venv/bin/...` 显式调用而不依赖 venv 激活，
避免不同 shell/pyenv shim 误用到全局 Python 3.9（项目使用 3.11 语法）。

```bash
# 终端 A：后端 API（通过 .venv/bin/uvicorn，强制使用 Python 3.11）
cd /Users/leon/fund-agent
.venv/bin/python -m uvicorn backend.api.app:app --reload --port 8000

# 终端 B：LangGraph Server（QA 流式问答）
cd /Users/leon/fund-agent
.venv/bin/langgraph dev

# 终端 C：前端
cd /Users/leon/fund-agent/frontend
npm install   # 第一次需要
cp .env.local.example .env.local
npm run dev
```

> **如果你已经 `source .venv/bin/activate` 了，可以直接用 `uvicorn ...` / `langgraph dev`，
> 不必加 `.venv/bin/` 前缀。但要注意 pyenv 用户 shim 中的 `uvicorn` 会指向 Python 3.9，
> 跑本仓库代码会因 `str | None` 语法报错 —— 必须用 venv 内的 uvicorn。**

打开 `http://localhost:3000`，按 `frontend/README.md` 中的 manual smoke checklist 验证五个页面。

## 部署到闲置电脑（Docker + Tailscale）

适合"几个朋友小圈子"使用：0 公网端口、0 域名、0 月费。

详见 [DOCKER.md](./DOCKER.md)。

核心流程：
1. 闲置电脑装 Docker Desktop + Tailscale
2. `git clone` 拉代码
3. `cp .env.example .env`，填 DeepSeek key
4. `.\scripts\start.ps1` 一键拉起 4 个容器
5. 把 Tailscale IP 发给朋友，他们也能访问

## Boundaries

Information assistant only — no buy/sell advice, no return predictions, no trading.
Numbers come from deterministic Python tools; the LLM only orchestrates and explains.

## 后端测试

测试数据库仅支持 PostgreSQL。启动可丢弃的 pgvector 测试服务后运行：

```bash
docker compose --profile test up -d postgres-test
TEST_DATABASE_URL=postgresql+psycopg2://fund_test:fund_test@localhost:55432/fund_agent_test \
  .venv/bin/python -m pytest -q backend/tests
```

数据库名必须以 `_test` 结尾。普通事务测试按 pytest worker 使用独立 schema；
多连接和 DDL 测试也不会访问开发或生产 schema。
