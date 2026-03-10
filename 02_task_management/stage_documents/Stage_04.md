# Stage_04 Document

## 1. Stage Objective (Verifiable)
- Objective: complete Stage_03 pending item and close hook-mode usability gap.
- Success criteria:
  - Hook mode keeps task continuity across independent `run_tool_a.sh` / `run_tool_b.sh` processes.
  - `KGWriter` main path supports configurable `sentence-transformers` with fallback.
  - `run_done` event clears active task mapping and closes task context.

## 2. Scope
- In scope:
  - `agent_mem` runtime continuity and embedding provider integration.
  - Hook payload enrichment and event routing (`run_done`).
  - Integration regression tests.
- Out of scope:
  - PDDL validator, belief promotion pipeline, full RCA async workflow.

## 3. Alignment Declaration
- Proposal alignment:
  - RQ1: improve process discipline and reduce repeated invalid recovery loops.
  - RQ2: activate real embedding backend in main pipeline.
  - RQ4: improve reusable process behavior under long-horizon execution.
- Architecture mapping:
  - Section 4.1/4.2 (online action logging + multi-view embedding).
  - Section 5.2 (execution-time repair retrieval).

## 4. Routed Tasks
- Engineer tasks:
  1. Add cross-process task continuity for hook-mode events.
  2. Add real embedding provider integration in `KGWriter` main chain.
  3. Add `run_done` lifecycle handling.
  4. Add regression checks for continuity and provider behavior.
- Verifier tasks:
  1. Confirm required test gates pass.
  2. Confirm hook-mode recheck yields non-empty repair suggestions after history accrues.

## 5. Acceptance Criteria
- Functional checks:
  - `PDDL_work_mem/tools/sweagent_ext_tools/venv/bin/python -m pytest PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/tests -q`
  - `PDDL_work_mem/tools/sweagent_ext_tools/venv/bin/python -m pytest PDDL_work_mem/tools/sweagent_ext_tools/tests -q`
  - `PDDL_work_mem/tools/sweagent_ext_tools/venv/bin/python -m pytest PDDL_work_mem/tools/sweagent_ext_tools -q`
- Runtime checks:
  - Hook-mode 3x `action_error` on same instance yields same `task_id`, non-zero `repair_suggestions` on later calls.
  - `run_done` clears `active_tasks` map.

## 6. Implementation Notes (Engineer)
- Key changes:
  - Added `GraphStore.get_last_action_id()` and resumed `last_action_id` in `ActionLogger.start_task()`.
  - Added active task persistence (`active_tasks.json`) in `SWEAgentAdapter` for cross-process continuity.
  - Added `run_done` handling end-to-end: `bridge_hook` -> `dispatcher` -> `agent_mem_main` -> `SWEAgentAdapter`.
  - Integrated configurable embedding provider in `KGWriter.EmbeddingGenerator`:
    - supports `model=random|sentence-transformers`
    - runtime fallback to deterministic hash-based vectors when unavailable.
  - Added embedding/provider observability in responses (`embedding_provider`).

## 7. Verification Notes (Verifier)
- Required gates:
  - `agent_mem/tests`: `12 passed`
  - `sweagent_ext_tools/tests`: `2 skipped` (optional dependency missing: `swerex/sweagent`)
  - full `sweagent_ext_tools`: `37 passed, 2 skipped`
- Runtime recheck evidence:
  - `PDDL_work_mem/实验/实验02/full_capability_recheck_20260222_005630`
  - Same task id across 3 events, edge accumulation (`kg_edge_count=2`), suggestions increase (`0 -> 1 -> 2`), run_done cleanup successful.

## 8. Stage Summary (Manager)
- Completed outcomes:
  - Hook continuity and run lifecycle closure are now usable in with-mem mode.
  - Sentence-transformers is now wired into main embedding path with safe fallback.
  - Stage_03 pending embedding item is closed.
- Unresolved items:
  - Belief update/promote/constraint compiler/validator are still pending (next stage gap list).
