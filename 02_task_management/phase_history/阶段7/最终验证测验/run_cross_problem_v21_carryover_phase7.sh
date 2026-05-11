#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
SWEAGENT_BIN="${SWEAGENT_BIN:-${SWE_AGENT_ROOT}/.venv/bin/sweagent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
START_WITH_TOOLS="${START_WITH_TOOLS:-${WS_ROOT}/PDDL_work_mem/source_code/sweagent_external_tools/bin/start_with_external_tools.sh}"
EVAL_STEP="${EVAL_STEP:-${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段7/最终验证测验/official_eval_step.py}"
RESOURCE_SLOT_SH="${RESOURCE_SLOT_SH:-${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段7/最终验证测验/with_resource_slot.sh}"

RUN_ROOT="${RUN_ROOT:?RUN_ROOT is required}"
INSTANCE_LIST_JSON="${INSTANCE_LIST_JSON:?INSTANCE_LIST_JSON is required}"
LABEL="${LABEL:?LABEL is required}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_siliconflow.yaml}"
PROMPT_PROFILE="${PROMPT_PROFILE:-prompt_base}"
SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-lite}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
ENV_VAR_PATH="${ENV_VAR_PATH:-${SWE_AGENT_ROOT}/.env}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1800}"
EVAL_TIMEOUT_SEC="${EVAL_TIMEOUT_SEC:-1800}"
MAX_WORKERS_EVAL="${MAX_WORKERS_EVAL:-1}"
RESUME_MODE="${RESUME_MODE:-1}"
REDO_EXISTING="${REDO_EXISTING:-0}"
DRY_RUN="${DRY_RUN:-0}"

EXP_DIR="${RUN_ROOT}/cross_problem/${LABEL}/v21_carryover"
OUTDIR="${EXP_DIR}/outputs"
LOG_DIR="${EXP_DIR}/logs"
METRICS_DIR="${EXP_DIR}/metrics"
PERSIST_DIR="${EXP_DIR}/persistence"
GRAPH_DIR="${PERSIST_DIR}/graph_store"
EVIDENCE_DIR="${PERSIST_DIR}/evidence_store"
SIDECAR_DIR="${PERSIST_DIR}/sidecar_store"
CACHE_DIR="${EXP_DIR}/cache"
mkdir -p "${OUTDIR}" "${LOG_DIR}" "${METRICS_DIR}/attempt_reports" "${METRICS_DIR}/attempt_summaries" "${METRICS_DIR}/attempt_feedback" "${GRAPH_DIR}" "${EVIDENCE_DIR}" "${SIDECAR_DIR}" "${CACHE_DIR}"
cp -f "${INSTANCE_LIST_JSON}" "${CACHE_DIR}/instance_ids.json"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[dry-run] cross-problem v21 carryover ${LABEL}"
  echo "instances_json=${INSTANCE_LIST_JSON}"
  exit 0
fi

export AGENT_MEM_STORAGE_DIR="${GRAPH_DIR}"
export AGENT_MEM_EVIDENCE_DIR="${EVIDENCE_DIR}"
export AGENT_MEM_V21_SIDECAR_DIR="${SIDECAR_DIR}"
export AGENT_MEM_V21_ENABLE_SUCCESS_FACT_HOTPATH="${AGENT_MEM_V21_ENABLE_SUCCESS_FACT_HOTPATH:-1}"
export AGENT_MEM_V21_ENABLE_SIDECAR="${AGENT_MEM_V21_ENABLE_SIDECAR:-1}"
export AGENT_MEM_V21_ENABLE_SUBTASK_PROJECTION="${AGENT_MEM_V21_ENABLE_SUBTASK_PROJECTION:-1}"
export AGENT_MEM_V21_ENABLE_CARD_COMPILER="${AGENT_MEM_V21_ENABLE_CARD_COMPILER:-1}"
export AGENT_MEM_V21_ENABLE_GOVERNANCE="${AGENT_MEM_V21_ENABLE_GOVERNANCE:-1}"

"${PYTHON_BIN}" - <<'PY' "${INSTANCE_LIST_JSON}"
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
for iid in json.loads(p.read_text(encoding="utf-8")).get("instance_ids", []):
    print(iid)
PY | while IFS= read -r iid; do
  attempt_dir="${OUTDIR}/${iid}/attempt_01"
  run_log="${LOG_DIR}/${iid}.attempt_01.log"
  event_log="${LOG_DIR}/${iid}.attempt_01.jsonl"
  pred_json="${METRICS_DIR}/attempt_reports/${iid}.attempt_01.predictions.json"
  report_json="${METRICS_DIR}/attempt_reports/${iid}.attempt_01.official_eval.json"
  summary_json="${METRICS_DIR}/attempt_summaries/${iid}.attempt_01.summary.json"
  feedback_json="${METRICS_DIR}/attempt_feedback/${iid}.attempt_01.feedback.json"

  if [[ "${RESUME_MODE}" == "1" && -f "${summary_json}" && -f "${feedback_json}" ]]; then
    echo "[resume] cross v21 ${LABEL} ${iid} already complete"
    continue
  fi

  mkdir -p "${attempt_dir}"
  export SWE_AGENT_EXT_TOOLS_LOG_FILE="${event_log}"
  export SWE_AGENT_EXT_INSTANCE_ID="${iid}"
  export SWE_AGENT_EXT_RUN_ID="phase7_cross_v21_${LABEL}"
  export SWE_AGENT_EXT_ATTEMPT_ID="attempt-01"

  set +e
  "${RESOURCE_SLOT_SH}" \
    --slot-dir "${PHASE7_HEAVY_SLOT_DIR:-${RUN_ROOT}/resource_slots/heavy}" \
    --slots "${PHASE7_HEAVY_SLOTS:-1}" \
    --poll-sec "${PHASE7_HEAVY_SLOT_POLL_SEC:-10}" \
    --label "cross_problem_v21_${LABEL}_${iid}_run" \
    -- \
    "${START_WITH_TOOLS}" --mode with-mem \
      "${SWEAGENT_BIN}" run-batch \
      --config "${MODEL_CONFIG}" \
      --instances.type swe_bench \
      --instances.subset "${SWEBENCH_SUBSET}" \
      --instances.split "${SWEBENCH_SPLIT}" \
      --instances.filter "^${iid}$" \
      --output_dir "${attempt_dir}" \
      --num_workers 1 \
      --env_var_path "${ENV_VAR_PATH}" \
      --agent.model.per_instance_call_limit "${PER_INSTANCE_CALL_LIMIT}" \
      --redo_existing false \
      --agent.tools.total_execution_timeout "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
      2>&1 | tee -a "${run_log}"
  rc=$?
  set -e
  echo "[info] cross v21 ${LABEL} ${iid} rc=${rc}" | tee -a "${run_log}"

  "${RESOURCE_SLOT_SH}" \
    --slot-dir "${PHASE7_HEAVY_SLOT_DIR:-${RUN_ROOT}/resource_slots/heavy}" \
    --slots "${PHASE7_HEAVY_SLOTS:-1}" \
    --poll-sec "${PHASE7_HEAVY_SLOT_POLL_SEC:-10}" \
    --label "cross_problem_v21_${LABEL}_${iid}_eval" \
    -- \
    "${PYTHON_BIN}" "${EVAL_STEP}" \
      --workspace-root "${WS_ROOT}" \
      --python-bin "${PYTHON_BIN}" \
      --instance-id "${iid}" \
      --attempt-dir "${attempt_dir}" \
      --predictions-json "${pred_json}" \
      --report-json "${report_json}" \
      --summary-json "${summary_json}" \
      --feedback-json "${feedback_json}" \
      --apply-feedback \
      --run-id "phase7_cross_v21_${LABEL}_${iid}_attempt_01" \
      --scope "Phase7 cross-problem v2.1 carryover ${LABEL} ${iid}" \
      --dataset "SWE-bench/SWE-bench ${SWEBENCH_SPLIT}" \
      --split "${SWEBENCH_SPLIT}" \
      --eval-timeout-sec "${EVAL_TIMEOUT_SEC}" \
      --max-workers-eval "${MAX_WORKERS_EVAL}"
done
