# Stage_03 Document

## 1. Stage Objective (Verifiable)
- Objective: advance beyond compatibility hardening into architecture-aligned feature progression (embedding/retrieval quality + test strictness).
- Success criteria:
  - Replace/upgrade dummy embedding path with configurable real embedding path (fallback retained).
  - Remove pytest return-value warnings by converting script-style tests to strict assertions.
  - Keep full suite green after refactor.

## 2. Scope
- In scope:
  - retrieval/embedding path hardening in `agent_mem/retrieval/*`.
  - test modernization for `test_simple.py`, `test_integration.py`, `test_functional.py`.
  - CI-friendly smoke strategy document update.
- Out of scope:
  - full PDDL3 hard-constraint backend.

## 3. Alignment Declaration
- Proposal alignment:
  - RQ2: stronger empirical basis for multi-view embedding impact.
  - RQ4: cleaner, more stable process metrics by stricter test discipline.
- Architecture mapping:
  - aligns with retrieval quality and progressive verifiability roadmap.

## 4. Routed Tasks
- Engineer tasks:
  1. Implement real embedding provider option with graceful fallback and cache hooks.
  2. Refactor script tests into pytest-style assertion tests.
  3. Preserve existing interfaces used by adapter and verifier.
- Verifier tasks:
  1. Check consistency between retrieval API and new tests.
  2. Ensure no redundant duplicate logic introduced by compatibility layer.
  3. Validate full test suite and warnings trend.

## 5. Acceptance Criteria
- Functional checks:
  - `pytest PDDL_work_mem/tools/sweagent_ext_tools -q` passes.
- Consistency checks:
  - retrieval interfaces remain backward compatible.
- Quality checks:
  - eliminate `PytestReturnNotNoneWarning` warnings.

## 6. Implementation Notes (Engineer)
- Progress:
  - Refactored script-style tests to pytest-compatible semantics:
    - `PDDL_work_mem/tools/sweagent_ext_tools/test_simple.py`
    - `PDDL_work_mem/tools/sweagent_ext_tools/test_integration.py`
    - `PDDL_work_mem/tools/sweagent_ext_tools/test_functional.py`
  - Removed return-value warnings by using assertion/exception-driven flow.
  - Verified full suite: `36 passed, 2 skipped`.
- Remaining:
  - Real embedding provider path is not yet implemented (still dummy fallback default).

## 7. Verification Notes (Verifier)
- Current status: PARTIAL
- Passed checks:
  - Full suite remains green after test refactor.
  - `PytestReturnNotNoneWarning` removed.
- Open check:
  - Real embedding provider implementation pending.

## 8. Stage Summary (Manager)
- Completed outcomes:
  - Verification strictness improved without regression.
- Unresolved items:
  - Embedding-path advancement (RQ2) deferred to next cycle step.
