# Phase 4: LangGraph QA Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 4 LangGraph QA flow that routes user questions through compliance policy, DeepSeek tool-calling over `ALL_TOOLS`, and streamable final answers.

**Architecture:** Add a new `backend.graph` package. `policy.py` owns deterministic allow/deny checks, `model.py` owns DeepSeek model construction and tool binding, and `qa_graph.py` owns the compiled LangGraph. Existing Phase 1 `thin_agent` remains unchanged for compatibility.

**Tech Stack:** Python 3.11, LangGraph, LangChain Core, LangChain OpenAI, DeepSeek `deepseek-chat`, pytest, SQLite-backed existing services/tools.

---

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-phase4-langgraph-qa-design.md`
- Run tests from `/Users/leon/fund-agent` with `.venv/bin/python -m pytest ...`.
- Use TDD for behavior changes: write failing tests, verify red, implement minimal code, verify green.
- No front-end, RAG, announcements, risk scans, daily reports, or trading integrations in this phase.
- Do not modify `backend.agent.thin_agent` beyond compatibility fixes; Phase 4 uses `backend.graph.qa_graph`.
- No LLM/network calls in automated tests.

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `backend/requirements.txt` | Add LangGraph dependencies | Modify |
| `requirements.txt` | Root install entry for LangGraph CLI | Create |
| `langgraph.json` | LangGraph Server config | Create |
| `backend/graph/__init__.py` | Graph package marker | Create |
| `backend/graph/policy.py` | Compliance allow/deny helpers | Create |
| `backend/graph/model.py` | DeepSeek model + `ALL_TOOLS` binding | Create |
| `backend/graph/qa_graph.py` | Compiled graph + `ask`/`stream` | Create |
| `backend/services/fund_service.py` | Illegal period error dict | Modify |
| `backend/scripts/smoke_fetch.py` | Optional Phase 4 smoke | Modify |
| `backend/README.md` | LangGraph usage docs | Modify |
| `backend/tests/test_graph_policy.py` | Policy tests | Create |
| `backend/tests/test_qa_graph.py` | Graph tests with fake model/tool | Create |
| `backend/tests/test_fund_service.py` | Illegal period test | Modify |

## Tasks

### Task 1: Dependencies and Docs

- [ ] Add `langgraph` and `langgraph-sdk` to dependency files; document `langgraph-cli[inmem]` as optional local server tooling.
- [ ] Create Phase 4 spec and this implementation plan.
- [ ] Add `langgraph.json` pointing graph ID `fund_agent` to `./backend/graph/qa_graph.py:graph`.

### Task 2: Compliance Policy

- [ ] Write policy tests for blocked and allowed questions.
- [ ] Implement `backend.graph.policy` with `check_question`, `check_answer`, and fixed refusal text.
- [ ] Verify `backend/tests/test_graph_policy.py` passes.

### Task 3: Metrics Error Contract

- [ ] Write test for unsupported `period`.
- [ ] Change `fund_service.get_metrics` to return error dict instead of raising.
- [ ] Verify `backend/tests/test_fund_service.py` passes.

### Task 4: LangGraph Model and QA Graph

- [ ] Write graph tests with fake model/tool.
- [ ] Implement `model.py` and `qa_graph.py`.
- [ ] Verify graph tests pass without real LLM/network.

### Task 5: Smoke and README

- [ ] Update `smoke_fetch.py` to include optional Phase 4 `ask()` smoke.
- [ ] Update README with `.venv/bin/python`, `langgraph dev`, and stream notes.
- [ ] Run full test suite.

## Verification

- `.venv/bin/python -m pytest backend/tests -v`
- Optional manual path with key configured: `langgraph dev`, then send a threadless run to assistant `fund_agent`.

## Self-Review

- Spec coverage: docs, policy, graph, dependencies, README/smoke, tests are covered.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: `graph`, `ask`, `stream`, `check_question`, `check_answer`, `REFUSAL_MESSAGE` names are used consistently.
