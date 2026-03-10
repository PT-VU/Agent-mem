# Decision Log

| ID | Date | Stage | Decision | Status | Owner | Notes |
|---|---|---|---|---|---|---|
| D-001 | 2026-02-18 | Stage_01 | Adopt structured stage workflow as mandatory multi-agent memory layout | Closed | Manager | Finalized with `docs/` + `stage_ops/` + `phase_history/` + `tools/` + `runtime/` layout |
| D-002 | 2026-02-18 | Stage_02 | Choose smoke-test dependency strategy (`swerex` install vs optional gate) | Closed | Manager + User | Resolved as optional local gate + explicit skip evidence |
| D-003 | 2026-02-18 | Stage_02 | Prioritize compatibility hardening before feature expansion | Closed | Manager | Implemented via API compatibility wrappers and test harness stabilization |
| D-004 | 2026-02-18 | Stage_03 | Refactor script tests to strict pytest semantics before embedding expansion | Closed | Manager | Removed warning-prone return-value patterns while keeping full suite green |
| D-005 | 2026-02-22 | Stage_04 | Persist hook task context across independent tool processes and close lifecycle with `run_done` | Closed | Manager | Implemented with `active_tasks.json` + `run_done` event chain; verified by runtime recheck |
| D-006 | 2026-02-22 | Stage_04 | Promote embedding backend default in with-mem mode to `sentence-transformers` with deterministic fallback | Closed | Manager | `KGWriter` now supports configurable provider; fallback keeps compatibility when model unavailable |
| D-007 | 2026-02-22 | Stage_05 | Replace MVP retrieval placeholders with formal search + similarity + belief-update loop | Closed | Manager | `search_experience` now structured; `update_beliefs` wired to `run_done`; embedding similarity activated |
