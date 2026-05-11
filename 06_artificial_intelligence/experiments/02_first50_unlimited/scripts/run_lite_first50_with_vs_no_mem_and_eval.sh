#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
COMMON_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common"
EXP_ROOT="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited"
NO_MEM_DIR="${EXP_ROOT}/no_mem"
WITH_MEM_DIR="${EXP_ROOT}/with_mem"

NO_MEM_RUN_SCRIPT="${NO_MEM_RUN_SCRIPT:-${NO_MEM_DIR}/scripts/run_lite_first50_nomem.sh}"
WITH_MEM_RUN_SCRIPT="${WITH_MEM_RUN_SCRIPT:-${WITH_MEM_DIR}/scripts/run_lite_first50_with_mem.sh}"

SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-lite}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
START_INDEX="${START_INDEX:-0}"
STOP_INDEX="${STOP_INDEX:-50}"
WINDOW_SIZE="${WINDOW_SIZE:-25}"
AUTO_CONTINUE="${AUTO_CONTINUE:-1}"
NUM_WORKERS="${NUM_WORKERS:-1}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_siliconflow.yaml}"
ENV_VAR_PATH="${ENV_VAR_PATH:-${SWE_AGENT_ROOT}/.env}"
REDO_EXISTING="${REDO_EXISTING:-1}"

MAX_WORKERS_EVAL="${MAX_WORKERS_EVAL:-4}"
EVAL_TIMEOUT_SEC="${EVAL_TIMEOUT_SEC:-1200}"

RUN_TAG="${RUN_TAG:-first50_with_vs_no_mem_$(date +%Y%m%d_%H%M%S)}"
EVAL_DIR="${EXP_ROOT}/notes/official_eval_runs/${RUN_TAG}"
LOG_DIR="${EVAL_DIR}/logs"
mkdir -p "${EVAL_DIR}" "${LOG_DIR}"

CACHE_FILE="${NO_MEM_DIR}/cache/lite_test_instances_cache.json"
CACHE_META_FILE="${EVAL_DIR}/cache_with_images.json"

# Hard constraints for this experiment:
# 1) step unlimited
# 2) each instance/attempt max 20 minutes
PER_INSTANCE_CALL_LIMIT="0"
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="1200"

# Sliding-window controls:
KEEP_BASE_RANGES="${KEEP_BASE_RANGES:-}"
PREFETCH_NEXT_WINDOW="${PREFETCH_NEXT_WINDOW:-1}"
PRUNE_BUILD_CACHE_EACH_WINDOW="${PRUNE_BUILD_CACHE_EACH_WINDOW:-1}"

is_int() { [[ "$1" =~ ^[0-9]+$ ]]; }
for v in START_INDEX STOP_INDEX WINDOW_SIZE NUM_WORKERS MAX_WORKERS_EVAL EVAL_TIMEOUT_SEC; do
  if ! is_int "${!v}"; then
    echo "${v} must be integer, got=${!v}" >&2
    exit 2
  fi
done

build_instance_cache_with_images() {
  "${PYTHON_BIN}" - <<'PY' "${CACHE_FILE}" "${CACHE_META_FILE}" "${SWEBENCH_SUBSET}" "${SWEBENCH_SPLIT}" "${STOP_INDEX}"
import json
import pathlib
import sys
from sweagent.run.batch_instances import SWEBenchInstances

cache_ids = pathlib.Path(sys.argv[1])
cache_meta = pathlib.Path(sys.argv[2])
subset = sys.argv[3]
split = sys.argv[4]
stop = int(sys.argv[5])
slice_expr = f":{stop}" if stop > 0 else ""
instances = SWEBenchInstances(subset=subset, split=split, slice=slice_expr).get_instance_configs()
ids = []
meta = []
for inst in instances:
    iid = inst.problem_statement.id
    image = inst.env.deployment.image
    ids.append(iid)
    meta.append({"id": iid, "image": image})
cache_ids.parent.mkdir(parents=True, exist_ok=True)
cache_meta.parent.mkdir(parents=True, exist_ok=True)
cache_ids.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")
cache_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"cached {len(ids)} ids -> {cache_ids}")
print(f"cached {len(meta)} id/image rows -> {cache_meta}")
PY
}

images_for_ranges() {
  "${PYTHON_BIN}" - <<'PY' "${CACHE_META_FILE}" "$@"
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

for required in "${PYTHON_BIN}" "${NO_MEM_RUN_SCRIPT}" "${WITH_MEM_RUN_SCRIPT}"; do
  if [[ ! -e "${required}" ]]; then
    echo "required file not found: ${required}" >&2
    exit 2
  fi
done

echo "Experiment constraints:"
echo "- per_instance_call_limit=${PER_INSTANCE_CALL_LIMIT} (0 means unlimited steps)"
echo "- instance_total_exec_timeout_sec=${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC} (20 minutes)"
echo "- sliding_window_size=${WINDOW_SIZE}"

build_instance_cache_with_images
if [[ ! -f "${CACHE_FILE}" ]]; then
  echo "cache file missing: ${CACHE_FILE}" >&2
  exit 2
fi

echo "[1/6] run first50 in window mode (prefetch + cleanup), window=${WINDOW_SIZE}"
if (( START_INDEX < STOP_INDEX )); then
  current_start="${START_INDEX}"
  prev_start=-1
  prev_end=-1
  while (( current_start < STOP_INDEX )); do
    current_end=$((current_start + WINDOW_SIZE))
    if (( current_end > STOP_INDEX )); then
      current_end=${STOP_INDEX}
    fi
    next_start=${current_end}
    next_end=$((next_start + WINDOW_SIZE))
    if (( next_end > STOP_INDEX )); then
      next_end=${STOP_INDEX}
    fi

    prefetch_log="${LOG_DIR}/prefetch_window_${current_start}_${current_end}.log"
    cleanup_log="${LOG_DIR}/cleanup_window_${current_start}_${current_end}.log"
    echo "Window run plan: start=${current_start} end=${current_end} next_start=${next_start} next_end=${next_end} stop=${STOP_INDEX}"

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

    echo "[window ${current_start}:${current_end}] run no-mem"
    WS_ROOT="${WS_ROOT}" \
    SWEBENCH_SUBSET="${SWEBENCH_SUBSET}" \
    SWEBENCH_SPLIT="${SWEBENCH_SPLIT}" \
    START_INDEX="${current_start}" \
    STOP_INDEX="${STOP_INDEX}" \
    WINDOW_SIZE="${WINDOW_SIZE}" \
    AUTO_CONTINUE="0" \
    PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT}" \
    INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
    NUM_WORKERS="${NUM_WORKERS}" \
    MODEL_CONFIG="${MODEL_CONFIG}" \
    ENV_VAR_PATH="${ENV_VAR_PATH}" \
    REDO_EXISTING="${REDO_EXISTING}" \
    "${NO_MEM_RUN_SCRIPT}"

    echo "[window ${current_start}:${current_end}] run with-mem"
    WS_ROOT="${WS_ROOT}" \
    SWEBENCH_SUBSET="${SWEBENCH_SUBSET}" \
    SWEBENCH_SPLIT="${SWEBENCH_SPLIT}" \
    START_INDEX="${current_start}" \
    STOP_INDEX="${STOP_INDEX}" \
    WINDOW_SIZE="${WINDOW_SIZE}" \
    AUTO_CONTINUE="0" \
    PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT}" \
    INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
    NUM_WORKERS="${NUM_WORKERS}" \
    MODEL_CONFIG="${MODEL_CONFIG}" \
    ENV_VAR_PATH="${ENV_VAR_PATH}" \
    REDO_EXISTING="${REDO_EXISTING}" \
    "${WITH_MEM_RUN_SCRIPT}"

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

    if [[ "${AUTO_CONTINUE}" != "1" ]]; then
      break
    fi
    current_start=${current_end}
  done
else
  echo "START_INDEX >= STOP_INDEX, no run needed."
fi

NO_MEM_OUTDIR="${NO_MEM_DIR}/outputs/run_outputs_lite_first50_nomem"
WITH_MEM_OUTDIR="${WITH_MEM_DIR}/outputs/run_outputs_lite_first50_with_mem"

mapfile -t INSTANCE_IDS < <("${PYTHON_BIN}" - <<'PY' "${CACHE_FILE}"
import json, pathlib, sys
ids = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(ids, list) or not ids:
    raise SystemExit("instance id cache is empty")
for iid in ids:
    print(iid)
PY
)

echo "[2/6] rebuild predictions"
NO_MEM_PREDS="${EVAL_DIR}/preds_no_mem.json"
WITH_MEM_PREDS="${EVAL_DIR}/preds_with_mem.json"

"${PYTHON_BIN}" "${COMMON_DIR}/rebuild_eval_predictions.py" \
  --output-dir "${NO_MEM_OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --default-model-name "run_outputs_lite_first50_nomem" \
  --out "${NO_MEM_PREDS}"

"${PYTHON_BIN}" "${COMMON_DIR}/rebuild_eval_predictions.py" \
  --output-dir "${WITH_MEM_OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --default-model-name "run_outputs_lite_first50_with_mem" \
  --out "${WITH_MEM_PREDS}"

RUN_ID_NO="first50_nomem_eval_${RUN_TAG}"
RUN_ID_WITH="first50_withmem_eval_${RUN_TAG}"

echo "[3/6] official eval no-mem"
"${PYTHON_BIN}" -m swebench.harness.run_evaluation \
  --dataset_name SWE-bench/SWE-bench \
  --split test \
  --predictions_path "${NO_MEM_PREDS}" \
  --max_workers "${MAX_WORKERS_EVAL}" \
  --timeout "${EVAL_TIMEOUT_SEC}" \
  --cache_level env \
  --clean false \
  --run_id "${RUN_ID_NO}" \
  --instance_ids "${INSTANCE_IDS[@]}"

RAW_NO="$(ls -1t "${WS_ROOT}"/*.${RUN_ID_NO}.json 2>/dev/null | head -n 1 || true)"
if [[ -z "${RAW_NO}" ]]; then
  echo "cannot locate raw report for no-mem run_id=${RUN_ID_NO}" >&2
  exit 2
fi
cp -f "${RAW_NO}" "${EVAL_DIR}/official_raw_no_mem.json"

NO_SUMMARY="${EVAL_DIR}/official_summary_no_mem.json"
"${PYTHON_BIN}" "${COMMON_DIR}/summarize_official_eval.py" \
  --report-json "${RAW_NO}" \
  --run-id "${RUN_ID_NO}" \
  --dataset "SWE-bench/SWE-bench test" \
  --scope "Lite First50 no-mem" \
  --summary-out "${NO_SUMMARY}"

echo "[4/6] official eval with-mem"
"${PYTHON_BIN}" -m swebench.harness.run_evaluation \
  --dataset_name SWE-bench/SWE-bench \
  --split test \
  --predictions_path "${WITH_MEM_PREDS}" \
  --max_workers "${MAX_WORKERS_EVAL}" \
  --timeout "${EVAL_TIMEOUT_SEC}" \
  --cache_level env \
  --clean false \
  --run_id "${RUN_ID_WITH}" \
  --instance_ids "${INSTANCE_IDS[@]}"

RAW_WITH="$(ls -1t "${WS_ROOT}"/*.${RUN_ID_WITH}.json 2>/dev/null | head -n 1 || true)"
if [[ -z "${RAW_WITH}" ]]; then
  echo "cannot locate raw report for with-mem run_id=${RUN_ID_WITH}" >&2
  exit 2
fi
cp -f "${RAW_WITH}" "${EVAL_DIR}/official_raw_with_mem.json"

WITH_SUMMARY="${EVAL_DIR}/official_summary_with_mem.json"
"${PYTHON_BIN}" "${COMMON_DIR}/summarize_official_eval.py" \
  --report-json "${RAW_WITH}" \
  --run-id "${RUN_ID_WITH}" \
  --dataset "SWE-bench/SWE-bench test" \
  --scope "Lite First50 with-mem" \
  --summary-out "${WITH_SUMMARY}"

echo "[5/6] build comparison json"
COMPARE_JSON="${EVAL_DIR}/official_comparison_with_vs_no_mem.json"
"${PYTHON_BIN}" "${COMMON_DIR}/compare_official_eval_reports.py" \
  --no-mem-report "${RAW_NO}" \
  --with-mem-report "${RAW_WITH}" \
  --instance-ids-json "${CACHE_FILE}" \
  --output "${COMPARE_JSON}"

echo "[6/6] generate markdown report"
REPORT_MD="${EVAL_DIR}/官方评测汇总报告.md"
"${PYTHON_BIN}" - <<'PY' "${NO_SUMMARY}" "${WITH_SUMMARY}" "${COMPARE_JSON}" "${REPORT_MD}" "${RUN_TAG}"
import json
import pathlib
import sys
from datetime import datetime

no = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
wm = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
cmpj = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))
out = pathlib.Path(sys.argv[4])
run_tag = sys.argv[5]

lines = []
lines.append(f"# 官方评测汇总报告（{run_tag}）")
lines.append("")
lines.append(f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}")
lines.append("- 数据集：SWE-bench/SWE-bench test（first 50）")
lines.append("")
lines.append("## 核心结果")
lines.append("")
lines.append("| 组别 | resolved | planned | solved_rate |")
lines.append("|---|---:|---:|---:|")
lines.append(f"| no-mem | {int(no.get('resolved_instances', 0))} | {int(no.get('planned_instances', 0))} | {float(no.get('solved_rate_on_planned', 0.0)):.4f} |")
lines.append(f"| with-mem | {int(wm.get('resolved_instances', 0))} | {int(wm.get('planned_instances', 0))} | {float(wm.get('solved_rate_on_planned', 0.0)):.4f} |")
lines.append("")
lines.append("## 对比差异")
lines.append("")
lines.append(f"- solved_rate 差值（with - no）：{float(cmpj.get('delta_solved_rate', 0.0)):.4f}")
lines.append(f"- with-mem 独有 resolved 数：{len(cmpj.get('only_with', []))}")
lines.append(f"- no-mem 独有 resolved 数：{len(cmpj.get('only_no', []))}")
lines.append(f"- 两组都 resolved 数：{len(cmpj.get('both_resolved', []))}")
lines.append("")
lines.append("## 文件索引")
lines.append("")
lines.append(f"- no-mem summary: `{sys.argv[1]}`")
lines.append(f"- with-mem summary: `{sys.argv[2]}`")
lines.append(f"- comparison json: `{sys.argv[3]}`")
lines.append("")

out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(str(out))
PY

echo "done"
echo "eval_dir=${EVAL_DIR}"
echo "report_md=${REPORT_MD}"
