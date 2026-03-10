#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# 多次尝试实验（no-mem）运行脚本
#
# 运行原理：
# 1) 先确定本次要跑的 instance 列表（支持按起止下标切片，或显式给 ID 列表）；
# 2) 对每个 instance 连续运行 N 次（默认 5 次），每次都是一次独立的 SWE-agent run-batch；
# 3) 每次尝试都记录：
#    - 完整运行日志（.log）
#    - 外部工具事件日志（.jsonl）
#    - 轨迹与官方输出目录（.traj 等）
# 4) no-mem 模式不挂载 AgentMem 持久化存储，作为对照组，用于对比“无记忆复用”行为；
# 5) 全部尝试结束后，汇总脚本聚合状态/成功率/步骤/成本等指标，便于与 with-mem 对比。
#
# 执行流程：
# A. 初始化路径与参数 -> B. 生成 instance 列表 -> C. 双层循环（instance x attempt）执行
# -> D. 收集日志/轨迹 -> E. 生成 summary JSON。
# -----------------------------------------------------------------------------
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
SWEAGENT_BIN="${SWEAGENT_BIN:-${SWE_AGENT_ROOT}/.venv/bin/sweagent}"
START_WITH_TOOLS="${START_WITH_TOOLS:-${WS_ROOT}/PDDL_work_mem/source_code/sweagent_external_tools/bin/start_with_external_tools.sh}"
COMMON_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/common"

EXP_DIR="${EXP_DIR:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/no_mem}"
OUTDIR="${OUTDIR:-${EXP_DIR}/outputs}"
LOG_DIR="${LOG_DIR:-${EXP_DIR}/logs/no_mem}"
CACHE_DIR="${CACHE_DIR:-${EXP_DIR}/cache}"
METRICS_DIR="${METRICS_DIR:-${EXP_DIR}/metrics}"
INSTANCE_LIST_FILE="${INSTANCE_LIST_FILE:-${CACHE_DIR}/instance_ids.json}"
SUMMARY_OUT="${SUMMARY_OUT:-${METRICS_DIR}/summary_multi_try_no_mem_20min.json}"

EXPERIMENT_ID="${EXPERIMENT_ID:-multi_try_no_mem_20min}"
SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-full}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
START_INDEX="${START_INDEX:-0}"
INSTANCE_COUNT="${INSTANCE_COUNT:-5}"
INSTANCE_IDS_CSV="${INSTANCE_IDS_CSV:-}"
REPEATS="${REPEATS:-5}"

MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/deepseek.yaml}"
NUM_WORKERS="${NUM_WORKERS:-1}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
ENV_VAR_PATH="${ENV_VAR_PATH:-${SWE_AGENT_ROOT}/.env}"
REDO_EXISTING="${REDO_EXISTING:-1}"
FAIL_FAST="${FAIL_FAST:-0}"
RESUME_MODE="${RESUME_MODE:-1}"

is_int() { [[ "$1" =~ ^[0-9]+$ ]]; }
to_bool_token() {
  local raw
  raw="$(echo "${1}" | tr '[:upper:]' '[:lower:]')"
  case "${raw}" in
    1|true|yes|on) echo "True" ;;
    *) echo "False" ;;
  esac
}

if ! is_int "${START_INDEX}" || ! is_int "${INSTANCE_COUNT}" || ! is_int "${REPEATS}"; then
  echo "START_INDEX/INSTANCE_COUNT/REPEATS must be integers" >&2
  exit 2
fi

mkdir -p "${OUTDIR}" "${LOG_DIR}" "${CACHE_DIR}" "${METRICS_DIR}"

build_instance_list() {
  "${SWE_AGENT_ROOT}/.venv/bin/python" - <<'PY' \
    "${INSTANCE_LIST_FILE}" "${INSTANCE_IDS_CSV}" "${SWEBENCH_SUBSET}" "${SWEBENCH_SPLIT}" "${START_INDEX}" "${INSTANCE_COUNT}"
import json
import pathlib
import sys
from sweagent.run.batch_instances import SWEBenchInstances

out_path = pathlib.Path(sys.argv[1])
ids_csv = sys.argv[2].strip()
subset = sys.argv[3]
split = sys.argv[4]
start = int(sys.argv[5])
count = int(sys.argv[6])

if ids_csv:
    ids = [x.strip() for x in ids_csv.split(",") if x.strip()]
else:
    stop = start + count
    instances = SWEBenchInstances(subset=subset, split=split, slice=f"{start}:{stop}").get_instance_configs()
    ids = [inst.problem_statement.id for inst in instances]

payload = {
    "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    "subset": subset,
    "split": split,
    "start_index": start,
    "instance_count_requested": count,
    "instance_ids": ids,
}
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"instance_ids={len(ids)} -> {out_path}")
PY
}

read_instance_ids() {
  "${SWE_AGENT_ROOT}/.venv/bin/python" - <<'PY' "${INSTANCE_LIST_FILE}"
import json
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
for iid in data.get("instance_ids", []):
    print(iid)
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

build_instance_list
mapfile -t INSTANCE_IDS < <(read_instance_ids)
if [[ "${#INSTANCE_IDS[@]}" -eq 0 ]]; then
  echo "No instance ids selected. Abort." >&2
  exit 1
fi

echo "Selected ${#INSTANCE_IDS[@]} instances, repeats=${REPEATS}, timeout=${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}s"

for iid in "${INSTANCE_IDS[@]}"; do
  safe_iid="${iid//\//_}"
  instance_log_dir="${LOG_DIR}/${safe_iid}"
  instance_out_root="${OUTDIR}/${iid}"
  mkdir -p "${instance_log_dir}" "${instance_out_root}"

  echo "==== Instance: ${iid} ===="
  for attempt in $(seq 1 "${REPEATS}"); do
    attempt_tag="$(printf "%02d" "${attempt}")"
    attempt_outdir="${instance_out_root}/attempt_${attempt_tag}"
    attempt_event_log="${instance_log_dir}/attempt_${attempt_tag}.jsonl"
    attempt_run_log="${instance_log_dir}/attempt_${attempt_tag}.log"
    mkdir -p "${attempt_outdir}"

    if [[ "$(to_bool_token "${RESUME_MODE}")" == "True" ]]; then
      if attempt_is_complete "${iid}" "${attempt_outdir}"; then
        echo "[${iid}] attempt=${attempt}/${REPEATS} skip (already complete: ${attempt_outdir})"
        continue
      fi
    fi

    export SWE_AGENT_EXT_TOOLS_LOG_FILE="${attempt_event_log}"

    echo "[${iid}] attempt=${attempt}/${REPEATS} out=${attempt_outdir}"

    set +e
    "${START_WITH_TOOLS}" --mode no-mem \
      "${SWEAGENT_BIN}" run-batch \
      --config "${MODEL_CONFIG}" \
      --instances.type swe_bench \
      --instances.subset "${SWEBENCH_SUBSET}" \
      --instances.split "${SWEBENCH_SPLIT}" \
      --instances.filter "^${iid}$" \
      --output_dir "${attempt_outdir}" \
      --num_workers "${NUM_WORKERS}" \
      --env_var_path "${ENV_VAR_PATH}" \
      --agent.model.per_instance_call_limit "${PER_INSTANCE_CALL_LIMIT}" \
      --agent.tools.total_execution_timeout "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
      --redo_existing "$(to_bool_token "${REDO_EXISTING}")" \
      2>&1 | tee -a "${attempt_run_log}"
    rc=$?
    set -e

    if [[ "${rc}" -ne 0 ]]; then
      echo "[${iid}] attempt=${attempt} failed rc=${rc}" | tee -a "${attempt_run_log}"
      if [[ "$(to_bool_token "${FAIL_FAST}")" == "True" ]]; then
        exit "${rc}"
      fi
    fi
  done
done

"${SWE_AGENT_ROOT}/.venv/bin/python" "${COMMON_DIR}/collect_multi_try_summary.py" \
  --experiment-id "${EXPERIMENT_ID}" \
  --mode "no-mem" \
  --workspace-root "${WS_ROOT}" \
  --output-root "${OUTDIR}" \
  --instance-list-file "${INSTANCE_LIST_FILE}" \
  --repeats "${REPEATS}" \
  --event-log-root "${LOG_DIR}" \
  --summary-out "${SUMMARY_OUT}"

echo "Done: ${SUMMARY_OUT}"
