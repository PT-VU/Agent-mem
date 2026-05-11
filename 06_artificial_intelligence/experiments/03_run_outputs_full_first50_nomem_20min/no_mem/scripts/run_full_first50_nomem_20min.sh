#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
SWEAGENT_BIN="${SWEAGENT_BIN:-${SWE_AGENT_ROOT}/.venv/bin/sweagent}"
START_WITH_TOOLS="${START_WITH_TOOLS:-${WS_ROOT}/PDDL_work_mem/source_code/sweagent_external_tools/bin/start_with_external_tools.sh}"
COMMON_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common"

EXP_DIR="${EXP_DIR:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/no_mem}"
OUTDIR_DEFAULT="${EXP_DIR}/outputs/run_outputs_full_first50_nomem_20min"
OUTDIR="${OUTDIR:-${OUTDIR_DEFAULT}}"
CACHE_FILE_DEFAULT="${EXP_DIR}/cache/full_test_instances_cache.json"
CACHE_FILE="${CACHE_FILE:-${CACHE_FILE_DEFAULT}}"
METRICS_DIR_DEFAULT="${EXP_DIR}/metrics"
METRICS_DIR="${METRICS_DIR:-${METRICS_DIR_DEFAULT}}"
MANIFEST_OUT_DEFAULT="${METRICS_DIR}/manifest_experiment01_full_first50_nomem_20min.json"
MANIFEST_OUT="${MANIFEST_OUT:-${MANIFEST_OUT_DEFAULT}}"
METRICS_OUT_DEFAULT="${METRICS_DIR}/metrics_experiment01_full_first50_nomem_20min.json"
METRICS_OUT="${METRICS_OUT:-${METRICS_OUT_DEFAULT}}"

SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-full}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
START_INDEX="${START_INDEX:-auto}"
STOP_INDEX="${STOP_INDEX:-50}"
WINDOW_SIZE="${WINDOW_SIZE:-25}"
AUTO_CONTINUE="${AUTO_CONTINUE:-1}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/deepseek.yaml}"
NUM_WORKERS="${NUM_WORKERS:-1}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
REDO_EXISTING="${REDO_EXISTING:-0}"
ENV_VAR_PATH="${ENV_VAR_PATH:-${SWE_AGENT_ROOT}/.env}"
METRICS_START_INDEX="${METRICS_START_INDEX:-0}"
METRICS_STOP_INDEX="${METRICS_STOP_INDEX:-${STOP_INDEX}}"
SUBSET_LABEL="${SUBSET_LABEL:-SWE-bench Full (first 50 instances, 20min cap)}"
EVENT_LOG_GLOB_DEFAULT="${EXP_DIR#${WS_ROOT}/}/logs/no_mem_tool_events_window_*.jsonl"
EVENT_LOG_GLOB="${EVENT_LOG_GLOB:-${EVENT_LOG_GLOB_DEFAULT}}"

# Remove stale hook settings from older directory layout before launching.
unset SWE_AGENT_EXTERNAL_HOOK_CLASS SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH
if [[ "${SWE_AGENT_EXT_TOOL_A_CMD:-}" == *"/PDDL_work_mem/tools/sweagent_ext_tools/"* ]]; then
  unset SWE_AGENT_EXT_TOOL_A_CMD
fi
if [[ "${SWE_AGENT_EXT_TOOL_B_CMD:-}" == *"/PDDL_work_mem/tools/sweagent_ext_tools/"* ]]; then
  unset SWE_AGENT_EXT_TOOL_B_CMD
fi

is_int() { [[ "$1" =~ ^[0-9]+$ ]]; }
to_bool_token() {
  local raw
  raw="$(echo "${1}" | tr '[:upper:]' '[:lower:]')"
  case "${raw}" in
    1|true|yes|on) echo "True" ;;
    *) echo "False" ;;
  esac
}

if ! is_int "${STOP_INDEX}" || ! is_int "${WINDOW_SIZE}"; then
  echo "STOP_INDEX and WINDOW_SIZE must be non-negative integers" >&2
  exit 2
fi

mkdir -p "${OUTDIR}" "$(dirname "${CACHE_FILE}")" "${EXP_DIR}/logs"

build_instance_cache() {
  "${SWE_AGENT_ROOT}/.venv/bin/python" - <<'PY' "${CACHE_FILE}" "${SWEBENCH_SUBSET}" "${SWEBENCH_SPLIT}" "${STOP_INDEX}"
import json
import pathlib
import sys
from sweagent.run.batch_instances import SWEBenchInstances

cache_path = pathlib.Path(sys.argv[1])
subset = sys.argv[2]
split = sys.argv[3]
stop = int(sys.argv[4])
slice_expr = f":{stop}" if stop > 0 else ""
instances = SWEBenchInstances(subset=subset, split=split, slice=slice_expr).get_instance_configs()
ids = [inst.problem_statement.id for inst in instances]
cache_path.parent.mkdir(parents=True, exist_ok=True)
cache_path.write_text(json.dumps(ids, ensure_ascii=False, indent=2))
print(f"cached {len(ids)} ids -> {cache_path}")
PY
}

verify_event_logs() {
  "${SWE_AGENT_ROOT}/.venv/bin/python" - <<'PY' "${WS_ROOT}" "${EVENT_LOG_GLOB}"
import pathlib
import sys

ws_root = pathlib.Path(sys.argv[1]).resolve()
glob_expr = sys.argv[2]
files = [p for p in ws_root.glob(glob_expr) if p.is_file()]
if not files:
    print(f"ERROR: no event log files found for glob={glob_expr}", file=sys.stderr)
    raise SystemExit(1)
print(f"event logs found: {len(files)}")
PY
}

next_incomplete_index() {
  "${SWE_AGENT_ROOT}/.venv/bin/python" - <<'PY' "${CACHE_FILE}" "${OUTDIR}" "${STOP_INDEX}"
import json
import pathlib
import sys

cache_file = pathlib.Path(sys.argv[1])
outdir = pathlib.Path(sys.argv[2])
stop = int(sys.argv[3])
ids = json.loads(cache_file.read_text())
for i, iid in enumerate(ids[:stop]):
    traj = outdir / iid / f"{iid}.traj"
    if not traj.exists():
        print(i)
        raise SystemExit(0)
print(stop)
PY
}

build_instance_cache

if [[ "${START_INDEX}" == "auto" ]]; then
  START_INDEX="$(next_incomplete_index)"
fi

if ! is_int "${START_INDEX}"; then
  echo "START_INDEX must be integer or auto" >&2
  exit 2
fi

if (( START_INDEX >= STOP_INDEX )); then
  echo "All instances are complete. Nothing to run."
else
  current_start=${START_INDEX}
  while (( current_start < STOP_INDEX )); do
    current_end=$((current_start + WINDOW_SIZE))
    if (( current_end > STOP_INDEX )); then
      current_end=${STOP_INDEX}
    fi

    event_log="${EXP_DIR}/logs/no_mem_tool_events_window_${current_start}_${current_end}.jsonl"
    run_log="${EXP_DIR}/logs/run_nomem_window_${current_start}_${current_end}.log"
    export SWE_AGENT_EXT_TOOLS_LOG_FILE="${event_log}"

    echo "Window run plan: start=${current_start} end=${current_end} stop=${STOP_INDEX}"

    "${START_WITH_TOOLS}" --mode no-mem \
      "${SWEAGENT_BIN}" run-batch \
      --config "${MODEL_CONFIG}" \
      --instances.type swe_bench \
      --instances.subset "${SWEBENCH_SUBSET}" \
      --instances.split "${SWEBENCH_SPLIT}" \
      --instances.slice "${current_start}:${current_end}" \
      --output_dir "${OUTDIR}" \
      --num_workers "${NUM_WORKERS}" \
      --env_var_path "${ENV_VAR_PATH}" \
      --agent.model.per_instance_call_limit "${PER_INSTANCE_CALL_LIMIT}" \
      --agent.tools.total_execution_timeout "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
      --redo_existing "$(to_bool_token "${REDO_EXISTING}")" \
      2>&1 | tee -a "${run_log}"

    if [[ "${AUTO_CONTINUE}" != "1" ]]; then
      break
    fi
    current_start=${current_end}
  done
fi

verify_event_logs

mkdir -p "${METRICS_DIR}"
"${SWE_AGENT_ROOT}/.venv/bin/python" "${COMMON_DIR}/collect_run_manifest.py" \
  --workspace-root "${WS_ROOT}" \
  --experiment-id "实验01_full_first50_nomem_20min" \
  --mode "no-mem" \
  --subset "${SWEBENCH_SUBSET}" \
  --split "${SWEBENCH_SPLIT}" \
  --output-dir "${OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --start-index "${METRICS_START_INDEX}" \
  --stop-index "${METRICS_STOP_INDEX}" \
  --run-script "PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/no_mem/scripts/run_full_first50_nomem_20min.sh" \
  --model-config "${MODEL_CONFIG}" \
  --event-log-glob "${EVENT_LOG_GLOB}" \
  --require-event-logs \
  --manifest-out "${MANIFEST_OUT}"

"${SWE_AGENT_ROOT}/.venv/bin/python" "${COMMON_DIR}/collect_run_metrics.py" \
  --workspace-root "${WS_ROOT}" \
  --experiment-id "实验01_full_first50_nomem_20min" \
  --subset-label "${SUBSET_LABEL}" \
  --mode "no-mem" \
  --output-dir "${OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --start-index "${METRICS_START_INDEX}" \
  --stop-index "${METRICS_STOP_INDEX}" \
  --event-log-glob "${EVENT_LOG_GLOB}" \
  --require-event-logs \
  --manifest-path "${MANIFEST_OUT}" \
  --metrics-out "${METRICS_OUT}"
