# Phase 4: LangGraph QA Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 4 LangGraph QA flow that routes user questions through compliance policy, DeepSeek tool-calling over `ALL_TOOLS`, and streamable final answers.

**Architecture:** Add a new `backend.graph` package. `policy.py` owns deterministic allow/deny checks, `model.py` owns DeepSeek model construction and tool binding, and `qa_graph.py` owns the compiled LangGraph. Existing Phase 1 `thin_agent` remains unchanged for compatibility.

**Tech Stack:** Python 3.11, LangGraph 0.6, LangChain Core, LangChain OpenAI, DeepSeek `deepseek-chat`, pytest, SQLite-backed existing services/tools.

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
| `backend/requirements.txt` | LangGraph dependencies | Done |
| `requirements.txt` | Root install entry for LangGraph CLI | Done |
| `langgraph.json` | LangGraph Server config | Done |
| `backend/graph/__init__.py` | Graph package marker | Done |
| `backend/graph/policy.py` | Compliance allow/deny helpers | Done |
| `backend/graph/model.py` | DeepSeek model + `ALL_TOOLS` binding | Done |
| `backend/graph/qa_graph.py` | Compiled graph + `ask`/`stream` | Done |
| `backend/services/fund_service.py` | Illegal period error dict | Done |
| `backend/scripts/smoke_fetch.py` | Optional Phase 4 smoke | Done |
| `backend/README.md` | LangGraph usage docs | Done |
| `backend/tests/test_graph_policy.py` | Policy tests | Done |
| `backend/tests/test_qa_graph.py` | Graph tests with fake model/tool | Done |
| `backend/tests/test_fund_service.py` | Illegal period test | Done |

## Tasks

### Task 1: Dependencies and Docs

- [x] Verify Phase 4 spec and this plan exist and are consistent.
- [x] Add `langgraph>=0.2,<0.3` and `langgraph-sdk` to `backend/requirements.txt`; document `langgraph-cli[inmem]` as optional local server tooling.

### Task 2: Compliance Policy

- [x] Write policy tests for blocked and allowed questions.
- [x] Implement `backend.graph.policy` with `check_question`, `check_answer`, and fixed refusal text.
- [x] Verify `backend/tests/test_graph_policy.py` passes (44/44).

### Task 3: Metrics Error Contract

- [x] Write test for unsupported `period`.
- [x] Change `fund_service.get_metrics` to return error dict instead of raising.
- [x] Verify `backend/tests/test_fund_service.py` passes.

### Task 4: LangGraph Model and QA Graph

- [x] Write graph tests with fake model/tool.
- [x] Implement `model.py` and `qa_graph.py`:
  - `QAState` = `MessagesState` alias (no extra keys needed).
  - Use LangGraph `ToolNode` with `ALL_TOOLS`.
  - Pre-check node: if `policy.check_question` blocks, append `AIMessage(REFUSAL_MESSAGE)` and END.
  - Model node: invoke `build_model()` with `ALL_TOOLS`; pass full `messages` state.
  - Post-check node: if `policy.check_answer` blocks, replace last `AIMessage.content` with `REFUSAL_MESSAGE`.
  - Two separate routing functions: `_route_pre_check` (pre_check → llm|END) and `_route_llm` (llm → tools|post_check).
  - `ask()`: invoke compiled graph with `{"messages": [HumanMessage(question)]}`, return `state["messages"][-1].content`.
  - `stream()`: same but call `.stream()` on compiled graph, yield chunks.
- [x] Create `langgraph.json` at repo root with `"fund_agent"` → `"backend/graph/qa_graph.py:graph"`.
- [x] Verify graph tests pass without real LLM/network.

### Task 5: Smoke and README

- [x] Update `smoke_fetch.py` to include optional Phase 4 `ask()` smoke.
- [x] Update README with `.venv/bin/python`, `langgraph dev`, and stream notes.
- [x] Run full test suite.

## Verification

- `.venv/bin/python -m pytest backend/tests -v` → 96 passed
- Optional manual path with key configured: `langgraph dev`, then send a threadless run to assistant `fund_agent`.

## Implementation Notes

### LangGraph 0.6 API quirks

- `StateGraph(state_schema)` does **not** accept `messages_modifier`; `MessagesState` already has `add_messages` as its built-in reducer.
- Two separate routing functions are needed: LangGraph 0.6 registers each conditional edge's function at graph-build time, and the same function cannot return different destination node names for different source nodes. Therefore `_route_pre_check` handles pre_check → llm|END and `_route_llm` handles llm → tools|post_check.
- `compiled.graph` is lazily built via `_get_graph()` singleton to allow tests to patch `build_model` before first import.
- Stream chunks are keyed by node name (e.g. `{"pre_check": {...}}`), not by `"messages"`.

### Graph topology

```
__start__ → pre_check → llm ⇄ tools → post_check → END
                  ↓
           (if blocked: AIMessage(REFUSAL) → END)
```

## Self-Review

- Spec coverage: docs, policy, graph, dependencies, README/smoke, tests are covered.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: `graph`, `ask`, `stream`, `check_question`, `check_answer`, `REFUSAL_MESSAGE` names are used consistently.
