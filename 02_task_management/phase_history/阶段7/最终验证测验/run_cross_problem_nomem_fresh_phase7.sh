#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
NO_MEM_SCRIPT="${NO_MEM_SCRIPT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/no_mem/scripts/run_multi_try_no_mem_20min.sh}"
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
RESUME_MODE="${RESUME_MODE:-1}"
REDO_EXISTING="${REDO_EXISTING:-0}"
DRY_RUN="${DRY_RUN:-0}"

EXP_DIR="${RUN_ROOT}/cross_problem/${LABEL}/nomem_fresh"
OUTDIR="${EXP_DIR}/outputs"
LOG_DIR="${EXP_DIR}/logs"
METRICS_DIR="${EXP_DIR}/metrics"
CACHE_DIR="${EXP_DIR}/cache"
mkdir -p "${OUTDIR}" "${LOG_DIR}" "${METRICS_DIR}/attempt_reports" "${METRICS_DIR}/attempt_summaries" "${CACHE_DIR}"
cp -f "${INSTANCE_LIST_JSON}" "${CACHE_DIR}/instance_ids.json"
INSTANCE_IDS_CSV="$("${PYTHON_BIN}" - <<'PY' "${INSTANCE_LIST_JSON}"
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
print(",".join(data.get("instance_ids", [])))
PY
)"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[dry-run] cross-problem nomem ${LABEL}"
  echo "instances_json=${INSTANCE_LIST_JSON}"
  exit 0
fi

INSTANCE_IDS_CSV="${INSTANCE_IDS_CSV}" \
EXP_DIR="${EXP_DIR}" \
OUTDIR="${OUTDIR}" \
LOG_DIR="${LOG_DIR}" \
CACHE_DIR="${CACHE_DIR}" \
METRICS_DIR="${METRICS_DIR}" \
INSTANCE_LIST_FILE="${CACHE_DIR}/instance_ids.json" \
SUMMARY_OUT="${METRICS_DIR}/summary_multi_try_no_mem_raw.json" \
SWEBENCH_SUBSET="${SWEBENCH_SUBSET}" \
SWEBENCH_SPLIT="${SWEBENCH_SPLIT}" \
REPEATS=1 \
MODEL_CONFIG="${MODEL_CONFIG}" \
NUM_WORKERS=1 \
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT}" \
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
ENV_VAR_PATH="${ENV_VAR_PATH}" \
REDO_EXISTING="${REDO_EXISTING}" \
RESUME_MODE="${RESUME_MODE}" \
"${RESOURCE_SLOT_SH}" \
  --slot-dir "${PHASE7_HEAVY_SLOT_DIR:-${RUN_ROOT}/resource_slots/heavy}" \
  --slots "${PHASE7_HEAVY_SLOTS:-1}" \
  --poll-sec "${PHASE7_HEAVY_SLOT_POLL_SEC:-10}" \
  --label "cross_problem_nomem_${LABEL}_run" \
  -- \
  "${NO_MEM_SCRIPT}"

while IFS= read -r iid; do
  attempt_dir="${OUTDIR}/${iid}/attempt_01"
  pred_json="${METRICS_DIR}/attempt_reports/${iid}.attempt_01.predictions.json"
  report_json="${METRICS_DIR}/attempt_reports/${iid}.attempt_01.official_eval.json"
  summary_json="${METRICS_DIR}/attempt_summaries/${iid}.attempt_01.summary.json"
  if [[ "${RESUME_MODE}" == "1" && -f "${summary_json}" ]]; then
    echo "[resume] cross nomem ${LABEL} ${iid} summary exists"
    continue
  fi
  "${RESOURCE_SLOT_SH}" \
    --slot-dir "${PHASE7_HEAVY_SLOT_DIR:-${RUN_ROOT}/resource_slots/heavy}" \
    --slots "${PHASE7_HEAVY_SLOTS:-1}" \
    --poll-sec "${PHASE7_HEAVY_SLOT_POLL_SEC:-10}" \
    --label "cross_problem_nomem_${LABEL}_${iid}_eval" \
    -- \
    "${PYTHON_BIN}" "${EVAL_STEP}" \
      --workspace-root "${WS_ROOT}" \
      --python-bin "${PYTHON_BIN}" \
      --instance-id "${iid}" \
      --attempt-dir "${attempt_dir}" \
      --predictions-json "${pred_json}" \
      --report-json "${report_json}" \
      --summary-json "${summary_json}" \
      --run-id "phase7_cross_nomem_${LABEL}_${iid}_attempt_01" \
      --scope "Phase7 cross-problem no-mem ${LABEL} ${iid}" \
      --dataset "SWE-bench/SWE-bench ${SWEBENCH_SPLIT}" \
      --split "${SWEBENCH_SPLIT}"
done < <(
  "${PYTHON_BIN}" - <<'PY' "${INSTANCE_LIST_JSON}"
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
for iid in json.loads(p.read_text(encoding="utf-8")).get("instance_ids", []):
    print(iid)
PY
)
