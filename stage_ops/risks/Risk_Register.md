# Risk Register

| ID | Date | Stage | Risk | Impact | Mitigation | Trigger | Status |
|---|---|---|---|---|---|---|---|
| R-001 | 2026-02-18 | Stage_01 | Existing docs are split across legacy and new structure, causing traceability gaps | Medium | Keep legacy files unchanged, add explicit source index and stage links | Missing source references in stage docs | Open |
| R-002 | 2026-02-18 | Stage_02 | Verifier gate is incomplete because `swerex` dependency is unavailable for smoke test collection | High | Scoped optional smoke gate + placeholder test to keep local verifier pipeline stable | `ModuleNotFoundError` in `smoke_test.py` | Mitigated |
| R-003 | 2026-02-18 | Stage_03 | Script-style tests return bool and emit pytest warnings, reducing strictness of assertions | Medium | Refactored script tests to assertion/exception style | `PytestReturnNotNoneWarning` during full suite | Mitigated |
| R-004 | 2026-02-18 | Stage_03 | Embedding path remains dummy-first, limiting research-depth validation for RQ2 | Medium | Implement configurable real embedding provider with fallback and cache controls | No real embedding provider configured in default path | Mitigated |
| R-005 | 2026-02-22 | Stage_04 | Cross-process active-task state file may face race conditions under high parallel writers | Medium | Add file locking / transactional state backend in next stage | Concurrent writes to `active_tasks.json` cause task mapping drift | Open |
| R-006 | 2026-02-22 | Stage_05 | Embedding similarity retrieval is linear scan and may degrade when memory scale grows | Medium | Introduce ANN/vector index and cache hot-query results in Stage_06 | `search_experience` latency increases with action count | Open |
