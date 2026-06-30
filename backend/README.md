# Fund Agent — Backend (Phase 1)

Deterministic fund-data backend + thin LangChain/DeepSeek agent slice.

## Setup

```bash
cd /Users/leon/fund-agent
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then put your DEEPSEEK_API_KEY in backend/.env
```

## Initialize the database

```bash
python -m backend.db.init_db
```

## Run tests (offline)

```bash
python -m pytest backend/tests -v
```

## Manual smoke test (live AKShare + agent)

```bash
python -m backend.scripts.smoke_fetch 110011
```

## Boundaries

Information assistant only — no buy/sell advice, no return predictions, no trading.
Numbers come from deterministic Python tools; the LLM only orchestrates and explains.
