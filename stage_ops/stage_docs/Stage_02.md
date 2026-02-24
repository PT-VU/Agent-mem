# Stage_02 Document

## 1. Stage Objective (Verifiable)
- Objective: close Stage_01 blocker, complete phase-1/phase-2 reliability hardening baseline, and make verification pipeline executable.
- Success criteria:
  - Required quality-gate commands execute without hard failure.
  - Integration/functional scripts pass.
  - Compatibility gaps between modules and verification scripts are resolved.

## 2. Scope
- In scope:
  - `sweagent_ext_tools` compatibility fixes and testability hardening.
  - dependency-gated smoke verification handling.
  - consistency fixes in graph indexing/config API.
- Out of scope:
  - full feature expansion for advanced retrieval/RCA optimization.

## 3. Alignment Declaration
- Proposal alignment:
  - RQ1/RQ4: strengthens process-discipline reliability and measurable execution quality.
- Architecture mapping:
  - Agent-mem data flow consistency (action logging -> KG edges -> retrieval) and verifier loop closure.

## 4. Routed Tasks
- Engineer tasks (file/module level):
  1. Fix graph indexing consistency in `agent_mem/storage/graph_store.py`.
  2. Add compatibility APIs for legacy verification scripts (`ConfigManager`, `MemoryAgent`, `ErrorHandler`, storage alias).
  3. Fix test harness scripts and storage test imports.
  4. Implement optional dependency gate for smoke tests.
- Verifier checks (must-check rules):
  1. Re-run stage quality-gate commands.
  2. Run full `sweagent_ext_tools` pytest suite.
  3. Verify no internal contradiction between stage plan and observed evidence.

## 5. Acceptance Criteria
- Functional checks:
  - `run_tests.py`, `test_simple.py`, `test_integration.py`, `test_functional.py` all pass.
- Consistency checks:
  - KG edge creation does not fail due missing reverse index.
  - config and retrieval compatibility methods are callable.
- Quality checks:
  - `pytest PDDL_work_mem/tools/sweagent_ext_tools -q` passes (allowing explicit skip of optional smoke dependencies).

## 6. Implementation Notes (Engineer)
- Changed files:
  - `PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/storage/graph_store.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/config/config_manager.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/retrieval/memory_agent.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/processing/error_handler.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/storage/local_storage.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/storage/__init__.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/run_tests.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/storage/test_interface.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/storage/test_local_storage.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/test_integration.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/tests/smoke_test.py`
  - `PDDL_work_mem/tools/sweagent_ext_tools/tests/test_smoke_placeholder.py`
- Why this implementation:
  - closes stage blocker with minimal invasive changes while preserving architecture evolution path.

## 7. Verification Notes (Verifier)
- Pass/Fail: PASS
- Blocking items:
  - None.
- Suggestions:
  - Convert script-style test files to strict pytest style to remove `PytestReturnNotNoneWarning`.

## 8. Stage Summary (Manager)
- Completed outcomes:
  - Stage_01 blocker removed and quality gate executable.
  - Stage-2 reliability baseline achieved with 36 passed / 2 skipped in full pytest.
  - compatibility layer added to keep old scripts and new architecture moving together.
- External support needed:
  - Decision on whether to install `swerex`/`sweagent` for full smoke execution or keep optional skip in local gate.
- New risks:
  - script-style tests returning bool may hide assertion clarity.
- Decision items:
  - D-002 (resolved with optional dependency gate policy).
  - D-003 (adopt compatibility-first hardening before feature expansion).
