# Fund Agent — Backend

Deterministic fund-data backend with 11 LangChain tools (fund / market / watchlist), a
Phase-1 thin DeepSeek agent slice, and a Phase-4 LangGraph QA flow.

## Setup

```bash
cd /Users/leon/fund-agent
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then put your DEEPSEEK_API_KEY in backend/.env
```

## Initialize the database

```bash
.venv/bin/python -m backend.db.init_db
```

## Run tests (offline)

```bash
.venv/bin/python -m pytest backend/tests -v
```

## Manual smoke test (live AKShare + agents)

```bash
.venv/bin/python -m backend.scripts.smoke_fetch 110011
```

## LangGraph QA flow (Phase 4)

```python
from backend.graph.qa_graph import ask, stream

# 一次性问答
print(ask("基金 110011 最新净值是多少?"))

# 流式调试
for chunk in stream("基金 110011 近一个月最大回撤"):
    print(chunk)
```

## LangGraph local server (optional)

```bash
.venv/bin/python -m pip install "langgraph-cli[inmem]"
langgraph dev
```

## API (Phase 2)

启动后端 HTTP API：

```bash
cd /Users/leon/fund-agent
.venv/bin/python -m uvicorn backend.api.app:app --reload --port 8000
```

Swagger UI：`http://localhost:8000/docs`
主要路由：
- `GET /api/funds/{code}` —— 基础信息
- `GET /api/funds/{code}/nav` —— 最新净值
- `GET /api/funds/{code}/nav-history?start=&end=` —— 净值历史
- `GET /api/funds/{code}/metrics?period=1m` —— 阶段指标
- `GET /api/watchlist` —— 自选池
- `GET /api/market/latest` —— 主要指数
- `GET /api/announcements` —— 公告占位

## Boundaries

Information assistant only — no buy/sell advice, no return predictions, no trading.
Numbers come from deterministic Python tools; the LLM only orchestrates and explains.
