#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
FORMAL_STARTER="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/start_kimi_same_only_formal_phase8_tmux.sh"
FORMAL_PREFETCHER="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/prefetch_kimi_same_only_formal_phase8.sh"
ENV_FILE="${ENV_FILE:-${SWE_AGENT_ROOT}/.env}"

usage() {
  cat <<'EOF'
Usage:
  run_kimi25_formal_same_only.sh [options]

Options:
  --mode NAME          full|prepare|run ; default full
  --case-start N        1-based inclusive start case index in SWE-bench Lite test
  --case-end N          1-based inclusive end case index in SWE-bench Lite test
  --run-tag TAG         Explicit run tag; default is stable per selected range
  --repeats N           Attempt repeats per case; default 10
  --split NAME          Dataset split; default test
  --subset NAME         Dataset subset; default lite
  --source-same-json P  Use an explicit instance list JSON instead of generating from case range
  -h, --help            Show this help
EOF
}

CASE_START_1BASED="${CASE_START_1BASED:-1}"
CASE_END_1BASED="${CASE_END_1BASED:-}"
SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-lite}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
SOURCE_SAME_JSON="${SOURCE_SAME_JSON:-}"
CASE_START_EXPLICIT="${CASE_START_EXPLICIT:-0}"
CASE_END_EXPLICIT="${CASE_END_EXPLICIT:-0}"
MODE="${MODE:-full}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    --case-start)
      CASE_START_1BASED="$2"
      CASE_START_EXPLICIT=1
      shift 2
      ;;
    --case-end)
      CASE_END_1BASED="$2"
      CASE_END_EXPLICIT=1
      shift 2
      ;;
    --run-tag)
      RUN_TAG="$2"
      shift 2
      ;;
    --repeats)
      REPEATS="$2"
      shift 2
      ;;
    --split)
      SWEBENCH_SPLIT="$2"
      shift 2
      ;;
    --subset)
      SWEBENCH_SUBSET="$2"
      shift 2
      ;;
    --source-same-json)
      SOURCE_SAME_JSON="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "${MODE}" in
  full|prepare|run)
    ;;
  *)
    echo "--mode must be one of: full, prepare, run" >&2
    exit 2
    ;;
esac

if ! [[ "${CASE_START_1BASED}" =~ ^[0-9]+$ ]]; then
  echo "--case-start must be an integer >= 1" >&2
  exit 2
fi
if (( CASE_START_1BASED < 1 )); then
  echo "--case-start must be >= 1" >&2
  exit 2
fi
if [[ -n "${CASE_END_1BASED}" ]]; then
  if ! [[ "${CASE_END_1BASED}" =~ ^[0-9]+$ ]]; then
    echo "--case-end must be an integer >= case-start" >&2
    exit 2
  fi
  if (( CASE_END_1BASED < CASE_START_1BASED )); then
    echo "--case-end must be >= --case-start" >&2
    exit 2
  fi
fi

if [[ ! -x "${FORMAL_STARTER}" ]]; then
  echo "formal starter not found or not executable: ${FORMAL_STARTER}" >&2
  exit 2
fi
if [[ ! -x "${FORMAL_PREFETCHER}" ]]; then
  echo "formal prefetcher not found or not executable: ${FORMAL_PREFETCHER}" >&2
  exit 2
fi

# Best effort: if the current shell did not export the key, try the local SWE-agent env file.
if [[ -z "${MOONSHOT_API_KEY:-}" && -z "${SILICONFLOW_API_KEY:-}" && -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

if [[ -z "${MOONSHOT_API_KEY:-}" && -z "${SILICONFLOW_API_KEY:-}" ]]; then
  echo "MOONSHOT_API_KEY is not set. Export it first or put it into ${ENV_FILE}." >&2
  exit 2
fi

REPEATS="${REPEATS:-10}"
PROMPT_PROFILE="${PROMPT_PROFILE:-prompt_base}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_moonshot.yaml}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
GLOBAL_HEAVY_SLOTS="${GLOBAL_HEAVY_SLOTS:-2}"
NOMEM_HEAVY_SLOTS="${NOMEM_HEAVY_SLOTS:-1}"
WITHMEM_HEAVY_SLOTS="${WITHMEM_HEAVY_SLOTS:-1}"
MAX_ACTIVE_RUN_BATCHES="${MAX_ACTIVE_RUN_BATCHES:-2}"
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

if [[ -z "${RUN_TAG:-}" ]]; then
  if [[ -n "${SOURCE_SAME_JSON}" ]]; then
    RUN_TAG="phase8_same_only_kimi_formal_custom_$(date +%Y%m%d_%H%M%S)"
  else
    start_label="$(printf "%03d" "${CASE_START_1BASED}")"
    if [[ -n "${CASE_END_1BASED}" ]]; then
      end_label="$(printf "%03d" "${CASE_END_1BASED}")"
    else
      end_label="end"
    fi
    RUN_TAG="phase8_same_only_kimi_formal_lite_${start_label}_${end_label}"
  fi
fi

echo "Starting Kimi 2.5 formal same-only run"
echo "mode=${MODE}"
echo "run_tag=${RUN_TAG}"
echo "subset=${SWEBENCH_SUBSET}"
echo "split=${SWEBENCH_SPLIT}"
echo "case_start_1based=${CASE_START_1BASED}"
echo "case_end_1based=${CASE_END_1BASED:-auto_last}"
if [[ -n "${SOURCE_SAME_JSON}" ]]; then
  echo "source_same_json=${SOURCE_SAME_JSON}"
fi
echo "model_config=${MODEL_CONFIG}"
echo "repeats=${REPEATS}"
echo "nomem_timeout_sec=${NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}"
echo "withmem_timeout_sec=${WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}"
echo "env_error_retries=${ENV_ERROR_RETRIES}"
echo "image_pull_timeout_sec=${IMAGE_PULL_TIMEOUT_SEC}"
echo "prepare_slots=${PHASE7_PREPARE_SLOTS}"
echo "nomem_runtime_prewarm=${NOMEM_RUNTIME_PREWARM}"
echo "withmem_runtime_prewarm=${WITHMEM_RUNTIME_PREWARM}"

common_env=(
  MOONSHOT_API_KEY="${MOONSHOT_API_KEY:-}"
  SILICONFLOW_API_KEY="${SILICONFLOW_API_KEY:-}"
  RUN_TAG="${RUN_TAG}"
  REPEATS="${REPEATS}"
  SWEBENCH_SUBSET="${SWEBENCH_SUBSET}"
  SWEBENCH_SPLIT="${SWEBENCH_SPLIT}"
  CASE_START_1BASED="${CASE_START_1BASED}"
  CASE_END_1BASED="${CASE_END_1BASED}"
  CASE_START_EXPLICIT="${CASE_START_EXPLICIT}"
  CASE_END_EXPLICIT="${CASE_END_EXPLICIT}"
  SOURCE_SAME_JSON="${SOURCE_SAME_JSON}"
  PROMPT_PROFILE="${PROMPT_PROFILE}"
  MODEL_CONFIG="${MODEL_CONFIG}"
  PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT}"
  GLOBAL_HEAVY_SLOTS="${GLOBAL_HEAVY_SLOTS}"
  NOMEM_HEAVY_SLOTS="${NOMEM_HEAVY_SLOTS}"
  WITHMEM_HEAVY_SLOTS="${WITHMEM_HEAVY_SLOTS}"
  MAX_ACTIVE_RUN_BATCHES="${MAX_ACTIVE_RUN_BATCHES}"
  NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}"
  WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}"
  MAX_WORKERS_EVAL="${MAX_WORKERS_EVAL}"
  EVAL_TIMEOUT_SEC="${EVAL_TIMEOUT_SEC}"
  ENV_ERROR_RETRIES="${ENV_ERROR_RETRIES}"
  IMAGE_PULL_TIMEOUT_SEC="${IMAGE_PULL_TIMEOUT_SEC}"
  PHASE7_PREPARE_SLOTS="${PHASE7_PREPARE_SLOTS}"
  PHASE7_PREPARE_SLOT_POLL_SEC="${PHASE7_PREPARE_SLOT_POLL_SEC}"
  NOMEM_RUNTIME_PREWARM="${NOMEM_RUNTIME_PREWARM}"
  WITHMEM_RUNTIME_PREWARM="${WITHMEM_RUNTIME_PREWARM}"
  NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC="${NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC}"
  WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC="${WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC}"
  NOMEM_PYTHON_STANDALONE_DIR="${NOMEM_PYTHON_STANDALONE_DIR}"
  WITHMEM_PYTHON_STANDALONE_DIR="${WITHMEM_PYTHON_STANDALONE_DIR}"
)

case "${MODE}" in
  full)
    env "${common_env[@]}" "${FORMAL_STARTER}"
    ;;
  prepare)
    setup_output="$(env "${common_env[@]}" SETUP_ONLY=1 "${FORMAL_STARTER}")"
    printf '%s\n' "${setup_output}"
    run_root="$(printf '%s\n' "${setup_output}" | awk -F= '/^run_root=/{print $2}')"
    same_json="$(printf '%s\n' "${setup_output}" | awk -F= '/^same_json=/{print $2}')"
    if [[ -z "${run_root}" || -z "${same_json}" ]]; then
      echo "failed to resolve run_root/same_json during setup-only phase" >&2
      exit 3
    fi
    env \
      "${common_env[@]}" \
      RUN_ROOT="${run_root}" \
      SAME_JSON="${same_json}" \
      NOMEM_RUNTIME_PREWARM="${PREPARE_NOMEM_RUNTIME_PREWARM:-1}" \
      WITHMEM_RUNTIME_PREWARM="${PREPARE_WITHMEM_RUNTIME_PREWARM:-1}" \
      NOMEM_PYTHON_STANDALONE_DIR="${PREPARE_NOMEM_PYTHON_STANDALONE_DIR:-${NOMEM_PYTHON_STANDALONE_DIR}}" \
      WITHMEM_PYTHON_STANDALONE_DIR="${PREPARE_WITHMEM_PYTHON_STANDALONE_DIR:-${WITHMEM_PYTHON_STANDALONE_DIR}}" \
      HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" \
      HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}" \
      "${FORMAL_PREFETCHER}"
    ;;
  run)
    env \
      "${common_env[@]}" \
      SKIP_INSTANCE_PREPARE=1 \
      HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" \
      HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}" \
      "${FORMAL_STARTER}"
    ;;
esac
