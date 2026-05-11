#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
RUNS_ROOT="${RUNS_ROOT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase8}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_moonshot.yaml}"
PROMPT_PROFILE="${PROMPT_PROFILE:-prompt_base}"
RUN_TAG="${RUN_TAG:-phase8_same_only_kimi_formal_lite_001_end}"
RUN_ROOT="${RUN_ROOT:-${RUNS_ROOT}/${RUN_TAG}}"
REPEATS="${REPEATS:-10}"
SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-lite}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
CASE_START_1BASED="${CASE_START_1BASED:-1}"
CASE_END_1BASED="${CASE_END_1BASED:-}"
CASE_START_EXPLICIT="${CASE_START_EXPLICIT:-0}"
CASE_END_EXPLICIT="${CASE_END_EXPLICIT:-0}"
SOURCE_SAME_JSON="${SOURCE_SAME_JSON:-}"
ALLOW_RESUME_EXISTING_RUN_ROOT="${ALLOW_RESUME_EXISTING_RUN_ROOT:-1}"
GLOBAL_HEAVY_SLOTS="${GLOBAL_HEAVY_SLOTS:-2}"
NOMEM_HEAVY_SLOTS="${NOMEM_HEAVY_SLOTS:-1}"
WITHMEM_HEAVY_SLOTS="${WITHMEM_HEAVY_SLOTS:-1}"
MAX_ACTIVE_RUN_BATCHES="${MAX_ACTIVE_RUN_BATCHES:-2}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
MAX_WORKERS_EVAL="${MAX_WORKERS_EVAL:-1}"
EVAL_TIMEOUT_SEC="${EVAL_TIMEOUT_SEC:-1200}"
ENV_ERROR_RETRIES="${ENV_ERROR_RETRIES:-1}"
IMAGE_PULL_TIMEOUT_SEC="${IMAGE_PULL_TIMEOUT_SEC:-1800}"
PHASE7_PREPARE_SLOTS="${PHASE7_PREPARE_SLOTS:-2}"
PHASE7_PREPARE_SLOT_POLL_SEC="${PHASE7_PREPARE_SLOT_POLL_SEC:-10}"
NOMEM_RUNTIME_PREWARM="${NOMEM_RUNTIME_PREWARM:-0}"
WITHMEM_RUNTIME_PREWARM="${WITHMEM_RUNTIME_PREWARM:-1}"
NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC="${NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC:-1800}"
WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC="${WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC:-1800}"
NOMEM_PYTHON_STANDALONE_DIR="${NOMEM_PYTHON_STANDALONE_DIR:-/root}"
WITHMEM_PYTHON_STANDALONE_DIR="${WITHMEM_PYTHON_STANDALONE_DIR:-/root}"
SKIP_INSTANCE_PREPARE="${SKIP_INSTANCE_PREPARE:-0}"
HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}"
HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-0}"
SETUP_ONLY="${SETUP_ONLY:-0}"
RESUME_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/resume_same_only_phase8.sh"
INVENTORY_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/collect_same_only_trial_inventory.py"
SELECTOR_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/select_lite_instances_range.py"
PYTHON_BIN="${WS_ROOT}/SWE-agent/.venv/bin/python"
SWE_AGENT_ENV_FILE="${SWE_AGENT_ENV_FILE:-${WS_ROOT}/SWE-agent/.env}"

if [[ -f "${SWE_AGENT_ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${SWE_AGENT_ENV_FILE}"
  set +a
fi

if [[ -z "${MOONSHOT_API_KEY:-}" && -z "${SILICONFLOW_API_KEY:-}" ]]; then
  echo "MOONSHOT_API_KEY is required for Moonshot Kimi. SILICONFLOW_API_KEY is still accepted for legacy SiliconFlow configs." >&2
  exit 2
fi
if ! [[ "${CASE_START_1BASED}" =~ ^[0-9]+$ ]] || (( CASE_START_1BASED < 1 )); then
  echo "CASE_START_1BASED must be an integer >= 1" >&2
  exit 2
fi
if [[ -n "${CASE_END_1BASED}" ]]; then
  if ! [[ "${CASE_END_1BASED}" =~ ^[0-9]+$ ]] || (( CASE_END_1BASED < CASE_START_1BASED )); then
    echo "CASE_END_1BASED must be an integer >= CASE_START_1BASED" >&2
    exit 2
  fi
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "python not found: ${PYTHON_BIN}" >&2
  exit 2
fi
if [[ -n "${SOURCE_SAME_JSON}" && ! -f "${SOURCE_SAME_JSON}" ]]; then
  echo "source same instance list not found: ${SOURCE_SAME_JSON}" >&2
  exit 2
fi
if [[ ! -f "${SELECTOR_SCRIPT}" ]]; then
  echo "selector script not found: ${SELECTOR_SCRIPT}" >&2
  exit 2
fi

INSTANCE_LIST_JSON="${RUN_ROOT}/same_instances.json"
EXISTING_RUN=0
if [[ -e "${RUN_ROOT}" && ! -d "${RUN_ROOT}" ]]; then
  echo "RUN_ROOT exists but is not a directory: ${RUN_ROOT}" >&2
  exit 2
fi
if [[ -d "${RUN_ROOT}" ]]; then
  EXISTING_RUN=1
  if [[ "${ALLOW_RESUME_EXISTING_RUN_ROOT}" != "1" ]]; then
    echo "target RUN_ROOT already exists and resume is disabled: ${RUN_ROOT}" >&2
    exit 2
  fi
fi

mkdir -p "${RUN_ROOT}/orchestrator_logs" "${RUN_ROOT}/orchestrator_state" "${RUN_ROOT}/notes"

if [[ ! -f "${INSTANCE_LIST_JSON}" ]]; then
  if [[ "${EXISTING_RUN}" -eq 1 && -z "${SOURCE_SAME_JSON}" ]]; then
    echo "existing RUN_ROOT is missing same_instances.json: ${RUN_ROOT}" >&2
    exit 2
  fi
  if [[ -n "${SOURCE_SAME_JSON}" ]]; then
    cp "${SOURCE_SAME_JSON}" "${INSTANCE_LIST_JSON}"
  else
    selector_args=(
      "${PYTHON_BIN}" "${SELECTOR_SCRIPT}"
      --workspace-root "${WS_ROOT}"
      --subset "${SWEBENCH_SUBSET}"
      --split "${SWEBENCH_SPLIT}"
      --case-start "${CASE_START_1BASED}"
      --repeats "${REPEATS}"
      --out "${INSTANCE_LIST_JSON}"
    )
    if [[ -n "${CASE_END_1BASED}" ]]; then
      selector_args+=(--case-end "${CASE_END_1BASED}")
    fi
    "${selector_args[@]}" >/dev/null
  fi
fi

INSTANCE_COUNT=""
STORED_REPEATS=""
STORED_CASE_START=""
STORED_CASE_END=""
STORED_SUBSET=""
STORED_SPLIT=""
while IFS='=' read -r key value; do
  case "${key}" in
    INSTANCE_COUNT) INSTANCE_COUNT="${value}" ;;
    STORED_REPEATS) STORED_REPEATS="${value}" ;;
    STORED_CASE_START) STORED_CASE_START="${value}" ;;
    STORED_CASE_END) STORED_CASE_END="${value}" ;;
    STORED_SUBSET) STORED_SUBSET="${value}" ;;
    STORED_SPLIT) STORED_SPLIT="${value}" ;;
  esac
done < <("${PYTHON_BIN}" - <<'PY' "${INSTANCE_LIST_JSON}"
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
ids = payload.get("instance_ids", [])
print(f"INSTANCE_COUNT={len(ids) if isinstance(ids, list) else 0}")
print(f"STORED_REPEATS={payload.get('repeats', '')}")
print(f"STORED_CASE_START={payload.get('case_start_1based', '')}")
print(f"STORED_CASE_END={payload.get('case_end_1based', '')}")
print(f"STORED_SUBSET={payload.get('subset', '')}")
print(f"STORED_SPLIT={payload.get('split', '')}")
PY
)

if [[ -z "${INSTANCE_COUNT}" || "${INSTANCE_COUNT}" == "0" ]]; then
  echo "same_instances.json contains no instance_ids: ${INSTANCE_LIST_JSON}" >&2
  exit 2
fi
if [[ -n "${STORED_REPEATS}" && "${STORED_REPEATS}" != "0" && "${REPEATS}" != "${STORED_REPEATS}" ]]; then
  echo "REPEATS=${REPEATS} does not match stored repeats=${STORED_REPEATS} in ${INSTANCE_LIST_JSON}" >&2
  exit 2
fi
if [[ "${EXISTING_RUN}" -eq 1 ]]; then
  if [[ "${CASE_START_EXPLICIT}" == "1" && -n "${STORED_CASE_START}" && "${CASE_START_1BASED}" != "${STORED_CASE_START}" ]]; then
    echo "CASE_START_1BASED=${CASE_START_1BASED} does not match stored value ${STORED_CASE_START} for ${RUN_ROOT}" >&2
    exit 2
  fi
  if [[ "${CASE_END_EXPLICIT}" == "1" && -n "${CASE_END_1BASED}" && -n "${STORED_CASE_END}" && "${CASE_END_1BASED}" != "${STORED_CASE_END}" ]]; then
    echo "CASE_END_1BASED=${CASE_END_1BASED} does not match stored value ${STORED_CASE_END} for ${RUN_ROOT}" >&2
    exit 2
  fi
fi

if [[ "${EXISTING_RUN}" -eq 1 && "${CASE_START_EXPLICIT}" != "1" && -n "${STORED_CASE_START}" ]]; then
  CASE_START_1BASED="${STORED_CASE_START}"
fi
if [[ -z "${CASE_END_1BASED}" && -n "${STORED_CASE_END}" ]]; then
  CASE_END_1BASED="${STORED_CASE_END}"
fi

SANITIZED_TAG="${RUN_TAG//[^A-Za-z0-9_]/_}"
MAIN_SESSION="${MAIN_SESSION:-${SANITIZED_TAG}_same_only}"
INDEX_SESSION="${INDEX_SESSION:-${SANITIZED_TAG}_trial_index}"
MAIN_LOG="${RUN_ROOT}/orchestrator_logs/same_only_resume.tmux.log"
INDEX_LOG="${RUN_ROOT}/orchestrator_logs/trial_indexer.tmux.log"

if tmux has-session -t "${MAIN_SESSION}" 2>/dev/null; then
  echo "main tmux session already running: ${MAIN_SESSION}" >&2
  exit 3
fi
if tmux has-session -t "${INDEX_SESSION}" 2>/dev/null; then
  echo "index tmux session already running: ${INDEX_SESSION}" >&2
  exit 3
fi

"${PYTHON_BIN}" - <<'PY' \
  "${RUN_ROOT}" \
  "${INSTANCE_LIST_JSON}" \
  "${MODEL_CONFIG}" \
  "${PROMPT_PROFILE}" \
  "${REPEATS}" \
  "${ENV_ERROR_RETRIES}" \
  "${NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
  "${WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
  "${IMAGE_PULL_TIMEOUT_SEC}" \
  "${PHASE7_PREPARE_SLOTS}" \
  "${PHASE7_PREPARE_SLOT_POLL_SEC}" \
  "${NOMEM_RUNTIME_PREWARM}" \
  "${WITHMEM_RUNTIME_PREWARM}" \
  "${NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC}" \
  "${WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC}" \
  "${NOMEM_PYTHON_STANDALONE_DIR}" \
  "${WITHMEM_PYTHON_STANDALONE_DIR}"
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

run_root = Path(sys.argv[1]).resolve()
same_json = Path(sys.argv[2]).resolve()
model_config = sys.argv[3]
prompt_profile = sys.argv[4]
repeats = int(sys.argv[5])
env_error_retries = int(sys.argv[6])
nomem_timeout = int(sys.argv[7])
withmem_timeout = int(sys.argv[8])
image_pull_timeout = int(sys.argv[9])
prepare_slots = int(sys.argv[10])
prepare_slot_poll_sec = int(sys.argv[11])
nomem_runtime_prewarm = sys.argv[12]
withmem_runtime_prewarm = sys.argv[13]
nomem_runtime_warmup_timeout = int(sys.argv[14])
withmem_runtime_warmup_timeout = int(sys.argv[15])
nomem_python_standalone_dir = sys.argv[16]
withmem_python_standalone_dir = sys.argv[17]

instance_payload = json.loads(same_json.read_text(encoding="utf-8"))
manifest_path = run_root / "orchestrator_state" / "run_manifest.json"
existing = {}
if manifest_path.exists():
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        existing = {}

generated_at = existing.get("generated_at") or datetime.now(timezone.utc).isoformat()
instance_ids = instance_payload.get("instance_ids", [])
subset = instance_payload.get("subset", "lite")
split = instance_payload.get("split", "test")
case_start = instance_payload.get("case_start_1based")
case_end = instance_payload.get("case_end_1based")
selection_mode = instance_payload.get("selection_mode", "manual")
comparison_axis = (
    f"same-only repeated attempts on SWE-bench {subset} {split}, "
    f"cases {case_start}-{case_end}, {len(instance_ids)} instances total, "
    f"{repeats} attempts each, immediate per-attempt eval, NoMem vs WithMem, Kimi"
)

manifest = {
    "generated_at": generated_at,
    "last_launcher_invoked_at": datetime.now(timezone.utc).isoformat(),
    "experiment_type": "same_only_kimi_formal",
    "run_root": str(run_root),
    "same_instances_json": str(same_json),
    "model_config": model_config,
    "prompt_profile": prompt_profile,
    "repeats": repeats,
    "groups": ["nomem", "with_mem"],
    "comparison_axis": comparison_axis,
    "dataset": {
        "subset": subset,
        "split": split,
        "selection_mode": selection_mode,
        "case_start_1based": case_start,
        "case_end_1based": case_end,
        "instance_count": len(instance_ids),
    },
    "formal_policy": {
        "per_attempt_eval": True,
        "environment_error_retries": env_error_retries,
        "submitted_exit_format_counts_as_completed_attempt": True,
        "nomem_timeout_sec": nomem_timeout,
        "withmem_timeout_sec": withmem_timeout,
        "image_pull_timeout_sec": image_pull_timeout,
        "prepare_slots": prepare_slots,
        "prepare_slot_poll_sec": prepare_slot_poll_sec,
        "nomem_runtime_prewarm": nomem_runtime_prewarm,
        "withmem_runtime_prewarm": withmem_runtime_prewarm,
        "nomem_runtime_warmup_timeout_sec": nomem_runtime_warmup_timeout,
        "withmem_runtime_warmup_timeout_sec": withmem_runtime_warmup_timeout,
        "nomem_python_standalone_dir": nomem_python_standalone_dir,
        "withmem_python_standalone_dir": withmem_python_standalone_dir,
    },
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
PY

if [[ ! -f "${RUN_ROOT}/notes/trial_recording_plan.md" ]]; then
cat > "${RUN_ROOT}/notes/trial_recording_plan.md" <<'EOF'
# Kimi Formal Same-Only Trial Recording Plan

本次正式实验要求：

1. `NoMem` 与 `WithMem` 使用完全相同的 case 顺序与 case 范围。
2. 每个 attempt 一结束立即做 official eval，并立刻产生：
   - official_eval.json
   - summary.json
   - feedback.json（with_mem）
3. 环境级失败允许自动重试 1 次，再定性。
4. `submitted (exit_format)` 先记作一次正常 completed attempt，结果以 official eval 为准。

重点观测字段：

- 当前 case / 当前 attempt / 当前 step
- completed attempts
- resolved / unresolved / incomplete
- WithMem 的 memory_hint_buffered / memory_injected / feedback
EOF
fi

"${PYTHON_BIN}" "${INVENTORY_SCRIPT}" --run-root "${RUN_ROOT}" >/dev/null

if [[ "${SETUP_ONLY}" == "1" ]]; then
cat <<EOF
run_root=${RUN_ROOT}
same_json=${INSTANCE_LIST_JSON}
instance_count=${INSTANCE_COUNT}
case_start_1based=${STORED_CASE_START:-${CASE_START_1BASED}}
case_end_1based=${STORED_CASE_END:-${CASE_END_1BASED}}
trial_inventory=${RUN_ROOT}/orchestrator_state/trial_inventory.json
EOF
exit 0
fi

MAIN_ENV_FILE="${RUN_ROOT}/orchestrator_state/main_tmux.env"
cat > "${MAIN_ENV_FILE}" <<EOF
RUN_ROOT=${RUN_ROOT@Q}
RUN_TAG=${RUN_TAG@Q}
MODEL_CONFIG=${MODEL_CONFIG@Q}
PROMPT_PROFILE=${PROMPT_PROFILE@Q}
REPEATS=${REPEATS@Q}
SWEBENCH_SUBSET=${SWEBENCH_SUBSET@Q}
SWEBENCH_SPLIT=${SWEBENCH_SPLIT@Q}
GLOBAL_HEAVY_SLOTS=${GLOBAL_HEAVY_SLOTS@Q}
NOMEM_HEAVY_SLOTS=${NOMEM_HEAVY_SLOTS@Q}
WITHMEM_HEAVY_SLOTS=${WITHMEM_HEAVY_SLOTS@Q}
MAX_ACTIVE_RUN_BATCHES=${MAX_ACTIVE_RUN_BATCHES@Q}
PER_INSTANCE_CALL_LIMIT=${PER_INSTANCE_CALL_LIMIT@Q}
NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC=${NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC@Q}
WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC=${WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC@Q}
MAX_WORKERS_EVAL=${MAX_WORKERS_EVAL@Q}
EVAL_TIMEOUT_SEC=${EVAL_TIMEOUT_SEC@Q}
ENV_ERROR_RETRIES=${ENV_ERROR_RETRIES@Q}
IMAGE_PULL_TIMEOUT_SEC=${IMAGE_PULL_TIMEOUT_SEC@Q}
PHASE7_PREPARE_SLOTS=${PHASE7_PREPARE_SLOTS@Q}
PHASE7_PREPARE_SLOT_POLL_SEC=${PHASE7_PREPARE_SLOT_POLL_SEC@Q}
NOMEM_RUNTIME_PREWARM=${NOMEM_RUNTIME_PREWARM@Q}
WITHMEM_RUNTIME_PREWARM=${WITHMEM_RUNTIME_PREWARM@Q}
NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC=${NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC@Q}
WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC=${WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC@Q}
NOMEM_PYTHON_STANDALONE_DIR=${NOMEM_PYTHON_STANDALONE_DIR@Q}
WITHMEM_PYTHON_STANDALONE_DIR=${WITHMEM_PYTHON_STANDALONE_DIR@Q}
SKIP_INSTANCE_PREPARE=${SKIP_INSTANCE_PREPARE@Q}
HF_HUB_OFFLINE=${HF_HUB_OFFLINE@Q}
HF_DATASETS_OFFLINE=${HF_DATASETS_OFFLINE@Q}
EOF

tmux new-session -d -s "${MAIN_SESSION}" \
  "set -a; source '${SWE_AGENT_ENV_FILE}'; source '${MAIN_ENV_FILE}'; set +a; '${RESUME_SCRIPT}' >> '${MAIN_LOG}' 2>&1"

tmux new-session -d -s "${INDEX_SESSION}" \
  "while tmux has-session -t '${MAIN_SESSION}' 2>/dev/null; do '${PYTHON_BIN}' '${INVENTORY_SCRIPT}' --run-root '${RUN_ROOT}' >> '${INDEX_LOG}' 2>&1; sleep 30; done; '${PYTHON_BIN}' '${INVENTORY_SCRIPT}' --run-root '${RUN_ROOT}' >> '${INDEX_LOG}' 2>&1"

cat <<EOF
run_root=${RUN_ROOT}
same_json=${INSTANCE_LIST_JSON}
instance_count=${INSTANCE_COUNT}
case_start_1based=${STORED_CASE_START:-${CASE_START_1BASED}}
case_end_1based=${STORED_CASE_END:-${CASE_END_1BASED}}
main_session=${MAIN_SESSION}
index_session=${INDEX_SESSION}
main_log=${MAIN_LOG}
index_log=${INDEX_LOG}
trial_inventory=${RUN_ROOT}/orchestrator_state/trial_inventory.json
EOF
