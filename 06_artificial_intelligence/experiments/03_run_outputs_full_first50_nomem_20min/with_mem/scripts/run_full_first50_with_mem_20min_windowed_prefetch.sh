#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
SWEAGENT_BIN="${SWEAGENT_BIN:-${SWE_AGENT_ROOT}/.venv/bin/sweagent}"
START_WITH_TOOLS="${START_WITH_TOOLS:-${WS_ROOT}/PDDL_work_mem/source_code/sweagent_external_tools/bin/start_with_external_tools.sh}"
COMMON_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
RUNTIME_GUARD_SH="${COMMON_DIR}/docker_runtime_guard.sh"

EXP_DIR="${EXP_DIR:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem}"
OUTDIR="${OUTDIR:-${EXP_DIR}/outputs/run_outputs_full_first50_with_mem_20min}"
CACHE_FILE="${CACHE_FILE:-${EXP_DIR}/cache/full_test_instances_cache.json}"
CACHE_META_FILE="${CACHE_META_FILE:-${EXP_DIR}/cache/full_test_instances_cache_with_images.json}"
METRICS_DIR="${METRICS_DIR:-${EXP_DIR}/metrics}"
MANIFEST_OUT="${MANIFEST_OUT:-${METRICS_DIR}/manifest_experiment02_full_first50_withmem_20min.json}"
METRICS_OUT="${METRICS_OUT:-${METRICS_DIR}/metrics_experiment02_full_first50_withmem_20min.json}"

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
PYTHON_STANDALONE_DIR="${PYTHON_STANDALONE_DIR:-/root}"
DEPLOYMENT_STARTUP_TIMEOUT_SEC="${DEPLOYMENT_STARTUP_TIMEOUT_SEC:-600}"
STARTUP_RETRIES="${STARTUP_RETRIES:-1}"
SUBSET_LABEL="${SUBSET_LABEL:-SWE-bench Full (first 50 instances, 20min cap)}"
EXPERIMENT_ID="${EXPERIMENT_ID:-实验02_full_first50_withmem_20min}"
RUN_SCRIPT_PATH="${RUN_SCRIPT_PATH:-PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/scripts/run_full_first50_with_mem_20min_windowed_prefetch.sh}"

KEEP_BASE_RANGES="${KEEP_BASE_RANGES:-0:25}"
PREFETCH_NEXT_WINDOW="${PREFETCH_NEXT_WINDOW:-1}"
PRUNE_BUILD_CACHE_EACH_WINDOW="${PRUNE_BUILD_CACHE_EACH_WINDOW:-1}"

EVENT_LOG_GLOB_DEFAULT="${EXP_DIR#${WS_ROOT}/}/logs/with_mem_tool_events_window_*.jsonl"
EVENT_LOG_GLOB="${EVENT_LOG_GLOB:-${EVENT_LOG_GLOB_DEFAULT}}"

AGENT_MEM_STORAGE_DIR="${AGENT_MEM_STORAGE_DIR:-${EXP_DIR}/persistence/graph_store}"
AGENT_MEM_EVIDENCE_DIR="${AGENT_MEM_EVIDENCE_DIR:-${EXP_DIR}/persistence/evidence_store}"
AGENT_MEM_EMBEDDING_MODEL="${AGENT_MEM_EMBEDDING_MODEL:-sentence-transformers}"
AGENT_MEM_EMBEDDING_MODEL_NAME="${AGENT_MEM_EMBEDDING_MODEL_NAME:-all-MiniLM-L6-v2}"
if [[ -z "${AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS+x}" ]]; then
  if (( NUM_WORKERS > 1 )); then
    AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS="0"
  else
    AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS="1"
  fi
fi
SWE_AGENT_EXT_TOOL_A_TIMEOUT_SEC="${SWE_AGENT_EXT_TOOL_A_TIMEOUT_SEC:-90.0}"
SWE_AGENT_EXT_TOOL_RETRY_TIMEOUT_SEC="${SWE_AGENT_EXT_TOOL_RETRY_TIMEOUT_SEC:-150.0}"
SWE_AGENT_EXT_TOOL_MAX_RETRIES="${SWE_AGENT_EXT_TOOL_MAX_RETRIES:-1}"

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

mkdir -p "${OUTDIR}" "$(dirname "${CACHE_FILE}")" "${EXP_DIR}/logs" "${METRICS_DIR}" \
  "${AGENT_MEM_STORAGE_DIR}" "${AGENT_MEM_EVIDENCE_DIR}"
source "${RUNTIME_GUARD_SH}"

build_instance_cache() {
  "${PYTHON_BIN}" - <<'PY' "${CACHE_FILE}" "${CACHE_META_FILE}" "${SWEBENCH_SUBSET}" "${SWEBENCH_SPLIT}" "${STOP_INDEX}"
import json
import pathlib
import sys
from sweagent.run.batch_instances import SWEBenchInstances

cache_ids = pathlib.Path(sys.argv[1])
cache_meta = pathlib.Path(sys.argv[2])
subset = sys.argv[3]
split = sys.argv[4]
stop = int(sys.argv[5])
slice_expr = f":{stop}" if stop > 0 else ""
instances = SWEBenchInstances(subset=subset, split=split, slice=slice_expr).get_instance_configs()
ids = []
meta = []
for inst in instances:
    iid = inst.problem_statement.id
    image = inst.env.deployment.image
    ids.append(iid)
    meta.append({"id": iid, "image": image})
cache_ids.parent.mkdir(parents=True, exist_ok=True)
cache_meta.parent.mkdir(parents=True, exist_ok=True)
cache_ids.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")
cache_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"cached {len(ids)} ids -> {cache_ids}")
print(f"cached {len(meta)} id/image rows -> {cache_meta}")
PY
}

next_incomplete_index() {
  "${PYTHON_BIN}" - <<'PY' "${CACHE_FILE}" "${OUTDIR}" "${STOP_INDEX}"
import json
import pathlib
import sys

cache_file = pathlib.Path(sys.argv[1])
outdir = pathlib.Path(sys.argv[2])
stop = int(sys.argv[3])
ids = json.loads(cache_file.read_text(encoding="utf-8"))
for i, iid in enumerate(ids[:stop]):
    traj = outdir / iid / f"{iid}.traj"
    if not traj.exists():
        print(i)
        raise SystemExit(0)
print(stop)
PY
}

images_for_ranges() {
  "${PYTHON_BIN}" - <<'PY' "${CACHE_META_FILE}" "$@"
import json
import pathlib
import sys

meta_path = pathlib.Path(sys.argv[1])
raw_ranges = sys.argv[2:]
rows = json.loads(meta_path.read_text(encoding="utf-8"))
images = []

def parse_range(text: str):
    if ":" not in text:
        return None
    a, b = text.split(":", 1)
    if not a.isdigit() or not b.isdigit():
        return None
    return int(a), int(b)

for rtxt in raw_ranges:
    parsed = parse_range(rtxt)
    if not parsed:
        continue
    s, e = parsed
    if s < 0:
        s = 0
    if e < s:
        e = s
    for row in rows[s:e]:
        image = row.get("image")
        if image:
            images.append(image)

seen = set()
for img in images:
    if img in seen:
        continue
    seen.add(img)
    print(img)
PY
}

prefetch_images_for_range() {
  local start="$1"
  local end="$2"
  local prefetch_log="$3"
  if (( start >= end )); then
    return 0
  fi
  echo "Prefetch images for window ${start}:${end}" | tee -a "${prefetch_log}"
  while IFS= read -r image; do
    [[ -z "${image}" ]] && continue
    if docker image inspect "${image}" >/dev/null 2>&1; then
      echo "[prefetch] exists: ${image}" | tee -a "${prefetch_log}"
      continue
    fi
    echo "[prefetch] pull: ${image}" | tee -a "${prefetch_log}"
    docker pull "${image}" >>"${prefetch_log}" 2>&1 || {
      echo "[prefetch] WARN pull failed: ${image}" | tee -a "${prefetch_log}"
    }
  done < <(images_for_ranges "${start}:${end}")
}

cleanup_prev_window_images() {
  local prev_start="$1"
  local prev_end="$2"
  local current_start="$3"
  local current_end="$4"
  local next_start="$5"
  local next_end="$6"
  local cleanup_log="$7"

  if (( prev_start >= prev_end )); then
    return 0
  fi

  echo "Cleanup images for prev window ${prev_start}:${prev_end}" | tee -a "${cleanup_log}"

  local tmp_keep tmp_prev
  tmp_keep="$(mktemp)"
  tmp_prev="$(mktemp)"
  trap 'rm -f "${tmp_keep}" "${tmp_prev}"' RETURN

  {
    images_for_ranges "${current_start}:${current_end}"
    if (( next_start < next_end )); then
      images_for_ranges "${next_start}:${next_end}"
    fi
    IFS=',' read -ra base_ranges <<<"${KEEP_BASE_RANGES}"
    for br in "${base_ranges[@]}"; do
      images_for_ranges "${br}"
    done
  } | awk 'NF' | sort -u > "${tmp_keep}"

  images_for_ranges "${prev_start}:${prev_end}" | awk 'NF' | sort -u > "${tmp_prev}"

  while IFS= read -r image; do
    [[ -z "${image}" ]] && continue
    if grep -Fxq "${image}" "${tmp_keep}"; then
      echo "[cleanup] keep: ${image}" | tee -a "${cleanup_log}"
      continue
    fi
    if docker ps --format '{{.Image}}' | grep -Fxq "${image}"; then
      echo "[cleanup] skip in-use: ${image}" | tee -a "${cleanup_log}"
      continue
    fi
    echo "[cleanup] remove: ${image}" | tee -a "${cleanup_log}"
    docker rmi -f "${image}" >>"${cleanup_log}" 2>&1 || true
  done < "${tmp_prev}"
}

verify_event_logs() {
  "${PYTHON_BIN}" - <<'PY' "${WS_ROOT}" "${EVENT_LOG_GLOB}"
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
  current_start="${START_INDEX}"
  prev_start=-1
  prev_end=-1

  while (( current_start < STOP_INDEX )); do
    current_end=$((current_start + WINDOW_SIZE))
    if (( current_end > STOP_INDEX )); then
      current_end=${STOP_INDEX}
    fi
    next_start=${current_end}
    next_end=$((next_start + WINDOW_SIZE))
    if (( next_end > STOP_INDEX )); then
      next_end=${STOP_INDEX}
    fi

    event_log="${EXP_DIR}/logs/with_mem_tool_events_window_${current_start}_${current_end}.jsonl"
    run_log="${EXP_DIR}/logs/run_with_mem_window_${current_start}_${current_end}.log"
    prefetch_log="${EXP_DIR}/logs/prefetch_window_${current_start}_${current_end}.log"
    cleanup_log="${EXP_DIR}/logs/cleanup_window_${current_start}_${current_end}.log"

    export SWE_AGENT_EXT_TOOLS_LOG_FILE="${event_log}"
    export SWE_AGENT_EXT_RUN_ID="${EXPERIMENT_ID}"
    export SWE_AGENT_EXT_ATTEMPT_ID="window-${current_start}-${current_end}"
    export AGENT_MEM_STORAGE_DIR AGENT_MEM_EVIDENCE_DIR AGENT_MEM_EMBEDDING_MODEL AGENT_MEM_EMBEDDING_MODEL_NAME
    export AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS
    export SWE_AGENT_EXT_TOOL_A_TIMEOUT_SEC SWE_AGENT_EXT_TOOL_RETRY_TIMEOUT_SEC SWE_AGENT_EXT_TOOL_MAX_RETRIES

    echo "Window run plan: start=${current_start} end=${current_end} next_start=${next_start} next_end=${next_end} stop=${STOP_INDEX}"
    echo "Prefetch current window images..."
    prefetch_images_for_range "${current_start}" "${current_end}" "${prefetch_log}"

    prefetch_next_pid=""
    if [[ "${PREFETCH_NEXT_WINDOW}" == "1" && ${next_start} -lt ${next_end} ]]; then
      echo "Prefetch next window images in background..."
      (
        prefetch_images_for_range "${next_start}" "${next_end}" "${prefetch_log}"
      ) &
      prefetch_next_pid="$!"
    fi

    runtime_guard_preflight "${run_log}"
    run_status=1
    startup_retry_index=0
    while (( startup_retry_index <= STARTUP_RETRIES )); do
      [[ "${startup_retry_index}" -gt 0 ]] && echo "[retry] startup retry ${startup_retry_index}/${STARTUP_RETRIES} for window ${current_start}:${current_end}" | tee -a "${run_log}"
      set +e
      run_cmd=(
        "${START_WITH_TOOLS}" --mode with-mem
        "${SWEAGENT_BIN}" run-batch
        --config "${MODEL_CONFIG}"
        --instances.type swe_bench
        --instances.subset "${SWEBENCH_SUBSET}"
        --instances.split "${SWEBENCH_SPLIT}"
        --instances.deployment.type docker
        --instances.deployment.startup_timeout "${DEPLOYMENT_STARTUP_TIMEOUT_SEC}"
        --instances.slice "${current_start}:${current_end}"
        --output_dir "${OUTDIR}"
        --num_workers "${NUM_WORKERS}"
        --env_var_path "${ENV_VAR_PATH}"
        --agent.model.per_instance_call_limit "${PER_INSTANCE_CALL_LIMIT}"
        --agent.tools.total_execution_timeout "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}"
        --redo_existing "$(to_bool_token "${REDO_EXISTING}")"
      )
      if [[ -n "${PYTHON_STANDALONE_DIR}" && "${PYTHON_STANDALONE_DIR}" != "__NONE__" ]]; then
        run_cmd+=(--instances.deployment.python_standalone_dir "${PYTHON_STANDALONE_DIR}")
      fi
      "${run_cmd[@]}" 2>&1 | tee -a "${run_log}"
      run_status=$?
      set -e
      if [[ "${run_status}" -eq 0 ]]; then
        break
      fi
      if grep -q "Runtime did not start within timeout" "${run_log}"; then
        runtime_guard_capture_diag "${run_log}" "docker.io/swebench/sweb.eval.x86_64."
        runtime_guard_cleanup_pattern "${run_log}" "docker.io/swebench/sweb.eval.x86_64."
        (( startup_retry_index++ ))
        continue
      fi
      runtime_guard_capture_diag "${run_log}" "docker.io/swebench/sweb.eval.x86_64."
      break
    done
    if [[ "${run_status}" -ne 0 ]]; then
      echo "[window] run-batch exited with status ${run_status} for ${current_start}:${current_end}" | tee -a "${run_log}"
    fi

    if [[ -n "${prefetch_next_pid}" ]]; then
      wait "${prefetch_next_pid}" || true
    fi

    if (( prev_start >= 0 )); then
      cleanup_prev_window_images "${prev_start}" "${prev_end}" "${current_start}" "${current_end}" "${next_start}" "${next_end}" "${cleanup_log}"
    fi

    if [[ "${PRUNE_BUILD_CACHE_EACH_WINDOW}" == "1" ]]; then
      docker builder prune -f >/dev/null 2>&1 || true
    fi

    prev_start="${current_start}"
    prev_end="${current_end}"

    if [[ "${AUTO_CONTINUE}" != "1" ]]; then
      break
    fi
    current_start=${current_end}
  done
fi

verify_event_logs

"${PYTHON_BIN}" "${COMMON_DIR}/collect_run_manifest.py" \
  --workspace-root "${WS_ROOT}" \
  --experiment-id "${EXPERIMENT_ID}" \
  --mode "with-mem" \
  --subset "${SWEBENCH_SUBSET}" \
  --split "${SWEBENCH_SPLIT}" \
  --output-dir "${OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --start-index "${METRICS_START_INDEX}" \
  --stop-index "${METRICS_STOP_INDEX}" \
  --run-script "${RUN_SCRIPT_PATH}" \
  --model-config "${MODEL_CONFIG}" \
  --event-log-glob "${EVENT_LOG_GLOB}" \
  --require-event-logs \
  --manifest-out "${MANIFEST_OUT}"

"${PYTHON_BIN}" "${COMMON_DIR}/collect_run_metrics.py" \
  --workspace-root "${WS_ROOT}" \
  --experiment-id "${EXPERIMENT_ID}" \
  --subset-label "${SUBSET_LABEL}" \
  --mode "with-mem" \
  --output-dir "${OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --start-index "${METRICS_START_INDEX}" \
  --stop-index "${METRICS_STOP_INDEX}" \
  --event-log-glob "${EVENT_LOG_GLOB}" \
  --require-event-logs \
  --manifest-path "${MANIFEST_OUT}" \
  --metrics-out "${METRICS_OUT}"
