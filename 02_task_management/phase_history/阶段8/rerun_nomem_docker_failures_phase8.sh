#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
RUN_TAG="${RUN_TAG:-phase8_same_only_001}"
RUN_ROOT="${RUN_ROOT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase8/${RUN_TAG}}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
SWEAGENT_BIN="${SWEAGENT_BIN:-${SWE_AGENT_ROOT}/.venv/bin/sweagent}"
START_WITH_TOOLS="${START_WITH_TOOLS:-${WS_ROOT}/PDDL_work_mem/source_code/sweagent_external_tools/bin/start_with_external_tools.sh}"
RESOURCE_SLOT_SH="${RESOURCE_SLOT_SH:-${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段7/最终验证测验/with_resource_slot.sh}"
EVAL_STEP="${EVAL_STEP:-${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段7/最终验证测验/official_eval_step.py}"
MANIFEST_JSON="${MANIFEST_JSON:-${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/nomem_docker_failures_phase8_same_only_001.json}"

MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_siliconflow.yaml}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-lite}"
ENV_VAR_PATH="${ENV_VAR_PATH:-${SWE_AGENT_ROOT}/.env}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
MAX_WORKERS_EVAL="${MAX_WORKERS_EVAL:-1}"
EVAL_TIMEOUT_SEC="${EVAL_TIMEOUT_SEC:-1800}"
DRY_RUN="${DRY_RUN:-0}"
MAX_TARGETS="${MAX_TARGETS:-0}"
RESUME_MODE="${RESUME_MODE:-1}"
RERUN_BATCH_ID="${RERUN_BATCH_ID:-$(date +%Y%m%d_%H%M%S)}"
PHASE7_GLOBAL_HEAVY_SLOT_DIR="${PHASE7_GLOBAL_HEAVY_SLOT_DIR:-${RUN_ROOT}/resource_slots/same_global}"
PHASE7_GLOBAL_HEAVY_SLOTS="${PHASE7_GLOBAL_HEAVY_SLOTS:-2}"
PHASE7_HEAVY_SLOT_DIR="${PHASE7_HEAVY_SLOT_DIR:-${RUN_ROOT}/resource_slots/same_nomem_rerun}"
PHASE7_HEAVY_SLOTS="${PHASE7_HEAVY_SLOTS:-1}"

EXP_DIR="${RUN_ROOT}/same_problem/nomem"
OUTDIR="${EXP_DIR}/outputs"
LOG_DIR="${EXP_DIR}/logs"
METRICS_DIR="${EXP_DIR}/metrics"
STATE_ROOT="${EXP_DIR}/rerun_docker_failures_58"
BACKUP_ROOT="${STATE_ROOT}/backups/${RERUN_BATCH_ID}"
COMPLETED_DIR="${STATE_ROOT}/completed"
FAILED_DIR="${STATE_ROOT}/failed"
mkdir -p "${OUTDIR}" "${LOG_DIR}" "${METRICS_DIR}/attempt_reports" "${METRICS_DIR}/attempt_summaries" "${METRICS_DIR}/attempt_feedback" "${COMPLETED_DIR}" "${FAILED_DIR}" "${BACKUP_ROOT}"

run_with_resource_limits() {
  local label="$1"
  shift
  local local_slot_dir="${PHASE7_HEAVY_SLOT_DIR:-${RUN_ROOT}/resource_slots/same_nomem_rerun}"
  local local_slots="${PHASE7_HEAVY_SLOTS:-1}"
  local local_poll="${PHASE7_HEAVY_SLOT_POLL_SEC:-10}"
  if [[ -n "${PHASE7_GLOBAL_HEAVY_SLOT_DIR:-}" ]]; then
    local global_slots="${PHASE7_GLOBAL_HEAVY_SLOTS:-1}"
    local global_poll="${PHASE7_GLOBAL_HEAVY_SLOT_POLL_SEC:-${local_poll}}"
    "${RESOURCE_SLOT_SH}" \
      --slot-dir "${PHASE7_GLOBAL_HEAVY_SLOT_DIR}" \
      --slots "${global_slots}" \
      --poll-sec "${global_poll}" \
      --label "global:${label}" \
      -- \
      "${RESOURCE_SLOT_SH}" \
        --slot-dir "${local_slot_dir}" \
        --slots "${local_slots}" \
        --poll-sec "${local_poll}" \
        --label "${label}" \
        -- \
        "$@"
    return $?
  fi
  "${RESOURCE_SLOT_SH}" \
    --slot-dir "${local_slot_dir}" \
    --slots "${local_slots}" \
    --poll-sec "${local_poll}" \
    --label "${label}" \
    -- \
    "$@"
}

target_lines() {
  "${PYTHON_BIN}" - <<'PY' "${MANIFEST_JSON}" "${MAX_TARGETS}"
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
max_targets = int(sys.argv[2])
count = 0
for item in manifest.get("targets", []):
    iid = item["instance_id"]
    for attempt in item.get("attempts", []):
        count += 1
        if max_targets > 0 and count > max_targets:
            raise SystemExit
        print(f"{iid} {int(attempt):02d}")
PY
}

backup_one() {
  local src="$1"
  local dst_dir="$2"
  if [[ -e "${src}" ]]; then
    mkdir -p "${dst_dir}"
    mv "${src}" "${dst_dir}/"
  fi
}

backup_and_clean_attempt() {
  local iid="$1"
  local tag="$2"
  local safe_iid="${iid//\//_}"
  local backup_dir="${BACKUP_ROOT}/${safe_iid}/attempt_${tag}"
  local attempt_outdir="${OUTDIR}/${iid}/attempt_${tag}"
  local run_log="${LOG_DIR}/${safe_iid}/attempt_${tag}.log"
  local event_log="${LOG_DIR}/${safe_iid}/attempt_${tag}.jsonl"
  local pred_json="${METRICS_DIR}/attempt_reports/${iid}.attempt_${tag}.predictions.json"
  local report_json="${METRICS_DIR}/attempt_reports/${iid}.attempt_${tag}.official_eval.json"
  local summary_json="${METRICS_DIR}/attempt_summaries/${iid}.attempt_${tag}.summary.json"
  local feedback_json="${METRICS_DIR}/attempt_feedback/${iid}.attempt_${tag}.feedback.json"
  local context_json="${METRICS_DIR}/attempt_context/${iid}.attempt_${tag}.context.json"

  backup_one "${attempt_outdir}" "${backup_dir}/outputs"
  backup_one "${run_log}" "${backup_dir}/logs"
  backup_one "${event_log}" "${backup_dir}/logs"
  backup_one "${pred_json}" "${backup_dir}/metrics/attempt_reports"
  backup_one "${report_json}" "${backup_dir}/metrics/attempt_reports"
  backup_one "${summary_json}" "${backup_dir}/metrics/attempt_summaries"
  backup_one "${feedback_json}" "${backup_dir}/metrics/attempt_feedback"
  backup_one "${context_json}" "${backup_dir}/metrics/attempt_context"
}

write_marker() {
  local path="$1"
  local iid="$2"
  local tag="$3"
  local run_rc="$4"
  local eval_rc="$5"
  mkdir -p "$(dirname "${path}")"
  cat > "${path}" <<EOF
{
  "instance_id": "${iid}",
  "attempt_tag": "${tag}",
  "run_rc": ${run_rc},
  "eval_rc": ${eval_rc},
  "rerun_batch_id": "${RERUN_BATCH_ID}"
}
EOF
}

refresh_rollup() {
  local same_list="${RUN_ROOT}/same_instances.json"
  if [[ ! -f "${same_list}" ]]; then
    return 0
  fi
  "${PYTHON_BIN}" - <<'PY' "${METRICS_DIR}" "${same_list}" "10" "prompt_base"
import json, pathlib, sys
metrics_dir = pathlib.Path(sys.argv[1])
instance_list_path = pathlib.Path(sys.argv[2])
repeats = int(sys.argv[3])
prompt = sys.argv[4]
instance_ids = json.loads(instance_list_path.read_text(encoding="utf-8")).get("instance_ids", [])
rows = []
for instance_id in instance_ids:
    attempts = []
    for attempt in range(1, repeats + 1):
        tag = f"{attempt:02d}"
        summary_path = metrics_dir / "attempt_summaries" / f"{instance_id}.attempt_{tag}.summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
        attempts.append({
            "attempt": attempt,
            "summary_path": str(summary_path),
            "submitted_instances": summary.get("submitted_instances", 0),
            "resolved_instances": summary.get("resolved_instances", 0),
            "incomplete_instances": summary.get("incomplete_instances", 0),
            "solved_rate_on_planned": summary.get("solved_rate_on_planned", 0.0),
            "prompt_profile": prompt,
            "memory_mode": "no_mem",
        })
    rows.append({"instance_id": instance_id, "attempts": attempts})
out = metrics_dir / "attempt_summaries.json"
out.write_text(json.dumps({"instance_ids": instance_ids, "repeats": repeats, "instances": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
print(out)
PY
}

if [[ ! -f "${MANIFEST_JSON}" ]]; then
  echo "manifest not found: ${MANIFEST_JSON}" >&2
  exit 2
fi

mapfile -t TARGETS < <(target_lines)
if [[ "${#TARGETS[@]}" -eq 0 ]]; then
  echo "no targets selected" >&2
  exit 1
fi

echo "run_root=${RUN_ROOT}"
echo "manifest=${MANIFEST_JSON}"
echo "targets=${#TARGETS[@]}"
echo "rerun_batch_id=${RERUN_BATCH_ID}"
echo "global_slot_dir=${PHASE7_GLOBAL_HEAVY_SLOT_DIR}"
echo "global_slots=${PHASE7_GLOBAL_HEAVY_SLOTS}"
echo "local_slot_dir=${PHASE7_HEAVY_SLOT_DIR}"
echo "local_slots=${PHASE7_HEAVY_SLOTS}"

if [[ "${DRY_RUN}" == "1" ]]; then
  printf '%s\n' "${TARGETS[@]}" | sed -n '1,80p'
  exit 0
fi

for line in "${TARGETS[@]}"; do
  iid="${line%% *}"
  tag="${line##* }"
  safe_iid="${iid//\//_}"
  done_marker="${COMPLETED_DIR}/${iid}.attempt_${tag}.done.json"
  fail_marker="${FAILED_DIR}/${iid}.attempt_${tag}.failed.json"
  attempt_outdir="${OUTDIR}/${iid}/attempt_${tag}"
  run_log="${LOG_DIR}/${safe_iid}/attempt_${tag}.log"
  event_log="${LOG_DIR}/${safe_iid}/attempt_${tag}.jsonl"
  pred_json="${METRICS_DIR}/attempt_reports/${iid}.attempt_${tag}.predictions.json"
  report_json="${METRICS_DIR}/attempt_reports/${iid}.attempt_${tag}.official_eval.json"
  summary_json="${METRICS_DIR}/attempt_summaries/${iid}.attempt_${tag}.summary.json"

  mkdir -p "${LOG_DIR}/${safe_iid}" "${OUTDIR}/${iid}"

  if [[ "${RESUME_MODE}" == "1" && -f "${done_marker}" ]]; then
    echo "[resume] skip ${iid} attempt=${tag} (done marker exists)"
    continue
  fi

  echo "[rerun] instance=${iid} attempt=${tag}"
  backup_and_clean_attempt "${iid}" "${tag}"
  rm -f "${fail_marker}"
  mkdir -p "${attempt_outdir}"
  export SWE_AGENT_EXT_TOOLS_LOG_FILE="${event_log}"

  set +e
  run_with_resource_limits \
    "phase8_nomem_docker_rerun_${iid}_attempt_${tag}" \
    "${START_WITH_TOOLS}" --mode no-mem \
      "${SWEAGENT_BIN}" run-batch \
      --config "${MODEL_CONFIG}" \
      --instances.type swe_bench \
      --instances.subset "${SWEBENCH_SUBSET}" \
      --instances.split "${SWEBENCH_SPLIT}" \
      --instances.filter "^${iid}$" \
      --output_dir "${attempt_outdir}" \
      --num_workers 1 \
      --env_var_path "${ENV_VAR_PATH}" \
      --agent.model.per_instance_call_limit "${PER_INSTANCE_CALL_LIMIT}" \
      --agent.tools.total_execution_timeout "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
      --redo_existing True \
      2>&1 | tee -a "${run_log}"
  run_rc=$?
  set -e

  set +e
  run_with_resource_limits \
    "phase8_nomem_docker_rerun_eval_${iid}_attempt_${tag}" \
    "${PYTHON_BIN}" "${EVAL_STEP}" \
      --workspace-root "${WS_ROOT}" \
      --python-bin "${PYTHON_BIN}" \
      --instance-id "${iid}" \
      --attempt-dir "${attempt_outdir}" \
      --predictions-json "${pred_json}" \
      --report-json "${report_json}" \
      --summary-json "${summary_json}" \
      --run-id "phase8_nomem_docker_rerun_${iid}_attempt_${tag}" \
      --scope "Phase8 same-problem no-mem docker-rerun ${iid} attempt ${tag}" \
      --dataset "SWE-bench/SWE-bench ${SWEBENCH_SPLIT}" \
      --split "${SWEBENCH_SPLIT}"
  eval_rc=$?
  set -e

  if [[ "${run_rc}" -eq 0 && "${eval_rc}" -eq 0 ]]; then
    write_marker "${done_marker}" "${iid}" "${tag}" "${run_rc}" "${eval_rc}"
  else
    write_marker "${fail_marker}" "${iid}" "${tag}" "${run_rc}" "${eval_rc}"
    echo "[warn] rerun failed instance=${iid} attempt=${tag} run_rc=${run_rc} eval_rc=${eval_rc}" >&2
  fi
done

refresh_rollup
echo "done rerun batch=${RERUN_BATCH_ID}"
