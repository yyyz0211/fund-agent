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

## Boundaries

Information assistant only — no buy/sell advice, no return predictions, no trading.
Numbers come from deterministic Python tools; the LLM only orchestrates and explains.
