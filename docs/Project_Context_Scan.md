# Project Context Scan

## Repo Map (Relevant Scope)
- Main benchmark framework: `swebench/`
- Agent-mem workspace: `PDDL_work_mem/`
- Tool extension baseline: `PDDL_work_mem/tools/sweagent_ext_tools/`

## sweagent_ext_tools Capability Snapshot
- Hook entry: `bridge_hook.py`
- Event router: `dispatcher.py`
- Tool handlers: `tools/tool_a.py`, `tools/tool_b.py`
- Agent-mem package scaffold: `agent_mem/` (core, retrieval, processing, storage, integration)
- Tests: `agent_mem/tests/`, `tests/smoke_test.py`, root-level functional tests

## Architecture Milestone Seed (from Agent-mem architecture)
1. Problem File + Observation KG integrity
2. Multi-view retrieval and memory injection (planning/execution)
3. RCA-based distillation and belief evolution
4. Soft-to-hard guardrail progression (preference/constraint)

## Non-Negotiable Research Mainlines (from proposal)
1. Auditable evidence-backed memory (not plain textual memory)
2. Progressive verifiability (soft preference to hard guardrails)
3. Process-discipline metrics (not only pass rate)
4. Training-free architecture with reusable experience assets
5. Support for long-horizon failure recovery and cascade suppression
