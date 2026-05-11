#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# 实验目标：
# 对同一批 instance（默认 full/test 的 0:25）做多次重复求解，对比 with-mem 与 no-mem
# 在重复尝试（attempt1..attempt10）中的官方 resolved 变化。
#
# 运行流程：
# 1) 生成固定 instance 列表（保证 with-mem/no-mem 完全同一组数据）；
# 2) 运行 no-mem 多次实验（每个 instance 重复 REPEATS 次）；
# 3) 运行 with-mem 多次实验（每个 instance 重复 REPEATS 次）；
# 4) 对每个 mode 的每个 attempt 构建预测文件，并跑官方评测；
# 5) 汇总每个 attempt 的 resolved 数量与 resolved_rate，输出对比 JSON。
#
# 注意：
# - 本脚本只编排流程，不改变 agent 核心代码。
# - 评测阶段会调用 swebench 官方评测流水线，耗时较长。
# -----------------------------------------------------------------------------
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
COMMON_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common"

NO_MEM_SCRIPT="${NO_MEM_SCRIPT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/no_mem/scripts/run_multi_try_no_mem_20min.sh}"
WITH_MEM_SCRIPT="${WITH_MEM_SCRIPT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/with_mem/scripts/run_multi_try_with_mem_20min.sh}"

RUNS_BASE_DIR="${RUNS_BASE_DIR:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/comparison_runs}"
RUN_PREFIX="${RUN_PREFIX:-first25_repeat10_slide25}"
AUTO_RESUME_LATEST="${AUTO_RESUME_LATEST:-1}"
RESUME_MODE="${RESUME_MODE:-1}"
REUSE_EXISTING_INSTANCE_LIST="${REUSE_EXISTING_INSTANCE_LIST:-1}"
AUTO_RESUME_START="${AUTO_RESUME_START:-1}"
RESUME_START_INDEX="${RESUME_START_INDEX:-auto}"  # auto | integer
PARALLEL_MODE_RUN="${PARALLEL_MODE_RUN:-1}"       # 1: no_mem + with_mem 并行跑
RUN_TAG="${RUN_TAG:-}"
if [[ -z "${RUN_TAG}" ]]; then
  if [[ "${AUTO_RESUME_LATEST}" == "1" ]]; then
    latest_run="$(ls -1dt "${RUNS_BASE_DIR}/${RUN_PREFIX}_"* 2>/dev/null | head -n 1 || true)"
    if [[ -n "${latest_run}" ]]; then
      RUN_TAG="$(basename "${latest_run}")"
    fi
  fi
  if [[ -z "${RUN_TAG}" ]]; then
    RUN_TAG="${RUN_PREFIX}_$(date +%Y%m%d_%H%M%S)"
  fi
fi
BASE_DIR="${BASE_DIR:-${RUNS_BASE_DIR}/${RUN_TAG}}"
SHARED_CACHE_DIR="${BASE_DIR}/cache"
INSTANCE_LIST_JSON="${INSTANCE_LIST_JSON:-${SHARED_CACHE_DIR}/instance_ids.json}"
INSTANCE_META_JSON="${INSTANCE_META_JSON:-${SHARED_CACHE_DIR}/instance_meta_with_images.json}"

NO_MEM_EXP_DIR="${BASE_DIR}/no_mem"
WITH_MEM_EXP_DIR="${BASE_DIR}/with_mem"
EVAL_DIR="${BASE_DIR}/official_eval"
RAW_REPORTS_DIR="${EVAL_DIR}/raw_reports"
SUMMARY_DIR="${EVAL_DIR}/summary_by_attempt"
PREDS_DIR="${EVAL_DIR}/predictions"
mkdir -p "${SHARED_CACHE_DIR}" "${NO_MEM_EXP_DIR}" "${WITH_MEM_EXP_DIR}" "${RAW_REPORTS_DIR}" "${SUMMARY_DIR}" "${PREDS_DIR}"

SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-full}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
START_INDEX="${START_INDEX:-0}"
INSTANCE_COUNT="${INSTANCE_COUNT:-25}"
REPEATS="${REPEATS:-10}"
WINDOW_SIZE="${WINDOW_SIZE:-25}"

MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_siliconflow.yaml}"
NUM_WORKERS="${NUM_WORKERS:-1}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
ENV_VAR_PATH="${ENV_VAR_PATH:-${SWE_AGENT_ROOT}/.env}"
REDO_EXISTING="${REDO_EXISTING:-0}"
RESET_INSTANCE_MEMORY="${RESET_INSTANCE_MEMORY:-1}"

MAX_WORKERS_EVAL="${MAX_WORKERS_EVAL:-4}"
EVAL_TIMEOUT_SEC="${EVAL_TIMEOUT_SEC:-1200}"
SKIP_EXISTING_EVAL_SUMMARY="${SKIP_EXISTING_EVAL_SUMMARY:-1}"

RUN_PHASE="${RUN_PHASE:-all}"  # all | run_only | eval_only
KEEP_BASE_RANGES="${KEEP_BASE_RANGES:-}"
PREFETCH_NEXT_WINDOW="${PREFETCH_NEXT_WINDOW:-1}"
PRUNE_BUILD_CACHE_EACH_WINDOW="${PRUNE_BUILD_CACHE_EACH_WINDOW:-1}"

is_int() { [[ "$1" =~ ^[0-9]+$ ]]; }
require_int() {
  local name="$1"
  local val="$2"
  if ! is_int "${val}"; then
    echo "${name} must be integer, got=${val}" >&2
    exit 2
  fi
}

for required in "${PYTHON_BIN}" "${NO_MEM_SCRIPT}" "${WITH_MEM_SCRIPT}"; do
  if [[ ! -e "${required}" ]]; then
    echo "required file not found: ${required}" >&2
    exit 2
  fi
done

require_int "START_INDEX" "${START_INDEX}"
require_int "INSTANCE_COUNT" "${INSTANCE_COUNT}"
require_int "REPEATS" "${REPEATS}"
require_int "WINDOW_SIZE" "${WINDOW_SIZE}"
require_int "MAX_WORKERS_EVAL" "${MAX_WORKERS_EVAL}"
require_int "EVAL_TIMEOUT_SEC" "${EVAL_TIMEOUT_SEC}"
require_int "INSTANCE_TOTAL_EXEC_TIMEOUT_SEC" "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}"
require_int "REDO_EXISTING" "${REDO_EXISTING}"
require_int "RESUME_MODE" "${RESUME_MODE}"
require_int "AUTO_RESUME_START" "${AUTO_RESUME_START}"
require_int "PARALLEL_MODE_RUN" "${PARALLEL_MODE_RUN}"
require_int "SKIP_EXISTING_EVAL_SUMMARY" "${SKIP_EXISTING_EVAL_SUMMARY}"
if [[ "${RESUME_START_INDEX}" != "auto" ]]; then
  require_int "RESUME_START_INDEX" "${RESUME_START_INDEX}"
fi

build_shared_instance_list() {
  "${PYTHON_BIN}" - <<'PY' "${INSTANCE_LIST_JSON}" "${INSTANCE_META_JSON}" "${SWEBENCH_SUBSET}" "${SWEBENCH_SPLIT}" "${START_INDEX}" "${INSTANCE_COUNT}"
import json
import pathlib
import sys
from datetime import datetime, timezone
from sweagent.run.batch_instances import SWEBenchInstances

out_path = pathlib.Path(sys.argv[1])
meta_path = pathlib.Path(sys.argv[2])
subset = sys.argv[3]
split = sys.argv[4]
start = int(sys.argv[5])
count = int(sys.argv[6])
stop = start + count

instances = SWEBenchInstances(subset=subset, split=split, slice=f"{start}:{stop}").get_instance_configs()
ids = []
meta_rows = []
for inst in instances:
    iid = inst.problem_statement.id
    image = inst.env.deployment.image
    ids.append(iid)
    meta_rows.append({"id": iid, "image": image})
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "subset": subset,
    "split": split,
    "start_index": start,
    "instance_count_requested": count,
    "instance_count_actual": len(ids),
    "instance_ids": ids,
}
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
meta_path.parent.mkdir(parents=True, exist_ok=True)
meta_path.write_text(json.dumps(meta_rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"instance_ids={len(ids)} -> {out_path}")
print(f"instance_meta={len(meta_rows)} -> {meta_path}")
PY
}

ids_csv_from_json() {
  "${PYTHON_BIN}" - <<'PY' "${INSTANCE_LIST_JSON}"
import json
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
ids = data.get("instance_ids", [])
if not isinstance(ids, list) or not ids:
    raise SystemExit("empty instance_ids in shared cache")
print(",".join(str(x) for x in ids))
PY
}

read_ids_to_array() {
  "${PYTHON_BIN}" - <<'PY' "${INSTANCE_LIST_JSON}"
import json
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
for iid in data.get("instance_ids", []):
    print(iid)
PY
}

images_for_ranges() {
  "${PYTHON_BIN}" - <<'PY' "${INSTANCE_META_JSON}" "$@"
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

csv_for_window() {
  "${PYTHON_BIN}" - <<'PY' "${INSTANCE_LIST_JSON}" "${1}" "${2}"
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
ids = data.get("instance_ids", [])
start = int(sys.argv[2])
end = int(sys.argv[3])
if not isinstance(ids, list):
    raise SystemExit("instance_ids must be list")
window = [str(x) for x in ids[start:end]]
print(",".join(window))
PY
}

attempt_is_complete() {
  local iid="$1"
  local attempt_outdir="$2"
  local instance_dir="${attempt_outdir}/${iid}"
  if [[ -f "${attempt_outdir}/run_batch_exit_statuses.yaml" ]]; then
    return 0
  fi
  if [[ -f "${attempt_outdir}/preds.json" ]]; then
    return 0
  fi
  if [[ -f "${instance_dir}/${iid}.traj" && -f "${instance_dir}/${iid}.pred" ]]; then
    return 0
  fi
  return 1
}

instance_mode_complete() {
  local mode_exp_dir="$1"
  local iid="$2"
  local attempt attempt_tag attempt_outdir
  for attempt in $(seq 1 "${REPEATS}"); do
    attempt_tag="$(printf "%02d" "${attempt}")"
    attempt_outdir="${mode_exp_dir}/outputs/${iid}/attempt_${attempt_tag}"
    if ! attempt_is_complete "${iid}" "${attempt_outdir}"; then
      return 1
    fi
  done
  return 0
}

find_resume_start_index() {
  local total_count="$1"
  local i iid
  for ((i = 0; i < total_count; i++)); do
    iid="${ALL_INSTANCE_IDS[$i]}"
    if ! instance_mode_complete "${NO_MEM_EXP_DIR}" "${iid}"; then
      echo "${i}"
      return 0
    fi
    if ! instance_mode_complete "${WITH_MEM_EXP_DIR}" "${iid}"; then
      echo "${i}"
      return 0
    fi
  done
  echo "${total_count}"
}

build_predictions_for_attempt() {
  local mode="$1"          # no_mem | with_mem
  local outputs_root="$2"  # mode output root
  local attempt_tag="$3"   # 01..10
  local preds_out="$4"

  "${PYTHON_BIN}" - <<'PY' "${INSTANCE_LIST_JSON}" "${outputs_root}" "${attempt_tag}" "${preds_out}" "${mode}"
import json
import pathlib
import sys

ids_file = pathlib.Path(sys.argv[1])
outputs_root = pathlib.Path(sys.argv[2])
attempt_tag = sys.argv[3]
preds_out = pathlib.Path(sys.argv[4])
mode = sys.argv[5]

data = json.loads(ids_file.read_text(encoding="utf-8"))
ids = data.get("instance_ids", [])
if not isinstance(ids, list):
    raise SystemExit("instance_ids must be list")

def extract_patch(pred_path: pathlib.Path, traj_path: pathlib.Path) -> str:
    if pred_path.exists():
        text = pred_path.read_text(encoding="utf-8", errors="ignore")
        stripped = text.lstrip()
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    patch = str(obj.get("model_patch", "") or "")
                    if patch.strip():
                        return patch
            except Exception:
                pass
        if stripped:
            return text
    if traj_path.exists():
        try:
            traj = json.loads(traj_path.read_text(encoding="utf-8"))
            info = traj.get("info", {}) if isinstance(traj, dict) else {}
            patch = str(info.get("submission", "") or "")
            if patch.strip():
                return patch
        except Exception:
            pass
    return ""

preds: dict[str, dict] = {}
for iid in ids:
    attempt_dir = outputs_root / iid / f"attempt_{attempt_tag}" / iid
    pred_path = attempt_dir / f"{iid}.pred"
    traj_path = attempt_dir / f"{iid}.traj"
    patch = extract_patch(pred_path, traj_path)
    if not patch.strip():
        continue
    if not patch.endswith("\n"):
        patch += "\n"
    preds[iid] = {
        "model_name_or_path": f"multi_try_{mode}_attempt_{attempt_tag}",
        "instance_id": iid,
        "model_patch": patch,
    }

preds_out.parent.mkdir(parents=True, exist_ok=True)
preds_out.write_text(json.dumps(preds, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"preds={len(preds)} -> {preds_out}")
PY
}

run_mode_experiment() {
  local mode="$1"  # no_mem | with_mem
  local exp_dir="$2"
  local script="$3"
  local csv="$4"

  if [[ "${mode}" == "no_mem" ]]; then
    WS_ROOT="${WS_ROOT}" \
    EXP_DIR="${exp_dir}" \
    OUTDIR="${exp_dir}/outputs" \
    LOG_DIR="${exp_dir}/logs/no_mem" \
    CACHE_DIR="${exp_dir}/cache" \
    METRICS_DIR="${exp_dir}/metrics" \
    INSTANCE_LIST_FILE="${exp_dir}/cache/instance_ids.json" \
    SUMMARY_OUT="${exp_dir}/metrics/summary_multi_try_no_mem_20min.json" \
    SWEBENCH_SUBSET="${SWEBENCH_SUBSET}" \
    SWEBENCH_SPLIT="${SWEBENCH_SPLIT}" \
    START_INDEX="${START_INDEX}" \
    INSTANCE_COUNT="${INSTANCE_COUNT}" \
    INSTANCE_IDS_CSV="${csv}" \
    REPEATS="${REPEATS}" \
    MODEL_CONFIG="${MODEL_CONFIG}" \
    NUM_WORKERS="${NUM_WORKERS}" \
    PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT}" \
    INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
    REDO_EXISTING="${REDO_EXISTING}" \
    RESUME_MODE="${RESUME_MODE}" \
    ENV_VAR_PATH="${ENV_VAR_PATH}" \
    "${script}"
  else
    WS_ROOT="${WS_ROOT}" \
    EXP_DIR="${exp_dir}" \
    OUTDIR="${exp_dir}/outputs" \
    LOG_DIR="${exp_dir}/logs/with_mem" \
    PERSIST_ROOT="${exp_dir}/persistence" \
    CACHE_DIR="${exp_dir}/cache" \
    METRICS_DIR="${exp_dir}/metrics" \
    INSTANCE_LIST_FILE="${exp_dir}/cache/instance_ids.json" \
    SUMMARY_OUT="${exp_dir}/metrics/summary_multi_try_with_mem_20min.json" \
    SWEBENCH_SUBSET="${SWEBENCH_SUBSET}" \
    SWEBENCH_SPLIT="${SWEBENCH_SPLIT}" \
    START_INDEX="${START_INDEX}" \
    INSTANCE_COUNT="${INSTANCE_COUNT}" \
    INSTANCE_IDS_CSV="${csv}" \
    REPEATS="${REPEATS}" \
    MODEL_CONFIG="${MODEL_CONFIG}" \
    NUM_WORKERS="${NUM_WORKERS}" \
    PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT}" \
    INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
    REDO_EXISTING="${REDO_EXISTING}" \
    RESUME_MODE="${RESUME_MODE}" \
    RESET_INSTANCE_MEMORY="${RESET_INSTANCE_MEMORY}" \
    ENV_VAR_PATH="${ENV_VAR_PATH}" \
    "${script}"
  fi
}

run_window_modes() {
  local window_ids_csv="$1"
  local current_start="$2"
  local current_end="$3"
  local rc_no=0
  local rc_with=0

  if [[ "${PARALLEL_MODE_RUN}" == "1" ]]; then
    echo "[run] parallel modes window=${current_start}:${current_end}"
    run_mode_experiment "no_mem" "${NO_MEM_EXP_DIR}" "${NO_MEM_SCRIPT}" "${window_ids_csv}" &
    local pid_no=$!
    run_mode_experiment "with_mem" "${WITH_MEM_EXP_DIR}" "${WITH_MEM_SCRIPT}" "${window_ids_csv}" &
    local pid_with=$!

    wait "${pid_no}" || rc_no=$?
    wait "${pid_with}" || rc_with=$?

    if (( rc_no != 0 || rc_with != 0 )); then
      echo "window=${current_start}:${current_end} failed rc_no=${rc_no} rc_with=${rc_with}" >&2
      exit 2
    fi
  else
    echo "[run] no_mem window=${current_start}:${current_end}"
    run_mode_experiment "no_mem" "${NO_MEM_EXP_DIR}" "${NO_MEM_SCRIPT}" "${window_ids_csv}"
    echo "[run] with_mem window=${current_start}:${current_end}"
    run_mode_experiment "with_mem" "${WITH_MEM_EXP_DIR}" "${WITH_MEM_SCRIPT}" "${window_ids_csv}"
  fi
}

rebuild_full_multi_try_summary() {
  local mode="$1"      # no-mem | with-mem
  local exp_dir="$2"
  local summary_out="$3"
  local event_log_root
  if [[ "${mode}" == "no-mem" ]]; then
    event_log_root="${exp_dir}/logs/no_mem"
  else
    event_log_root="${exp_dir}/logs/with_mem"
  fi

  "${PYTHON_BIN}" "${COMMON_DIR}/collect_multi_try_summary.py" \
    --experiment-id "${RUN_TAG}_${mode}_windowed" \
    --mode "${mode}" \
    --workspace-root "${WS_ROOT}" \
    --output-root "${exp_dir}/outputs" \
    --instance-list-file "${INSTANCE_LIST_JSON}" \
    --repeats "${REPEATS}" \
    --event-log-root "${event_log_root}" \
    --summary-out "${summary_out}"
}

evaluate_mode_attempt() {
  local mode="$1"          # no_mem | with_mem
  local outputs_root="$2"  # ${mode_exp_dir}/outputs
  local attempt_tag="$3"

  local preds_json="${PREDS_DIR}/${mode}_attempt_${attempt_tag}.json"
  local run_id="multi_try_${RUN_TAG}_${mode}_attempt_${attempt_tag}_eval_$(date +%Y%m%d_%H%M%S)"
  local raw_report_link="${RAW_REPORTS_DIR}/${mode}_attempt_${attempt_tag}.${run_id}.json"
  local summary_json="${SUMMARY_DIR}/${mode}_attempt_${attempt_tag}.json"

  if [[ "${SKIP_EXISTING_EVAL_SUMMARY}" == "1" && -f "${summary_json}" ]]; then
    echo "[eval] skip ${mode} attempt=${attempt_tag}: summary already exists"
    return 0
  fi

  build_predictions_for_attempt "${mode}" "${outputs_root}" "${attempt_tag}" "${preds_json}"

  mapfile -t INSTANCE_IDS < <(read_ids_to_array)
  if [[ "${#INSTANCE_IDS[@]}" -eq 0 ]]; then
    echo "No instance ids in ${INSTANCE_LIST_JSON}" >&2
    exit 2
  fi

  local pred_count
  pred_count="$("${PYTHON_BIN}" - <<'PY' "${preds_json}"
import json
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
if not p.exists():
    print(0)
    raise SystemExit(0)
data = json.loads(p.read_text(encoding="utf-8"))
print(len(data) if isinstance(data, dict) else 0)
PY
)"

  if [[ "${pred_count}" == "0" ]]; then
    "${PYTHON_BIN}" - <<'PY' "${summary_json}" "${run_id}" "${INSTANCE_LIST_JSON}" "${mode}" "${attempt_tag}" "${preds_json}"
import json
import pathlib
import sys
from datetime import datetime

summary_path = pathlib.Path(sys.argv[1])
run_id = sys.argv[2]
instance_list_path = pathlib.Path(sys.argv[3])
mode = sys.argv[4]
attempt_tag = sys.argv[5]
preds_json = pathlib.Path(sys.argv[6]).resolve()
instance_data = json.loads(instance_list_path.read_text(encoding="utf-8"))
instance_ids = instance_data.get("instance_ids", [])
summary = {
    "run_id": run_id,
    "dataset": "SWE-bench/SWE-bench test",
    "scope": f"multi_try {mode} attempt_{attempt_tag}",
    "planned_instances": len(instance_ids),
    "submitted_instances": 0,
    "completed_instances": 0,
    "resolved_instances": 0,
    "unresolved_instances": 0,
    "error_instances": 0,
    "incomplete_instances": len(instance_ids),
    "incomplete_ids": instance_ids,
    "solved_rate_on_planned": 0.0,
    "solved_rate_on_submitted": 0.0,
    "report_json": None,
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "skipped_reason": "empty_predictions",
    "predictions_path": str(preds_json),
}
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(str(summary_path))
PY
    echo "[eval] skip ${mode} attempt=${attempt_tag}: empty predictions"
    return 0
  fi

  "${PYTHON_BIN}" -m swebench.harness.run_evaluation \
    --dataset_name SWE-bench/SWE-bench \
    --split test \
    --predictions_path "${preds_json}" \
    --max_workers "${MAX_WORKERS_EVAL}" \
    --timeout "${EVAL_TIMEOUT_SEC}" \
    --cache_level env \
    --clean false \
    --run_id "${run_id}" \
    --instance_ids "${INSTANCE_IDS[@]}"

  local raw_report
  raw_report="$(ls -1t "${WS_ROOT}"/*.${run_id}.json 2>/dev/null | head -n 1 || true)"
  if [[ -z "${raw_report}" ]]; then
    echo "Cannot find raw eval report for run_id=${run_id}" >&2
    exit 2
  fi

  cp -f "${raw_report}" "${raw_report_link}"

  "${PYTHON_BIN}" "${COMMON_DIR}/summarize_official_eval.py" \
    --report-json "${raw_report}" \
    --run-id "${run_id}" \
    --dataset "SWE-bench/SWE-bench test" \
    --scope "multi_try ${mode} attempt_${attempt_tag}" \
    --summary-out "${summary_json}"
}

aggregate_attempt_level_report() {
  "${PYTHON_BIN}" - <<'PY' "${SUMMARY_DIR}" "${REPEATS}" "${EVAL_DIR}"
import json
import pathlib
import sys

summary_dir = pathlib.Path(sys.argv[1])
repeats = int(sys.argv[2])
eval_dir = pathlib.Path(sys.argv[3])

rows = []
for i in range(1, repeats + 1):
    tag = f"{i:02d}"
    no_p = summary_dir / f"no_mem_attempt_{tag}.json"
    with_p = summary_dir / f"with_mem_attempt_{tag}.json"
    no_j = json.loads(no_p.read_text(encoding="utf-8")) if no_p.exists() else {}
    with_j = json.loads(with_p.read_text(encoding="utf-8")) if with_p.exists() else {}
    row = {
        "attempt": i,
        "no_mem": {
            "resolved_instances": int(no_j.get("resolved_instances", 0) or 0),
            "planned_instances": int(no_j.get("planned_instances", 0) or 0),
            "submitted_instances": int(no_j.get("submitted_instances", 0) or 0),
            "resolved_rate": float(no_j.get("solved_rate_on_planned", 0.0) or 0.0),
            "resolved_rate_on_submitted": float(no_j.get("solved_rate_on_submitted", 0.0) or 0.0),
            "summary_file": str(no_p),
            "skipped_reason": no_j.get("skipped_reason"),
        },
        "with_mem": {
            "resolved_instances": int(with_j.get("resolved_instances", 0) or 0),
            "planned_instances": int(with_j.get("planned_instances", 0) or 0),
            "submitted_instances": int(with_j.get("submitted_instances", 0) or 0),
            "resolved_rate": float(with_j.get("solved_rate_on_planned", 0.0) or 0.0),
            "resolved_rate_on_submitted": float(with_j.get("solved_rate_on_submitted", 0.0) or 0.0),
            "summary_file": str(with_p),
            "skipped_reason": with_j.get("skipped_reason"),
        },
    }
    row["delta_resolved_rate"] = round(row["with_mem"]["resolved_rate"] - row["no_mem"]["resolved_rate"], 6)
    row["delta_resolved_rate_on_submitted"] = round(
        row["with_mem"]["resolved_rate_on_submitted"] - row["no_mem"]["resolved_rate_on_submitted"], 6
    )
    row["delta_resolved_instances"] = row["with_mem"]["resolved_instances"] - row["no_mem"]["resolved_instances"]
    rows.append(row)

out = {
    "report_version": "v1",
    "attempt_count": repeats,
    "per_attempt": rows,
}

out_path = eval_dir / "resolved_rate_by_attempt_with_vs_no_mem.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(str(out_path))
PY
}

echo "RUN_TAG=${RUN_TAG}"
echo "BASE_DIR=${BASE_DIR}"
echo "subset=${SWEBENCH_SUBSET} split=${SWEBENCH_SPLIT} start=${START_INDEX} count=${INSTANCE_COUNT} repeats=${REPEATS}"

if [[ "${RUN_PHASE}" == "all" || "${RUN_PHASE}" == "run_only" ]]; then
  if [[ "${REUSE_EXISTING_INSTANCE_LIST}" == "1" && -f "${INSTANCE_LIST_JSON}" && -f "${INSTANCE_META_JSON}" ]]; then
    echo "Reuse existing instance list/meta: ${INSTANCE_LIST_JSON}"
  else
    build_shared_instance_list
  fi
  mapfile -t ALL_INSTANCE_IDS < <(read_ids_to_array)
  if [[ "${#ALL_INSTANCE_IDS[@]}" -eq 0 ]]; then
    echo "No instance ids selected." >&2
    exit 2
  fi
  total_count="${#ALL_INSTANCE_IDS[@]}"
  echo "instance_total=${total_count}, window_size=${WINDOW_SIZE}, parallel_mode=${PARALLEL_MODE_RUN}, resume_mode=${RESUME_MODE}"

  resume_index=0
  if [[ "${RESUME_START_INDEX}" == "auto" ]]; then
    if [[ "${RESUME_MODE}" == "1" && "${AUTO_RESUME_START}" == "1" ]]; then
      resume_index="$(find_resume_start_index "${total_count}")"
    fi
  else
    resume_index="${RESUME_START_INDEX}"
  fi

  if (( resume_index >= total_count )); then
    echo "All instances/attempts are complete. Nothing to run."
  else
    current_start=$(((resume_index / WINDOW_SIZE) * WINDOW_SIZE))
    if (( current_start < 0 )); then
      current_start=0
    fi
    prev_start=$((current_start - WINDOW_SIZE))
    if (( prev_start < 0 )); then
      prev_start=-1
      prev_end=-1
    else
      prev_end=${current_start}
    fi

    while (( current_start < total_count )); do
      current_end=$((current_start + WINDOW_SIZE))
      if (( current_end > total_count )); then
        current_end=${total_count}
      fi
      next_start=${current_end}
      next_end=$((next_start + WINDOW_SIZE))
      if (( next_end > total_count )); then
        next_end=${total_count}
      fi

      prefetch_log="${BASE_DIR}/logs/prefetch_window_${current_start}_${current_end}.log"
      cleanup_log="${BASE_DIR}/logs/cleanup_window_${current_start}_${current_end}.log"
      mkdir -p "${BASE_DIR}/logs"

      echo "Window run plan: start=${current_start} end=${current_end} next_start=${next_start} next_end=${next_end} resume_index=${resume_index} total=${total_count}"
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

      WINDOW_IDS_CSV="$(csv_for_window "${current_start}" "${current_end}")"
      if [[ -z "${WINDOW_IDS_CSV}" ]]; then
        echo "Window ${current_start}:${current_end} has empty id list, skip." >&2
      else
        run_window_modes "${WINDOW_IDS_CSV}" "${current_start}" "${current_end}"
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
      current_start=${current_end}
    done
  fi

  rebuild_full_multi_try_summary "no-mem" "${NO_MEM_EXP_DIR}" "${NO_MEM_EXP_DIR}/metrics/summary_multi_try_no_mem_20min.json"
  rebuild_full_multi_try_summary "with-mem" "${WITH_MEM_EXP_DIR}" "${WITH_MEM_EXP_DIR}/metrics/summary_multi_try_with_mem_20min.json"
fi

if [[ "${RUN_PHASE}" == "all" || "${RUN_PHASE}" == "eval_only" ]]; then
  if [[ ! -f "${INSTANCE_LIST_JSON}" ]]; then
    echo "Missing ${INSTANCE_LIST_JSON}. Cannot evaluate." >&2
    exit 2
  fi
  for i in $(seq 1 "${REPEATS}"); do
    tag="$(printf "%02d" "${i}")"
    echo "[eval] no_mem attempt=${tag}"
    evaluate_mode_attempt "no_mem" "${NO_MEM_EXP_DIR}/outputs" "${tag}"
    echo "[eval] with_mem attempt=${tag}"
    evaluate_mode_attempt "with_mem" "${WITH_MEM_EXP_DIR}/outputs" "${tag}"
  done

  final_report="$(aggregate_attempt_level_report)"
  echo "final_report=${final_report}"
fi

echo "done"
