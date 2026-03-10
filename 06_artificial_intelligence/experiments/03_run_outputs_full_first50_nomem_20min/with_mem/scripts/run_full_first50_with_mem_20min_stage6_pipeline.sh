#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
RUNNER="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/scripts/run_full_first50_with_mem_20min_windowed_prefetch.sh"
EVAL_RUNNER="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/scripts/run_official_eval_full50_withmem_20min.sh"
BEHAVIOR_ANALYZER="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common/analyze_memory_behavior.py"
EVAL_FEEDBACK_APPLIER="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common/apply_official_eval_feedback.py"

RUN_TAG="${RUN_TAG:-stage6_full50_withmem_20min_$(date +%Y%m%d_%H%M%S)}"
BASE_EXP_DIR="${BASE_EXP_DIR:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/reruns}"
EXP_DIR="${EXP_DIR:-${BASE_EXP_DIR}/${RUN_TAG}}"
OUTDIR="${OUTDIR:-${EXP_DIR}/outputs/run_outputs_full_first50_with_mem_20min}"
CACHE_FILE="${CACHE_FILE:-${EXP_DIR}/cache/full_test_instances_cache.json}"
CACHE_META_FILE="${CACHE_META_FILE:-${EXP_DIR}/cache/full_test_instances_cache_with_images.json}"
METRICS_DIR="${METRICS_DIR:-${EXP_DIR}/metrics}"
NOTES_DIR="${NOTES_DIR:-${EXP_DIR}/notes}"
MANIFEST_OUT="${MANIFEST_OUT:-${METRICS_DIR}/manifest_stage6_full_first50_withmem_20min.json}"
METRICS_OUT="${METRICS_OUT:-${METRICS_DIR}/metrics_stage6_full_first50_withmem_20min.json}"
BEHAVIOR_JSON="${BEHAVIOR_JSON:-${METRICS_DIR}/memory_behavior_stage6_full50.json}"
BEHAVIOR_MD="${BEHAVIOR_MD:-${NOTES_DIR}/memory_behavior_stage6_full50.md}"
EVAL_FEEDBACK_JSON="${EVAL_FEEDBACK_JSON:-${METRICS_DIR}/official_eval_feedback_exp02_full_first50_withmem_20min.json}"

mkdir -p "${EXP_DIR}" "${METRICS_DIR}" "${NOTES_DIR}"

START_INDEX="${START_INDEX:-0}"
STOP_INDEX="${STOP_INDEX:-50}"
WINDOW_SIZE="${WINDOW_SIZE:-25}"
AUTO_CONTINUE="${AUTO_CONTINUE:-1}"
NUM_WORKERS="${NUM_WORKERS:-1}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
REDO_EXISTING="${REDO_EXISTING:-0}"

export EXPERIMENT_ID="${EXPERIMENT_ID:-阶段6_full_first50_withmem_20min}"
export RUN_SCRIPT_PATH="PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/scripts/run_full_first50_with_mem_20min_stage6_pipeline.sh"
export SUBSET_LABEL="${SUBSET_LABEL:-SWE-bench Full first50 with_mem (stage6, 20min cap)}"
export AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS="${AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS:-1}"
export AGENT_MEM_ENABLE_LLM_EXTRACTION="${AGENT_MEM_ENABLE_LLM_EXTRACTION:-1}"
export AGENT_MEM_LLM_EXTRACT_MODE="${AGENT_MEM_LLM_EXTRACT_MODE:-hybrid}"
export AGENT_MEM_EXTRACT_MAX_SIGNALS="${AGENT_MEM_EXTRACT_MAX_SIGNALS:-0}"
export AGENT_MEM_EXTRACT_MAX_ABSTRACTS="${AGENT_MEM_EXTRACT_MAX_ABSTRACTS:-0}"
export AGENT_MEM_EXTRACT_MAX_REPAIR_PATTERNS="${AGENT_MEM_EXTRACT_MAX_REPAIR_PATTERNS:-0}"
export AGENT_MEM_MAX_HINTS="${AGENT_MEM_MAX_HINTS:-0}"
export SWE_AGENT_MEM_FAMILY_COOLDOWN_STEPS="${SWE_AGENT_MEM_FAMILY_COOLDOWN_STEPS:-4}"
export SWE_AGENT_MEM_MAX_HINTS_PER_FAMILY_PER_ATTEMPT="${SWE_AGENT_MEM_MAX_HINTS_PER_FAMILY_PER_ATTEMPT:-1}"
export SWE_AGENT_EXT_TOOL_A_TIMEOUT_SEC="${SWE_AGENT_EXT_TOOL_A_TIMEOUT_SEC:-90}"
export SWE_AGENT_EXT_TOOL_B_TIMEOUT_SEC="${SWE_AGENT_EXT_TOOL_B_TIMEOUT_SEC:-120}"
export SWE_AGENT_EXT_TOOL_RETRY_TIMEOUT_SEC="${SWE_AGENT_EXT_TOOL_RETRY_TIMEOUT_SEC:-150}"
export SWE_AGENT_EXT_TOOL_MAX_RETRIES="${SWE_AGENT_EXT_TOOL_MAX_RETRIES:-1}"

echo "[1/4] run stage6 with_mem full first50"
START_INDEX="${START_INDEX}" \
STOP_INDEX="${STOP_INDEX}" \
WINDOW_SIZE="${WINDOW_SIZE}" \
AUTO_CONTINUE="${AUTO_CONTINUE}" \
NUM_WORKERS="${NUM_WORKERS}" \
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT}" \
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
REDO_EXISTING="${REDO_EXISTING}" \
EXP_DIR="${EXP_DIR}" \
OUTDIR="${OUTDIR}" \
CACHE_FILE="${CACHE_FILE}" \
CACHE_META_FILE="${CACHE_META_FILE}" \
METRICS_DIR="${METRICS_DIR}" \
MANIFEST_OUT="${MANIFEST_OUT}" \
METRICS_OUT="${METRICS_OUT}" \
"${RUNNER}"

echo "[2/4] run official evaluation"
OUTDIR="${OUTDIR}" \
CACHE_FILE="${CACHE_FILE}" \
METRICS_DIR="${METRICS_DIR}" \
NOTES_DIR="${NOTES_DIR}" \
"${EVAL_RUNNER}"

echo "[3/4] apply official eval feedback"
"${PYTHON_BIN}" "${EVAL_FEEDBACK_APPLIER}" \
  --workspace-root "${WS_ROOT}" \
  --report-json "${METRICS_DIR}/official_eval_report_exp02_full_first50_withmem_20min.json" \
  --output-dir "${OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --run-id "${RUN_TAG}" \
  --output-json "${EVAL_FEEDBACK_JSON}"

echo "[4/4] analyze memory behavior"
"${PYTHON_BIN}" "${BEHAVIOR_ANALYZER}" \
  --exp-dir "${EXP_DIR}" \
  --metrics-json "${METRICS_OUT}" \
  --manifest-json "${MANIFEST_OUT}" \
  --official-summary-json "${METRICS_DIR}/official_eval_summary_exp02_full_first50_withmem_20min.json" \
  --output-json "${BEHAVIOR_JSON}" \
  --output-md "${BEHAVIOR_MD}" \
  --scope "阶段6 full first50 with_mem"

echo "done"
echo "exp_dir=${EXP_DIR}"
echo "metrics=${METRICS_OUT}"
echo "behavior_report=${BEHAVIOR_MD}"
