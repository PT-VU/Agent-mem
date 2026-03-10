#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
SWEAGENT_BIN="${SWEAGENT_BIN:-${SWE_AGENT_ROOT}/.venv/bin/sweagent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
START_WITH_TOOLS="${START_WITH_TOOLS:-${WS_ROOT}/PDDL_work_mem/source_code/sweagent_external_tools/bin/start_with_external_tools.sh}"
COMMON_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common"
BEHAVIOR_ANALYZER="${COMMON_DIR}/analyze_memory_behavior.py"
EVAL_FEEDBACK_APPLIER="${COMMON_DIR}/apply_official_eval_feedback.py"
LOCAL_EVAL_STUB_WRITER="${COMMON_DIR}/write_local_eval_stub.py"
RUNTIME_GUARD_SH="${COMMON_DIR}/docker_runtime_guard.sh"

RUN_TAG="${RUN_TAG:-stage6_smoke_full_first5_withmem_$(date +%Y%m%d_%H%M%S)}"
BASE_EXP_DIR="${BASE_EXP_DIR:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/smoke_runs}"
EXP_DIR="${EXP_DIR:-${BASE_EXP_DIR}/${RUN_TAG}}"
OUTDIR="${OUTDIR:-${EXP_DIR}/outputs/run_outputs_full_first5_with_mem}"
CACHE_FILE="${CACHE_FILE:-${EXP_DIR}/cache/full_test_instances_cache_first5.json}"
CACHE_META_FILE="${CACHE_META_FILE:-${EXP_DIR}/cache/full_test_instances_cache_first5_with_images.json}"
METRICS_DIR="${METRICS_DIR:-${EXP_DIR}/metrics}"
NOTES_DIR="${NOTES_DIR:-${EXP_DIR}/notes}"
MANIFEST_OUT="${MANIFEST_OUT:-${METRICS_DIR}/manifest_stage6_smoke_full_first5_withmem.json}"
METRICS_OUT="${METRICS_OUT:-${METRICS_DIR}/metrics_stage6_smoke_full_first5_withmem.json}"
PREDS_JSON="${PREDS_JSON:-${OUTDIR}/preds_stage6_smoke_full_first5.json}"
RUN_ID="${RUN_ID:-stage6_smoke_full_first5_withmem_eval_$(date +%Y%m%d_%H%M%S)}"
OFFICIAL_SUMMARY_JSON="${OFFICIAL_SUMMARY_JSON:-${METRICS_DIR}/official_eval_summary_stage6_smoke_full_first5_withmem.json}"
OFFICIAL_REPORT_JSON="${OFFICIAL_REPORT_JSON:-${METRICS_DIR}/official_eval_report_stage6_smoke_full_first5_withmem.json}"
OFFICIAL_FEEDBACK_JSON="${OFFICIAL_FEEDBACK_JSON:-${METRICS_DIR}/official_eval_feedback_stage6_smoke_full_first5_withmem.json}"
BEHAVIOR_JSON="${BEHAVIOR_JSON:-${METRICS_DIR}/memory_behavior_stage6_smoke_full_first5.json}"
BEHAVIOR_MD="${BEHAVIOR_MD:-${NOTES_DIR}/memory_behavior_stage6_smoke_full_first5.md}"

mkdir -p "${EXP_DIR}" "${METRICS_DIR}" "${NOTES_DIR}" "${EXP_DIR}/logs" "${EXP_DIR}/cache" \
  "${EXP_DIR}/metrics/instance_reports" "${EXP_DIR}/metrics/instance_summaries" "${EXP_DIR}/metrics/instance_feedback"
source "${RUNTIME_GUARD_SH}"

START_INDEX="${START_INDEX:-0}"
STOP_INDEX="${STOP_INDEX:-5}"
NUM_WORKERS="${NUM_WORKERS:-1}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
REDO_EXISTING="${REDO_EXISTING:-0}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/deepseek.yaml}"
ENV_VAR_PATH="${ENV_VAR_PATH:-${SWE_AGENT_ROOT}/.env}"
MAX_WORKERS_EVAL="${MAX_WORKERS_EVAL:-1}"
PYTHON_STANDALONE_DIR="${PYTHON_STANDALONE_DIR:-/root}"
DEPLOYMENT_STARTUP_TIMEOUT_SEC="${DEPLOYMENT_STARTUP_TIMEOUT_SEC:-600}"
STARTUP_RETRIES="${STARTUP_RETRIES:-1}"

export EXPERIMENT_ID="${EXPERIMENT_ID:-阶段6_smoke_full_first5_withmem_closed_loop}"
export RUN_SCRIPT_PATH="PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/scripts/run_full_first5_with_mem_smoke_stage6.sh"
export SUBSET_LABEL="${SUBSET_LABEL:-SWE-bench Full first5 with_mem smoke (stage6 closed loop, 20min cap)}"
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
export AGENT_MEM_STORAGE_DIR="${AGENT_MEM_STORAGE_DIR:-${EXP_DIR}/persistence/graph_store}"
export AGENT_MEM_EVIDENCE_DIR="${AGENT_MEM_EVIDENCE_DIR:-${EXP_DIR}/persistence/evidence_store}"

build_instance_cache() {
  "${PYTHON_BIN}" - <<'PY' "${CACHE_FILE}" "${CACHE_META_FILE}" "${STOP_INDEX}"
import json
import pathlib
import sys
from sweagent.run.batch_instances import SWEBenchInstances

cache_ids = pathlib.Path(sys.argv[1])
cache_meta = pathlib.Path(sys.argv[2])
stop = int(sys.argv[3])
instances = SWEBenchInstances(subset="full", split="test", slice=f":{stop}").get_instance_configs()
ids = []
meta = []
for inst in instances:
    ids.append(inst.problem_statement.id)
    meta.append({"id": inst.problem_statement.id, "image": inst.env.deployment.image})
cache_ids.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")
cache_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print(str(cache_ids))
PY
}

maybe_prefetch_image() {
  local image="$1"
  local log_file="$2"
  if [[ -z "${image}" ]]; then
    return 0
  fi
  if docker image inspect "${image}" >/dev/null 2>&1; then
    echo "[prefetch] exists: ${image}" | tee -a "${log_file}"
    return 0
  fi
  echo "[prefetch] pull: ${image}" | tee -a "${log_file}"
  docker pull "${image}" >>"${log_file}" 2>&1
}

aggregate_instance_reports() {
  "${PYTHON_BIN}" - <<'PY' "${CACHE_FILE}" "${METRICS_DIR}/instance_reports" "${OFFICIAL_REPORT_JSON}"
import json
import pathlib
import sys

cache_path = pathlib.Path(sys.argv[1])
reports_dir = pathlib.Path(sys.argv[2])
out_path = pathlib.Path(sys.argv[3])
instance_ids = json.loads(cache_path.read_text(encoding="utf-8"))
resolved_ids = []
unresolved_ids = []
incomplete_ids = []
error_ids = []
submitted_ids = []
completed_ids = []
empty_patch_ids = []
for iid in instance_ids:
    path = reports_dir / f"{iid}.official_eval.json"
    if not path.exists():
        incomplete_ids.append(iid)
        continue
    report = json.loads(path.read_text(encoding="utf-8"))
    if iid in report.get("submitted_ids", []):
        submitted_ids.append(iid)
    if iid in report.get("completed_ids", []):
        completed_ids.append(iid)
    if iid in report.get("resolved_ids", []):
        resolved_ids.append(iid)
    if iid in report.get("unresolved_ids", []):
        unresolved_ids.append(iid)
    if iid in report.get("error_ids", []):
        error_ids.append(iid)
    if iid in report.get("empty_patch_ids", []):
        empty_patch_ids.append(iid)
    if iid in report.get("incomplete_ids", []):
        incomplete_ids.append(iid)

payload = {
    "schema_version": 2,
    "total_instances": len(instance_ids),
    "submitted_instances": len(submitted_ids),
    "submitted_ids": submitted_ids,
    "completed_instances": len(completed_ids),
    "completed_ids": completed_ids,
    "resolved_instances": len(resolved_ids),
    "resolved_ids": resolved_ids,
    "unresolved_instances": len(unresolved_ids),
    "unresolved_ids": unresolved_ids,
    "error_instances": len(error_ids),
    "error_ids": error_ids,
    "empty_patch_instances": len(empty_patch_ids),
    "empty_patch_ids": empty_patch_ids,
    "incomplete_ids": incomplete_ids,
}
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(str(out_path))
PY
}

aggregate_instance_feedback() {
  "${PYTHON_BIN}" - <<'PY' "${METRICS_DIR}/instance_feedback" "${OFFICIAL_FEEDBACK_JSON}"
import json
import pathlib
import sys

feedback_dir = pathlib.Path(sys.argv[1])
out_path = pathlib.Path(sys.argv[2])
records = []
outcome_counts = {}
for path in sorted(feedback_dir.glob("*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        continue
    records.append(
        {
            "path": str(path),
            "processed_instances": data.get("processed_instances", 0),
            "outcome_counts": data.get("outcome_counts", {}),
        }
    )
    for key, value in (data.get("outcome_counts") or {}).items():
        outcome_counts[key] = int(outcome_counts.get(key, 0)) + int(value)

payload = {
    "schema_version": "v1",
    "feedback_files": records,
    "outcome_counts": outcome_counts,
    "processed_feedback_files": len(records),
}
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(str(out_path))
PY
}

build_instance_cache

echo "[1/5] run per-instance closed loop"
"${PYTHON_BIN}" - <<'PY' "${CACHE_META_FILE}" "${START_INDEX}" "${STOP_INDEX}"
import json
import pathlib
import sys
rows = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
start = int(sys.argv[2]); stop = int(sys.argv[3])
for idx, row in enumerate(rows[start:stop], start=start):
    print(f"{idx}\t{row['id']}\t{row['image']}")
PY
while IFS=$'\t' read -r idx instance_id image; do
  [[ -z "${instance_id}" ]] && continue
  instance_dir="${OUTDIR}/${instance_id}"
  instance_summary_json="${METRICS_DIR}/instance_summaries/${instance_id}.official_eval_summary.json"
  instance_feedback_json="${METRICS_DIR}/instance_feedback/${instance_id}.official_eval_feedback.json"
  run_log="${EXP_DIR}/logs/run_${idx}_${instance_id}.log"
  prefetch_log="${EXP_DIR}/logs/prefetch_${idx}_${instance_id}.log"
  eval_run_id="${RUN_ID}_${idx}_${instance_id}"
  raw_report_link="${METRICS_DIR}/instance_reports/${instance_id}.official_eval.json"

  if [[ "${REDO_EXISTING}" != "1" && -f "${instance_summary_json}" && -f "${instance_feedback_json}" ]]; then
    echo "[loop] skip completed instance ${instance_id}"
    continue
  fi

  maybe_prefetch_image "${image}" "${prefetch_log}"

  if [[ "${REDO_EXISTING}" == "1" || ! -f "${instance_dir}/${instance_id}.traj" ]]; then
    export SWE_AGENT_EXT_TOOLS_LOG_FILE="${EXP_DIR}/logs/with_mem_tool_events_${idx}_${instance_id}.jsonl"
    export SWE_AGENT_EXT_INSTANCE_ID="${instance_id}"
    export SWE_AGENT_EXT_RUN_ID="${RUN_TAG}"
    export SWE_AGENT_EXT_ATTEMPT_ID="attempt-${idx}"
    echo "[run] ${instance_id}" | tee "${run_log}"
    runtime_guard_preflight "${run_log}"
    image_pattern="docker.io/swebench/sweb.eval.x86_64.${instance_id/:/-}:latest"
    runtime_guard_cleanup_pattern "${run_log}" "${image_pattern}"
    run_status=1
    startup_retry_index=0
    while (( startup_retry_index <= STARTUP_RETRIES )); do
      [[ "${startup_retry_index}" -gt 0 ]] && echo "[retry] startup retry ${startup_retry_index}/${STARTUP_RETRIES} for ${instance_id}" | tee -a "${run_log}"
      set +e
      run_cmd=(
        "${START_WITH_TOOLS}" --mode with-mem
        "${SWEAGENT_BIN}" run-batch
        --config "${MODEL_CONFIG}"
        --instances.type swe_bench
        --instances.subset full
        --instances.split test
        --instances.deployment.type docker
        --instances.deployment.startup_timeout "${DEPLOYMENT_STARTUP_TIMEOUT_SEC}"
        --instances.slice "${idx}:$((idx + 1))"
        --output_dir "${OUTDIR}"
        --num_workers "${NUM_WORKERS}"
        --env_var_path "${ENV_VAR_PATH}"
        --agent.model.per_instance_call_limit "${PER_INSTANCE_CALL_LIMIT}"
        --agent.tools.total_execution_timeout "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}"
        --redo_existing "$( [[ "${REDO_EXISTING}" == "1" ]] && echo True || echo False )"
      )
      if [[ -n "${PYTHON_STANDALONE_DIR}" && "${PYTHON_STANDALONE_DIR}" != "__NONE__" ]]; then
        run_cmd+=(--instances.deployment.python_standalone_dir "${PYTHON_STANDALONE_DIR}")
      fi
      timeout --foreground -k 45s "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}s" "${run_cmd[@]}" 2>&1 | tee -a "${run_log}"
      run_status=$?
      set -e
      if [[ "${run_status}" -eq 0 ]]; then
        break
      fi
      if grep -q "Runtime did not start within timeout" "${run_log}"; then
        runtime_guard_capture_diag "${run_log}" "${image_pattern}"
        runtime_guard_cleanup_pattern "${run_log}" "${image_pattern}"
        (( startup_retry_index++ ))
        continue
      fi
      runtime_guard_capture_diag "${run_log}" "${image_pattern}"
      break
    done
    if [[ "${run_status}" -eq 124 || "${run_status}" -eq 137 ]]; then
      echo "[run] hard timeout triggered for ${instance_id} after ${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}s" | tee -a "${run_log}"
    elif [[ "${run_status}" -ne 0 ]]; then
      echo "[run] run-batch exited with status ${run_status} for ${instance_id}" | tee -a "${run_log}"
    fi
  else
    echo "[run] reuse existing outputs for ${instance_id}" | tee -a "${run_log}"
  fi

  tmp_cache="$(mktemp)"
  printf '[\n  "%s"\n]\n' "${instance_id}" > "${tmp_cache}"
  pred_json="${METRICS_DIR}/instance_reports/${instance_id}.predictions.json"
  "${PYTHON_BIN}" "${COMMON_DIR}/rebuild_eval_predictions.py" \
    --output-dir "${OUTDIR}" \
    --cache-file "${tmp_cache}" \
    --default-model-name "run_outputs_full_first5_with_mem_stage6_closed_loop" \
    --out "${pred_json}" >/dev/null

  pred_count="$("${PYTHON_BIN}" - <<'PY' "${pred_json}"
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print(0)
    raise SystemExit(0)
print(len(data) if isinstance(data, dict) else 0)
PY
)"

  if [[ "${pred_count}" -eq 0 ]]; then
    local_reason="missing_prediction"
    if [[ "${run_status:-0}" -eq 124 || "${run_status:-0}" -eq 137 ]]; then
      local_reason="timeout_no_prediction"
    elif [[ "${run_status:-0}" -ne 0 ]]; then
      local_reason="run_failure_no_prediction"
    fi
    echo "[eval] skip official harness for ${instance_id}: ${local_reason}" | tee -a "${run_log}"
    "${PYTHON_BIN}" "${LOCAL_EVAL_STUB_WRITER}" \
      --instance-id "${instance_id}" \
      --outcome incomplete \
      --reason "${local_reason}" \
      --out "${raw_report_link}" >/dev/null
  else
    "${PYTHON_BIN}" -m swebench.harness.run_evaluation \
      --dataset_name SWE-bench/SWE-bench \
      --split test \
      --predictions_path "${pred_json}" \
      --max_workers "${MAX_WORKERS_EVAL}" \
      --timeout "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
      --cache_level env \
      --clean false \
      --run_id "${eval_run_id}" \
      --instance_ids "${instance_id}"

    raw_report_json="$(ls -1t "${WS_ROOT}"/*.${eval_run_id}.json 2>/dev/null | head -n 1 || true)"
    if [[ -z "${raw_report_json}" ]]; then
      echo "Cannot find raw report for ${instance_id}" >&2
      exit 2
    fi
    cp -f "${raw_report_json}" "${raw_report_link}"
  fi
  "${PYTHON_BIN}" "${COMMON_DIR}/summarize_official_eval.py" \
    --report-json "${raw_report_link}" \
    --run-id "${eval_run_id}" \
    --dataset "SWE-bench/SWE-bench test" \
    --scope "Stage6 smoke single-instance ${instance_id}" \
    --summary-out "${instance_summary_json}" >/dev/null

  "${PYTHON_BIN}" "${EVAL_FEEDBACK_APPLIER}" \
    --workspace-root "${WS_ROOT}" \
    --report-json "${raw_report_link}" \
    --output-dir "${OUTDIR}" \
    --cache-file "${tmp_cache}" \
    --run-id "${eval_run_id}" \
    --output-json "${instance_feedback_json}" >/dev/null
  rm -f "${tmp_cache}"
done < <("${PYTHON_BIN}" - <<'PY' "${CACHE_META_FILE}" "${START_INDEX}" "${STOP_INDEX}"
import json
import pathlib
import sys
rows = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
start = int(sys.argv[2]); stop = int(sys.argv[3])
for idx, row in enumerate(rows[start:stop], start=start):
    print(f"{idx}\t{row['id']}\t{row['image']}")
PY
)

echo "[2/5] aggregate official eval reports"
aggregate_instance_reports
aggregate_instance_feedback
"${PYTHON_BIN}" "${COMMON_DIR}/summarize_official_eval.py" \
  --report-json "${OFFICIAL_REPORT_JSON}" \
  --run-id "${RUN_ID}" \
  --dataset "SWE-bench/SWE-bench test" \
  --scope "Stage6 smoke full first5 with_mem closed loop" \
  --summary-out "${OFFICIAL_SUMMARY_JSON}" >/dev/null

echo "[3/5] collect manifest"
EVENT_LOG_GLOB="${EXP_DIR#${WS_ROOT}/}/logs/with_mem_tool_events_*.jsonl"
"${PYTHON_BIN}" "${COMMON_DIR}/collect_run_manifest.py" \
  --workspace-root "${WS_ROOT}" \
  --experiment-id "${EXPERIMENT_ID}" \
  --mode "with-mem" \
  --subset "full" \
  --split "test" \
  --output-dir "${OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --start-index "${START_INDEX}" \
  --stop-index "${STOP_INDEX}" \
  --run-script "${RUN_SCRIPT_PATH}" \
  --model-config "${MODEL_CONFIG}" \
  --event-log-glob "${EVENT_LOG_GLOB}" \
  --require-event-logs \
  --manifest-out "${MANIFEST_OUT}" >/dev/null

echo "[4/5] collect metrics"
"${PYTHON_BIN}" "${COMMON_DIR}/collect_run_metrics.py" \
  --workspace-root "${WS_ROOT}" \
  --experiment-id "${EXPERIMENT_ID}" \
  --subset-label "${SUBSET_LABEL}" \
  --mode "with-mem" \
  --output-dir "${OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --start-index "${START_INDEX}" \
  --stop-index "${STOP_INDEX}" \
  --event-log-glob "${EVENT_LOG_GLOB}" \
  --require-event-logs \
  --manifest-path "${MANIFEST_OUT}" \
  --metrics-out "${METRICS_OUT}" >/dev/null

echo "[5/5] analyze memory behavior"
"${PYTHON_BIN}" "${BEHAVIOR_ANALYZER}" \
  --exp-dir "${EXP_DIR}" \
  --metrics-json "${METRICS_OUT}" \
  --manifest-json "${MANIFEST_OUT}" \
  --official-summary-json "${OFFICIAL_SUMMARY_JSON}" \
  --output-json "${BEHAVIOR_JSON}" \
  --output-md "${BEHAVIOR_MD}" \
  --scope "阶段6 smoke full first5 with_mem closed loop"

echo "done"
echo "exp_dir=${EXP_DIR}"
echo "official_summary=${OFFICIAL_SUMMARY_JSON}"
echo "official_feedback=${OFFICIAL_FEEDBACK_JSON}"
echo "behavior_report=${BEHAVIOR_MD}"
