# Stage_05 Document

## 1. Stage Objective (Verifiable)
- Objective: remove MVP-blocking placeholders in memory retrieval/update path to make with-mem mode materially usable.
- Success criteria:
  - `search_experience()` returns formal, evidence-backed results instead of placeholder.
  - Belief update is executed at task end (`run_done`) and persisted.
  - Embedding-based action similarity search is available in core KG path.

## 2. Scope
- In scope:
  - `ObservationKG.find_similar_actions` implementation.
  - `GraphStore.find_similar_actions` embedding-first retrieval.
  - `MemoryAgent.update_beliefs` real update logic.
  - `SWEAgentAdapter.search_experience` formal output contract.
  - Wiring belief update into `handle_run_done`.
- Out of scope:
  - PDDL validator/compiler hard-guardrail pipeline.
  - GUI multi-modal memory path.

## 3. Alignment Declaration
- Proposal alignment:
  - RQ1: improve process robustness via reusable repair memory and belief evolution.
  - RQ2: strengthen embedding-based retrieval path from placeholder to operational.
  - RQ4: reduce repetitive failure loops by persistent suggestions and belief accumulation.
- Architecture mapping:
  - Section 4.2 (multi-view embeddings) and Section 6 (Memory Agent responsibilities).

## 4. Routed Tasks
- Engineer tasks:
  1. Implement embedding similarity search in fact graph.
  2. Replace placeholder `search_experience` with structured retrieval output.
  3. Implement belief update and connect it to task lifecycle.
  4. Add/extend tests for new behavior.
- Verifier tasks:
  1. Validate required pytest gates remain green.
  2. Validate with-mem runtime sample includes non-empty retrieval outputs and belief updates.

## 5. Acceptance Criteria
- Functional checks:
  - `PDDL_work_mem/tools/sweagent_ext_tools/venv/bin/python -m pytest PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/tests -q`
  - `PDDL_work_mem/tools/sweagent_ext_tools/venv/bin/python -m pytest PDDL_work_mem/tools/sweagent_ext_tools/tests -q`
  - `PDDL_work_mem/tools/sweagent_ext_tools/venv/bin/python -m pytest PDDL_work_mem/tools/sweagent_ext_tools -q`
- Runtime checks:
  - `run_done` response includes non-empty `belief_update` with created/updated counters.
  - `search_experience` response includes `results/recommendations/belief_hints/evidence_refs`.

## 6. Implementation Notes (Engineer)
- `ObservationKG.find_similar_actions` now computes weighted cosine similarity across embedding views.
- `GraphStore.find_similar_actions` now uses embedding-first retrieval with lexical fallback.
- `MemoryAgent.update_beliefs` now creates attempt belief + upserts atomic belief + updates stats.
- `SWEAgentAdapter.handle_run_done` now triggers belief update and persists result.
- `SWEAgentAdapter.search_experience` now returns formal retrieval payload with assumptions/failure mode description.
- Tests updated:
  - `agent_mem/tests/test_core.py` added embedding-similarity test.
  - `test_integration.py` validates search output and belief update path.

## 7. Verification Notes (Verifier)
- Required gates:
  - `agent_mem/tests`: `13 passed`
  - `sweagent_ext_tools/tests`: `2 skipped` (optional dependency missing: `swerex/sweagent`)
  - full `sweagent_ext_tools`: `38 passed, 2 skipped`
- Runtime evidence:
  - `PDDL_work_mem/实验/实验02/mvp_alignment_recheck_20260222_011055/mvp_alignment_summary.json`

## 8. Stage Summary (Manager)
- Completed outcomes:
  - Removed three major MVP blockers (search placeholder / belief update placeholder / embedding similarity placeholder).
  - With-mem mode now provides formal retrieval APIs and evolving belief signals.
- Unresolved items:
  - Validator/compiler/constraint pipeline still pending.
  - High-concurrency lock safety for `active_tasks.json` still pending.
