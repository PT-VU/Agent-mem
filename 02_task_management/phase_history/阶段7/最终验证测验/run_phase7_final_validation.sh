#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_PYTHON="${SWE_AGENT_PYTHON:-${WS_ROOT}/SWE-agent/.venv/bin/python}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUNS_ROOT="${RUNS_ROOT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase7}"
RUN_TAG="${RUN_TAG:-phase7_final_validation_$(date +%Y%m%d_%H%M%S)}"
RUN_ROOT="${RUNS_ROOT}/${RUN_TAG}"
STATE_DIR="${RUN_ROOT}/orchestrator_state"
LOG_DIR="${RUN_ROOT}/orchestrator_logs"
mkdir -p "${STATE_DIR}" "${LOG_DIR}"
LOCK_FILE="${RUN_ROOT}/orchestrator.lock"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "another orchestrator is already running for RUN_TAG=${RUN_TAG}" >&2
  exit 3
fi

SAME_INSTANCE_ID="${SAME_INSTANCE_ID:-}"
SAME_INSTANCE_COUNT="${SAME_INSTANCE_COUNT:-15}"
SAME_INSTANCE_SEED="${SAME_INSTANCE_SEED:-42}"
SAME_REPEATS="${SAME_REPEATS:-10}"
CROSS_REPO_A="${CROSS_REPO_A:-django}"
CROSS_REPO_B="${CROSS_REPO_B:-sympy}"
CROSS_COUNT="${CROSS_COUNT:-25}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_siliconflow.yaml}"
PROMPT_PROFILE="${PROMPT_PROFILE:-prompt_base}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
DRY_RUN="${DRY_RUN:-0}"
SELF_TEST="${SELF_TEST:-0}"
PIPELINE_START_STAGGER_SEC="${PIPELINE_START_STAGGER_SEC:-3}"
PHASE7_SAME_HEAVY_SLOTS="${PHASE7_SAME_HEAVY_SLOTS:-1}"
PHASE7_CROSS_HEAVY_SLOTS="${PHASE7_CROSS_HEAVY_SLOTS:-1}"
PHASE7_HEAVY_SLOT_POLL_SEC="${PHASE7_HEAVY_SLOT_POLL_SEC:-10}"

SELECTOR="${SCRIPT_DIR}/select_lite_instances_by_repo.py"
SAME_SELECTOR="${SCRIPT_DIR}/select_lite_instances_random.py"
SAME_NOMEM="${SCRIPT_DIR}/run_same_problem_nomem_phase7.sh"
SAME_V21="${SCRIPT_DIR}/run_same_problem_v21_phase7.sh"
CROSS_NOMEM="${SCRIPT_DIR}/run_cross_problem_nomem_fresh_phase7.sh"
CROSS_V21="${SCRIPT_DIR}/run_cross_problem_v21_carryover_phase7.sh"

select_repo_list() {
  local repo="$1"
  local out="$2"
  if [[ -f "${out}" ]]; then
    return 0
  fi
  "${SWE_AGENT_PYTHON}" "${SELECTOR}" --workspace-root "${WS_ROOT}" --repo "${repo}" --split "${SWEBENCH_SPLIT}" --count "${CROSS_COUNT}" --out "${out}"
}

select_same_list() {
  local out="$1"
  if [[ -f "${out}" ]]; then
    return 0
  fi
  if [[ -n "${SAME_INSTANCE_ID}" ]]; then
    "${SWE_AGENT_PYTHON}" - <<'PY' "${out}" "${SAME_INSTANCE_ID}" "${SWEBENCH_SPLIT}"
import json, pathlib, sys
from datetime import datetime, timezone

out_path = pathlib.Path(sys.argv[1])
instance_id = sys.argv[2]
split = sys.argv[3]
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "subset": "lite",
    "split": split,
    "selection_mode": "manual_singleton",
    "count_requested": 1,
    "count_selected": 1,
    "instance_ids": [instance_id],
}
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(str(out_path))
PY
    return 0
  fi
  "${SWE_AGENT_PYTHON}" "${SAME_SELECTOR}" --workspace-root "${WS_ROOT}" --split "${SWEBENCH_SPLIT}" --count "${SAME_INSTANCE_COUNT}" --seed "${SAME_INSTANCE_SEED}" --out "${out}"
}

run_pipeline_same() {
  if [[ -f "${STATE_DIR}/same_problem.done.ok" ]]; then
    echo "[resume] same_problem already done"
    return 0
  fi
  if [[ "${SELF_TEST}" == "1" ]]; then
    echo "[self-test] same_problem start"
    sleep 2
    echo "[self-test] same_problem end"
    touch "${STATE_DIR}/same_problem.done.ok"
    return 0
  fi
  RUN_ROOT="${RUN_ROOT}" INSTANCE_LIST_JSON="${SAME_JSON}" REPEATS="${SAME_REPEATS}" MODEL_CONFIG="${MODEL_CONFIG}" PROMPT_PROFILE="${PROMPT_PROFILE}" DRY_RUN="${DRY_RUN}" \
    PHASE7_HEAVY_SLOT_DIR="${PHASE7_SAME_HEAVY_SLOT_DIR}" PHASE7_HEAVY_SLOTS="${PHASE7_SAME_HEAVY_SLOTS}" PHASE7_HEAVY_SLOT_POLL_SEC="${PHASE7_HEAVY_SLOT_POLL_SEC}" \
    "${SAME_NOMEM}" | tee "${LOG_DIR}/same_problem_nomem.log"
  RUN_ROOT="${RUN_ROOT}" INSTANCE_LIST_JSON="${SAME_JSON}" REPEATS="${SAME_REPEATS}" MODEL_CONFIG="${MODEL_CONFIG}" PROMPT_PROFILE="${PROMPT_PROFILE}" DRY_RUN="${DRY_RUN}" \
    PHASE7_HEAVY_SLOT_DIR="${PHASE7_SAME_HEAVY_SLOT_DIR}" PHASE7_HEAVY_SLOTS="${PHASE7_SAME_HEAVY_SLOTS}" PHASE7_HEAVY_SLOT_POLL_SEC="${PHASE7_HEAVY_SLOT_POLL_SEC}" \
    "${SAME_V21}" | tee "${LOG_DIR}/same_problem_v21.log"
  touch "${STATE_DIR}/same_problem.done.ok"
}

run_pipeline_cross() {
  if [[ -f "${STATE_DIR}/cross_problem.done.ok" ]]; then
    echo "[resume] cross_problem already done"
    return 0
  fi
  if [[ "${SELF_TEST}" == "1" ]]; then
    echo "[self-test] cross_problem start"
    sleep 3
    echo "[self-test] cross_problem end"
    touch "${STATE_DIR}/cross_problem.done.ok"
    return 0
  fi

  RUN_ROOT="${RUN_ROOT}" INSTANCE_LIST_JSON="${REPO_A_JSON}" LABEL="${CROSS_REPO_A}" MODEL_CONFIG="${MODEL_CONFIG}" PROMPT_PROFILE="${PROMPT_PROFILE}" DRY_RUN="${DRY_RUN}" \
    PHASE7_HEAVY_SLOT_DIR="${PHASE7_CROSS_HEAVY_SLOT_DIR}" PHASE7_HEAVY_SLOTS="${PHASE7_CROSS_HEAVY_SLOTS}" PHASE7_HEAVY_SLOT_POLL_SEC="${PHASE7_HEAVY_SLOT_POLL_SEC}" \
    "${CROSS_NOMEM}" | tee "${LOG_DIR}/cross_${CROSS_REPO_A}_nomem.log"
  RUN_ROOT="${RUN_ROOT}" INSTANCE_LIST_JSON="${REPO_A_JSON}" LABEL="${CROSS_REPO_A}" MODEL_CONFIG="${MODEL_CONFIG}" PROMPT_PROFILE="${PROMPT_PROFILE}" DRY_RUN="${DRY_RUN}" \
    PHASE7_HEAVY_SLOT_DIR="${PHASE7_CROSS_HEAVY_SLOT_DIR}" PHASE7_HEAVY_SLOTS="${PHASE7_CROSS_HEAVY_SLOTS}" PHASE7_HEAVY_SLOT_POLL_SEC="${PHASE7_HEAVY_SLOT_POLL_SEC}" \
    "${CROSS_V21}" | tee "${LOG_DIR}/cross_${CROSS_REPO_A}_v21.log"

  RUN_ROOT="${RUN_ROOT}" INSTANCE_LIST_JSON="${REPO_B_JSON}" LABEL="${CROSS_REPO_B}" MODEL_CONFIG="${MODEL_CONFIG}" PROMPT_PROFILE="${PROMPT_PROFILE}" DRY_RUN="${DRY_RUN}" \
    PHASE7_HEAVY_SLOT_DIR="${PHASE7_CROSS_HEAVY_SLOT_DIR}" PHASE7_HEAVY_SLOTS="${PHASE7_CROSS_HEAVY_SLOTS}" PHASE7_HEAVY_SLOT_POLL_SEC="${PHASE7_HEAVY_SLOT_POLL_SEC}" \
    "${CROSS_NOMEM}" | tee "${LOG_DIR}/cross_${CROSS_REPO_B}_nomem.log"
  RUN_ROOT="${RUN_ROOT}" INSTANCE_LIST_JSON="${REPO_B_JSON}" LABEL="${CROSS_REPO_B}" MODEL_CONFIG="${MODEL_CONFIG}" PROMPT_PROFILE="${PROMPT_PROFILE}" DRY_RUN="${DRY_RUN}" \
    PHASE7_HEAVY_SLOT_DIR="${PHASE7_CROSS_HEAVY_SLOT_DIR}" PHASE7_HEAVY_SLOTS="${PHASE7_CROSS_HEAVY_SLOTS}" PHASE7_HEAVY_SLOT_POLL_SEC="${PHASE7_HEAVY_SLOT_POLL_SEC}" \
    "${CROSS_V21}" | tee "${LOG_DIR}/cross_${CROSS_REPO_B}_v21.log"

  touch "${STATE_DIR}/cross_problem.done.ok"
}

echo "run_root=${RUN_ROOT}"
echo "same_instance=${SAME_INSTANCE_ID:-random_selection}"
echo "same_instance_count=${SAME_INSTANCE_COUNT}"
echo "same_instance_seed=${SAME_INSTANCE_SEED}"
echo "cross_repo_a=${CROSS_REPO_A}"
echo "cross_repo_b=${CROSS_REPO_B}"
echo "same_heavy_slots=${PHASE7_SAME_HEAVY_SLOTS}"
echo "cross_heavy_slots=${PHASE7_CROSS_HEAVY_SLOTS}"

export PHASE7_SAME_HEAVY_SLOT_DIR="${RUN_ROOT}/resource_slots/same"
export PHASE7_CROSS_HEAVY_SLOT_DIR="${RUN_ROOT}/resource_slots/cross"
export PHASE7_HEAVY_SLOT_POLL_SEC

cat > "${STATE_DIR}/run_config.json" <<EOF
{
  "run_tag": "${RUN_TAG}",
  "same_instance_id": "${SAME_INSTANCE_ID}",
  "same_instance_count": ${SAME_INSTANCE_COUNT},
  "same_instance_seed": ${SAME_INSTANCE_SEED},
  "same_repeats": ${SAME_REPEATS},
  "cross_repo_a": "${CROSS_REPO_A}",
  "cross_repo_b": "${CROSS_REPO_B}",
  "cross_count": ${CROSS_COUNT},
  "prompt_profile": "${PROMPT_PROFILE}"
}
EOF

SAME_JSON="${STATE_DIR}/same_instances.json"
REPO_A_JSON="${STATE_DIR}/repo_a_instances.json"
REPO_B_JSON="${STATE_DIR}/repo_b_instances.json"
select_same_list "${SAME_JSON}"
select_repo_list "${CROSS_REPO_A}" "${REPO_A_JSON}"
select_repo_list "${CROSS_REPO_B}" "${REPO_B_JSON}"

run_pipeline_same &
PID_SAME=$!
sleep "${PIPELINE_START_STAGGER_SEC}"
run_pipeline_cross &
PID_CROSS=$!

wait "${PID_SAME}"
RC_SAME=$?
wait "${PID_CROSS}"
RC_CROSS=$?

echo "${RC_SAME}" > "${STATE_DIR}/same_problem.exit"
echo "${RC_CROSS}" > "${STATE_DIR}/cross_problem.exit"

if [[ "${RC_SAME}" -ne 0 || "${RC_CROSS}" -ne 0 ]]; then
  echo "same_problem_rc=${RC_SAME} cross_problem_rc=${RC_CROSS}" >&2
  exit 1
fi

echo "phase7 final validation orchestration completed"
