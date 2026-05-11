#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# 实验目标：
# 对同一个 SWE-bench instance 连续运行多次 with-mem 尝试，并在 attempt 之间保留记忆。
#
# 运行原理：
# 1) 固定一个 instance（默认 astropy__astropy-11693）；
# 2) 连续执行 REPEATS 次尝试，每次是一次独立的 SWE-agent run-batch；
# 3) 所有 attempt 共享同一份 AgentMem persistence（graph_store / evidence_store）；
# 4) 每个 attempt 结束后立刻执行：
#    - rebuild predictions
#    - official eval（若无 patch 则写本地 incomplete stub）
#    - apply official_eval_feedback
# 5) 全部结束后写出 attempt 级 summary，便于比较 attempt1..attemptN 是否出现学习效果。
# -----------------------------------------------------------------------------

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
SWEAGENT_BIN="${SWEAGENT_BIN:-${SWE_AGENT_ROOT}/.venv/bin/sweagent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
START_WITH_TOOLS="${START_WITH_TOOLS:-${WS_ROOT}/PDDL_work_mem/source_code/sweagent_external_tools/bin/start_with_external_tools.sh}"
COMMON_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common"
EVAL_FEEDBACK_APPLIER="${COMMON_DIR}/apply_official_eval_feedback.py"
LOCAL_EVAL_STUB_WRITER="${COMMON_DIR}/write_local_eval_stub.py"
RUNTIME_GUARD_SH="${COMMON_DIR}/docker_runtime_guard.sh"

RUN_TAG="${RUN_TAG:-repeat5_single_withmem_$(date +%Y%m%d_%H%M%S)}"
BASE_EXP_DIR="${BASE_EXP_DIR:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/with_mem/continuous_attempt_runs}"
EXP_DIR="${EXP_DIR:-${BASE_EXP_DIR}/${RUN_TAG}}"
OUTDIR="${OUTDIR:-${EXP_DIR}/outputs}"
LOG_DIR="${LOG_DIR:-${EXP_DIR}/logs}"
METRICS_DIR="${METRICS_DIR:-${EXP_DIR}/metrics}"
NOTES_DIR="${NOTES_DIR:-${EXP_DIR}/notes}"
PERSIST_DIR="${PERSIST_DIR:-${EXP_DIR}/persistence}"
GRAPH_DIR="${GRAPH_DIR:-${PERSIST_DIR}/graph_store}"
EVIDENCE_DIR="${EVIDENCE_DIR:-${PERSIST_DIR}/evidence_store}"

INSTANCE_ID="${INSTANCE_ID:-astropy__astropy-11693}"
REPEATS="${REPEATS:-5}"
START_ATTEMPT="${START_ATTEMPT:-1}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_siliconflow.yaml}"
ENV_VAR_PATH="${ENV_VAR_PATH:-${SWE_AGENT_ROOT}/.env}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
EVAL_TIMEOUT_SEC="${EVAL_TIMEOUT_SEC:-1800}"
MAX_WORKERS_EVAL="${MAX_WORKERS_EVAL:-1}"
REDO_EXISTING="${REDO_EXISTING:-0}"
PYTHON_STANDALONE_DIR="${PYTHON_STANDALONE_DIR:-/root}"
DEPLOYMENT_STARTUP_TIMEOUT_SEC="${DEPLOYMENT_STARTUP_TIMEOUT_SEC:-600}"
STARTUP_RETRIES="${STARTUP_RETRIES:-1}"
RUNTIME_PREWARM="${RUNTIME_PREWARM:-1}"
MAX_ACTIVE_RUN_BATCHES="${MAX_ACTIVE_RUN_BATCHES:-2}"
SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-full}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"

export AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS="${AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS:-1}"
export AGENT_MEM_ENABLE_LLM_EXTRACTION="${AGENT_MEM_ENABLE_LLM_EXTRACTION:-1}"
export AGENT_MEM_LLM_EXTRACT_MODE="${AGENT_MEM_LLM_EXTRACT_MODE:-hybrid}"
export AGENT_MEM_EXTRACT_MAX_SIGNALS="${AGENT_MEM_EXTRACT_MAX_SIGNALS:-0}"
export AGENT_MEM_EXTRACT_MAX_ABSTRACTS="${AGENT_MEM_EXTRACT_MAX_ABSTRACTS:-0}"
export AGENT_MEM_EXTRACT_MAX_REPAIR_PATTERNS="${AGENT_MEM_EXTRACT_MAX_REPAIR_PATTERNS:-0}"
export AGENT_MEM_MAX_HINTS="${AGENT_MEM_MAX_HINTS:-0}"
export SWE_AGENT_EXT_TOOL_A_TIMEOUT_SEC="${SWE_AGENT_EXT_TOOL_A_TIMEOUT_SEC:-90}"
export SWE_AGENT_EXT_TOOL_B_TIMEOUT_SEC="${SWE_AGENT_EXT_TOOL_B_TIMEOUT_SEC:-120}"
export SWE_AGENT_EXT_TOOL_RETRY_TIMEOUT_SEC="${SWE_AGENT_EXT_TOOL_RETRY_TIMEOUT_SEC:-150}"
export SWE_AGENT_EXT_TOOL_MAX_RETRIES="${SWE_AGENT_EXT_TOOL_MAX_RETRIES:-1}"
export AGENT_MEM_STORAGE_DIR="${GRAPH_DIR}"
export AGENT_MEM_EVIDENCE_DIR="${EVIDENCE_DIR}"

mkdir -p "${EXP_DIR}" "${OUTDIR}" "${LOG_DIR}" "${METRICS_DIR}" "${NOTES_DIR}" "${GRAPH_DIR}" "${EVIDENCE_DIR}" \
  "${METRICS_DIR}/attempt_reports" "${METRICS_DIR}/attempt_summaries" "${METRICS_DIR}/attempt_feedback"

source "${RUNTIME_GUARD_SH}"

attempt_outdir() {
  local tag
  tag="$(printf "%02d" "$1")"
  printf "%s/%s/attempt_%s" "${OUTDIR}" "${INSTANCE_ID}" "${tag}"
}

attempt_log() {
  local tag
  tag="$(printf "%02d" "$1")"
  printf "%s/%s.attempt_%s.log" "${LOG_DIR}" "${INSTANCE_ID}" "${tag}"
}

attempt_event_log() {
  local tag
  tag="$(printf "%02d" "$1")"
  printf "%s/%s.attempt_%s.jsonl" "${LOG_DIR}" "${INSTANCE_ID}" "${tag}"
}

attempt_pred_json() {
  local tag
  tag="$(printf "%02d" "$1")"
  printf "%s/attempt_reports/%s.attempt_%s.predictions.json" "${METRICS_DIR}" "${INSTANCE_ID}" "${tag}"
}

attempt_raw_report() {
  local tag
  tag="$(printf "%02d" "$1")"
  printf "%s/attempt_reports/%s.attempt_%s.official_eval.json" "${METRICS_DIR}" "${INSTANCE_ID}" "${tag}"
}

attempt_summary_json() {
  local tag
  tag="$(printf "%02d" "$1")"
  printf "%s/attempt_summaries/%s.attempt_%s.summary.json" "${METRICS_DIR}" "${INSTANCE_ID}" "${tag}"
}

attempt_feedback_json() {
  local tag
  tag="$(printf "%02d" "$1")"
  printf "%s/attempt_feedback/%s.attempt_%s.feedback.json" "${METRICS_DIR}" "${INSTANCE_ID}" "${tag}"
}

validate_previous_attempt_state() {
  local prev_attempt prev_tag summary_json feedback_json
  prev_attempt="$1"
  prev_tag="$(printf "%02d" "${prev_attempt}")"
  summary_json="$(attempt_summary_json "${prev_attempt}")"
  feedback_json="$(attempt_feedback_json "${prev_attempt}")"

  test -f "${summary_json}" || {
    echo "[resume-check] missing summary for attempt ${prev_tag}: ${summary_json}" >&2
    return 1
  }
  test -f "${feedback_json}" || {
    echo "[resume-check] missing feedback for attempt ${prev_tag}: ${feedback_json}" >&2
    return 1
  }
  test -f "${GRAPH_DIR}/attempt_summaries_v1.json" || {
    echo "[resume-check] missing graph attempt summaries store" >&2
    return 1
  }
  test -f "${GRAPH_DIR}/experience_rw_map.jsonl" || {
    echo "[resume-check] missing experience rw map" >&2
    return 1
  }

  "${PYTHON_BIN}" - <<'PY' "${GRAPH_DIR}/attempt_summaries_v1.json" "${GRAPH_DIR}/experience_rw_map.jsonl" "${INSTANCE_ID}" "attempt-${prev_tag}"
import json, pathlib, sys
summary_store = pathlib.Path(sys.argv[1])
rw_map = pathlib.Path(sys.argv[2])
instance_id = sys.argv[3]
attempt_id = sys.argv[4]

store = json.loads(summary_store.read_text(encoding="utf-8"))
summary_hit = None
if isinstance(store, dict):
    for value in store.values():
        if isinstance(value, dict) and value.get("instance_id") == instance_id and value.get("attempt_id") == attempt_id:
            summary_hit = value
            break
elif isinstance(store, list):
    for value in store:
        if isinstance(value, dict) and value.get("instance_id") == instance_id and value.get("attempt_id") == attempt_id:
            summary_hit = value
            break
if summary_hit is None:
    print(f"[resume-check] attempt summary not found for {instance_id} {attempt_id}", file=sys.stderr)
    raise SystemExit(2)

has_run_done_write = False
has_eval_feedback = False
for line in rw_map.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    item = json.loads(line)
    if item.get("instance_id") != instance_id:
        continue
    if item.get("attempt_id") == attempt_id and item.get("write_ids"):
        has_run_done_write = True
    read_ids = item.get("read_ids") or []
    write_ids = item.get("write_ids") or []
    if any(str(x).startswith("sum_") for x in read_ids + write_ids):
        has_eval_feedback = True

if not has_run_done_write:
    print(f"[resume-check] no persisted write_ids found for {instance_id} {attempt_id}", file=sys.stderr)
    raise SystemExit(3)
if not has_eval_feedback:
    print(f"[resume-check] no summary-linked feedback/write evidence found for {instance_id}", file=sys.stderr)
    raise SystemExit(4)
print(f"[resume-check] verified persisted memory for {instance_id} {attempt_id}")
PY
}

if ! [[ "${START_ATTEMPT}" =~ ^[0-9]+$ ]] || (( START_ATTEMPT < 1 || START_ATTEMPT > REPEATS )); then
  echo "invalid START_ATTEMPT=${START_ATTEMPT} for REPEATS=${REPEATS}" >&2
  exit 2
fi

if (( START_ATTEMPT > 1 )); then
  validate_previous_attempt_state "$((START_ATTEMPT - 1))"
fi

INSTANCE_IMAGE=""
IMAGE_MATCH_PATTERN="${INSTANCE_ID}"

for attempt in $(seq "${START_ATTEMPT}" "${REPEATS}"); do
  attempt_tag="$(printf "%02d" "${attempt}")"
  attempt_dir="$(attempt_outdir "${attempt}")"
  run_log="$(attempt_log "${attempt}")"
  event_log="$(attempt_event_log "${attempt}")"
  pred_json="$(attempt_pred_json "${attempt}")"
  raw_report_json="$(attempt_raw_report "${attempt}")"
  summary_json="$(attempt_summary_json "${attempt}")"
  feedback_json="$(attempt_feedback_json "${attempt}")"
  eval_run_id="${RUN_TAG}_${INSTANCE_ID}_attempt_${attempt_tag}"
  tmp_cache="$(mktemp)"
  printf '[\n  "%s"\n]\n' "${INSTANCE_ID}" > "${tmp_cache}"

  mkdir -p "${attempt_dir}"
  if [[ "${REDO_EXISTING}" != "1" && -f "${summary_json}" && -f "${feedback_json}" ]]; then
    echo "[skip] attempt ${attempt_tag} already summarized"
    rm -f "${tmp_cache}"
    continue
  fi

  export SWE_AGENT_EXT_TOOLS_LOG_FILE="${event_log}"
  export SWE_AGENT_EXT_INSTANCE_ID="${INSTANCE_ID}"
  export SWE_AGENT_EXT_RUN_ID="${RUN_TAG}"
  export SWE_AGENT_EXT_ATTEMPT_ID="attempt-${attempt_tag}"

  echo "[run] instance=${INSTANCE_ID} attempt=${attempt_tag}" | tee "${run_log}"
  runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:preflight"
  runtime_guard_preflight "${run_log}"
  if [[ -z "${INSTANCE_IMAGE}" ]]; then
    runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:resolve_image"
    if INSTANCE_IMAGE="$(runtime_guard_resolve_swebench_image "${run_log}" "${INSTANCE_ID}" "${SWEBENCH_SUBSET}" "${SWEBENCH_SPLIT}")"; then
      IMAGE_MATCH_PATTERN="${INSTANCE_IMAGE}"
    else
      echo "[warn] failed to resolve deployment image for ${INSTANCE_ID}; skip runtime prewarm" | tee -a "${run_log}"
      INSTANCE_IMAGE=""
      IMAGE_MATCH_PATTERN="${INSTANCE_ID}"
    fi
  fi
  if [[ "${RUNTIME_PREWARM}" == "1" && -n "${INSTANCE_IMAGE}" ]]; then
    runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:runtime_warmup"
    if ! runtime_guard_prepare_runtime_image "${run_log}" "${INSTANCE_IMAGE}" "${PYTHON_STANDALONE_DIR}" "linux/amd64"; then
      runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:runtime_warmup_failed"
      echo "[warn] runtime warmup failed for ${INSTANCE_ID}; continue with direct launch" | tee -a "${run_log}"
      runtime_guard_capture_diag "${run_log}" "${IMAGE_MATCH_PATTERN}"
    fi
  fi
  runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:capacity_wait"
  runtime_guard_wait_for_capacity "${run_log}" "${MAX_ACTIVE_RUN_BATCHES}" 10
  runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:cleanup_before_run"
  runtime_guard_cleanup_logged_containers "${run_log}"
  run_status=1
  startup_retry_index=0
  while (( startup_retry_index <= STARTUP_RETRIES )); do
    [[ "${startup_retry_index}" -gt 0 ]] && echo "[retry] startup retry ${startup_retry_index}/${STARTUP_RETRIES} for ${INSTANCE_ID}" | tee -a "${run_log}"
    runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:launch_sweagent_retry_${startup_retry_index}"
    set +e
    run_cmd=(
      "${START_WITH_TOOLS}" --mode with-mem
      "${SWEAGENT_BIN}" run-batch
      --config "${MODEL_CONFIG}"
      --instances.type swe_bench
      --instances.subset full
      --instances.split test
      --instances.filter "^${INSTANCE_ID}$"
      --instances.deployment.type docker
      --instances.deployment.startup_timeout "${DEPLOYMENT_STARTUP_TIMEOUT_SEC}"
      --output_dir "${attempt_dir}"
      --num_workers 1
      --env_var_path "${ENV_VAR_PATH}"
      --agent.model.per_instance_call_limit "${PER_INSTANCE_CALL_LIMIT}"
      --redo_existing "$( [[ "${REDO_EXISTING}" == "1" ]] && echo True || echo False )"
    )
    if [[ -n "${PYTHON_STANDALONE_DIR}" && "${PYTHON_STANDALONE_DIR}" != "__NONE__" ]]; then
      run_cmd+=(--instances.deployment.python_standalone_dir "${PYTHON_STANDALONE_DIR}")
    fi
    if [[ "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" =~ ^[0-9]+$ ]] && (( INSTANCE_TOTAL_EXEC_TIMEOUT_SEC > 0 )); then
      run_cmd+=(--agent.tools.total_execution_timeout "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}")
      timeout --foreground -k 45s "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}s" "${run_cmd[@]}" 2>&1 | tee -a "${run_log}"
    else
      "${run_cmd[@]}" 2>&1 | tee -a "${run_log}"
    fi
    run_status=$?
    set -e
    if [[ "${run_status}" -eq 0 ]]; then
      runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:sweagent_exit_0"
      break
    fi
    runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:sweagent_exit_${run_status}"
    if grep -q "Runtime did not start within timeout" "${run_log}"; then
      runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:capture_diag_runtime_timeout"
      runtime_guard_capture_diag "${run_log}" "${IMAGE_MATCH_PATTERN}"
      runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:cleanup_after_runtime_timeout"
      runtime_guard_cleanup_logged_containers "${run_log}"
      (( startup_retry_index++ ))
      continue
    fi
    runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:capture_diag_non_runtime_failure"
    runtime_guard_capture_diag "${run_log}" "${IMAGE_MATCH_PATTERN}"
    break
  done

  runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:rebuild_predictions"
  "${PYTHON_BIN}" "${COMMON_DIR}/rebuild_eval_predictions.py" \
    --output-dir "${attempt_dir}" \
    --cache-file "${tmp_cache}" \
    --default-model-name "repeat5_single_withmem_closed_loop" \
    --out "${pred_json}" >/dev/null

  pred_count="$("${PYTHON_BIN}" - <<'PY' "${pred_json}"
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    print(0)
    raise SystemExit(0)
print(len(data) if isinstance(data, dict) else 0)
PY
)"

  if [[ "${pred_count}" -eq 0 ]]; then
    runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:local_eval_stub"
    local_reason="missing_prediction"
    if [[ "${run_status}" -eq 124 || "${run_status}" -eq 137 ]]; then
      local_reason="timeout_no_prediction"
    elif [[ "${run_status}" -ne 0 ]]; then
      local_reason="run_failure_no_prediction"
    fi
    "${PYTHON_BIN}" "${LOCAL_EVAL_STUB_WRITER}" \
      --instance-id "${INSTANCE_ID}" \
      --outcome incomplete \
      --reason "${local_reason}" \
      --out "${raw_report_json}" >/dev/null
  else
    runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:official_eval"
    "${PYTHON_BIN}" -m swebench.harness.run_evaluation \
      --dataset_name SWE-bench/SWE-bench \
      --split test \
      --predictions_path "${pred_json}" \
      --max_workers "${MAX_WORKERS_EVAL}" \
      --timeout "${EVAL_TIMEOUT_SEC}" \
      --cache_level env \
      --clean false \
      --run_id "${eval_run_id}" \
      --instance_ids "${INSTANCE_ID}"
    latest_report="$(ls -1t "${WS_ROOT}"/*.${eval_run_id}.json 2>/dev/null | head -n 1 || true)"
    if [[ -z "${latest_report}" ]]; then
      echo "missing raw eval report for attempt ${attempt_tag}" >&2
      rm -f "${tmp_cache}"
      exit 2
    fi
    cp -f "${latest_report}" "${raw_report_json}"
  fi

  runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:summarize_eval"
  "${PYTHON_BIN}" "${COMMON_DIR}/summarize_official_eval.py" \
    --report-json "${raw_report_json}" \
    --run-id "${eval_run_id}" \
    --dataset "SWE-bench/SWE-bench test" \
    --scope "Repeat5 single-instance with_mem attempt ${attempt_tag}" \
    --summary-out "${summary_json}" >/dev/null

  runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:apply_feedback"
  "${PYTHON_BIN}" "${EVAL_FEEDBACK_APPLIER}" \
    --workspace-root "${WS_ROOT}" \
    --report-json "${raw_report_json}" \
    --output-dir "${attempt_dir}" \
    --cache-file "${tmp_cache}" \
    --run-id "${eval_run_id}" \
    --output-json "${feedback_json}" >/dev/null

  runtime_guard_mark_stage "${run_log}" "attempt_${attempt_tag}:cleanup_after_attempt"
  runtime_guard_cleanup_logged_containers "${run_log}"
  rm -f "${tmp_cache}"
done

"${PYTHON_BIN}" - <<'PY' "${METRICS_DIR}" "${INSTANCE_ID}" "${REPEATS}"
import json, pathlib, sys
metrics_dir = pathlib.Path(sys.argv[1])
instance_id = sys.argv[2]
repeats = int(sys.argv[3])
rows = []
for attempt in range(1, repeats + 1):
    tag = f"{attempt:02d}"
    summary_path = metrics_dir / "attempt_summaries" / f"{instance_id}.attempt_{tag}.summary.json"
    feedback_path = metrics_dir / "attempt_feedback" / f"{instance_id}.attempt_{tag}.feedback.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    feedback = json.loads(feedback_path.read_text(encoding="utf-8")) if feedback_path.exists() else {}
    rows.append({
        "attempt": attempt,
        "summary_path": str(summary_path),
        "feedback_path": str(feedback_path),
        "submitted_instances": summary.get("submitted_instances", 0),
        "resolved_instances": summary.get("resolved_instances", 0),
        "incomplete_instances": summary.get("incomplete_instances", 0),
        "solved_rate_on_planned": summary.get("solved_rate_on_planned", 0.0),
        "feedback_outcome_counts": feedback.get("outcome_counts", {}),
    })
out = metrics_dir / "attempt_summaries.json"
out.write_text(json.dumps({
    "instance_id": instance_id,
    "repeats": repeats,
    "attempts": rows,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(str(out))
PY

echo "done"
echo "exp_dir=${EXP_DIR}"
echo "attempt_summaries=${METRICS_DIR}/attempt_summaries.json"
