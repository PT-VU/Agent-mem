# Agent-mem Stage Milestones

## M1: MVP Reliability Hardening
- Scope: fix failing tests, unify storage and type definitions, stabilize serialization
- Arch mapping: Problem File + Observation KG + Belief Graph base correctness
- Exit criteria: all core tests pass, no contradictory schema definitions

## M2: Retrieval and Injection Quality
- Scope: improve retrieval quality and planning/execution injection behavior
- Arch mapping: multi-view embedding, query rewrite, subgraph selection
- Exit criteria: deterministic retrieval behavior and evidence-linked suggestions

## M3: RCA and Belief Evolution
- Scope: root-cause extraction and belief update/promotion lifecycle
- Arch mapping: asynchronous RCA, distilled skeletons, belief status transition
- Exit criteria: reproducible RCA output and confidence-backed belief updates

## M4: Verifiable Guardrails
- Scope: preference/constraint candidates and validation loop integration
- Arch mapping: soft/hard control layers and fail-fast checks
- Exit criteria: measurable reduction in invalid action patterns
