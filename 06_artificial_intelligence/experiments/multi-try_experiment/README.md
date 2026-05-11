# Multi-Try Experiment (Same Instance Repeated Attempts)

## Goal
- Evaluate whether AgentMem can learn from previous attempts on the same instance.
- For each selected instance, run repeated attempts (`REPEATS`, default `5`):
  - Attempt 1 starts with empty memory for that instance (with-mem mode).
  - Attempts 2..N reuse memory accumulated from earlier attempts on the same instance.
- Keep a strict per-attempt execution limit (`20min` by default).
- Run with-mem and no-mem as controlled comparison.

## Output Layout
- `with_mem/outputs/<instance_id>/attempt_XX/<instance_id>/<instance_id>.traj`
- `with_mem/logs/with_mem/<instance_id>/attempt_XX.jsonl`
- `with_mem/logs/with_mem/<instance_id>/attempt_XX.log`
- `with_mem/persistence/<instance_id>/{graph_store,evidence_store}`
- `with_mem/metrics/summary_multi_try_with_mem_20min.json`
- `no_mem/outputs/<instance_id>/attempt_XX/<instance_id>/<instance_id>.traj`
- `no_mem/logs/no_mem/<instance_id>/attempt_XX.jsonl`
- `no_mem/logs/no_mem/<instance_id>/attempt_XX.log`
- `no_mem/metrics/summary_multi_try_no_mem_20min.json`

## Key Scripts
- with-mem:
  - `PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/with_mem/scripts/run_multi_try_with_mem_20min.sh`
  - `PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/with_mem/scripts/run_lite_failedcase_repeat10_with_mem_closed_loop.sh`
- no-mem:
  - `PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/no_mem/scripts/run_multi_try_no_mem_20min.sh`
- summary collector:
  - `PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/common/collect_multi_try_summary.py`

## Configurable Parameters
- `SWEBENCH_SUBSET` (`full`/`lite`)
- `SWEBENCH_SPLIT` (`test`/`dev`)
- `START_INDEX` (default `0`)
- `INSTANCE_COUNT` (how many instances to cover)
- `INSTANCE_IDS_CSV` (optional explicit list, overrides index/count)
- `REPEATS` (default `5`)
- `INSTANCE_TOTAL_EXEC_TIMEOUT_SEC` (default `1200`)
- `PER_INSTANCE_CALL_LIMIT` (default `0`, unlimited calls)
- `REDO_EXISTING` (default `1`)
- `FAIL_FAST` (default `0`)
- `RESET_INSTANCE_MEMORY` (with-mem only, default `1`)

## Example Commands
```bash
cd /home/pt/SWE-bench

# with-mem, full dataset, first 3 instances, each repeated 5 times
SWEBENCH_SUBSET=full START_INDEX=0 INSTANCE_COUNT=3 REPEATS=5 \
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC=1200 \
PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/with_mem/scripts/run_multi_try_with_mem_20min.sh

# with-mem, Lite 历史失败候选自动选择；若当前 attempt_01 仍失败，则继续跑满 10 次
PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/with_mem/scripts/run_lite_failedcase_repeat10_with_mem_closed_loop.sh

# no-mem baseline on the same scope
SWEBENCH_SUBSET=full START_INDEX=0 INSTANCE_COUNT=3 REPEATS=5 \
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC=1200 \
PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/no_mem/scripts/run_multi_try_no_mem_20min.sh
```

## What Gets Recorded
- Full trajectory per attempt (`*.traj`).
- Tool event stream per attempt (`*.jsonl`), including:
  - `external_tool_response`
  - `memory_hint_buffered`
  - `memory_injected`
  - `external_tool_timeout`
  - other HOOK events
- Aggregated summary per mode:
  - success count/rate by attempt index
  - first success attempt distribution
  - step/cost/fail-signal trends by attempt
  - per-instance detailed attempt records
