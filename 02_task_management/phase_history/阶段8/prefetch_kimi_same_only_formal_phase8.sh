#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
PREPARE_SCRIPT="${PREPARE_SCRIPT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common/prepare_instance_environment.sh}"

RUN_ROOT="${RUN_ROOT:?RUN_ROOT is required}"
SAME_JSON="${SAME_JSON:-${RUN_ROOT}/same_instances.json}"
SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-lite}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
IMAGE_PULL_TIMEOUT_SEC="${IMAGE_PULL_TIMEOUT_SEC:-1800}"
ENV_FATAL_EXIT_CODE="${ENV_FATAL_EXIT_CODE:-86}"
PREPARE_RESUME_MODE="${PREPARE_RESUME_MODE:-1}"
HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}"

NOMEM_RUNTIME_PREWARM="${NOMEM_RUNTIME_PREWARM:-1}"
WITHMEM_RUNTIME_PREWARM="${WITHMEM_RUNTIME_PREWARM:-1}"
NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC="${NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC:-1800}"
WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC="${WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC:-1800}"
NOMEM_PYTHON_STANDALONE_DIR="${NOMEM_PYTHON_STANDALONE_DIR:-/root}"
WITHMEM_PYTHON_STANDALONE_DIR="${WITHMEM_PYTHON_STANDALONE_DIR:-/root}"

if [[ ! -f "${SAME_JSON}" ]]; then
  echo "same instance list not found: ${SAME_JSON}" >&2
  exit 2
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "python not found: ${PYTHON_BIN}" >&2
  exit 2
fi
if [[ ! -f "${PREPARE_SCRIPT}" ]]; then
  echo "prepare script not found: ${PREPARE_SCRIPT}" >&2
  exit 2
fi

NOMEM_LOG_DIR="${RUN_ROOT}/same_problem/nomem/logs"
WITHMEM_ROOT="${RUN_ROOT}/same_problem/with_mem"
PREPARED_ROOT="${RUN_ROOT}/orchestrator_state/prepared_env"
mkdir -p "${NOMEM_LOG_DIR}" "${WITHMEM_ROOT}" "${PREPARED_ROOT}/nomem" "${PREPARED_ROOT}/with_mem"

load_instance_ids() {
  "${PYTHON_BIN}" - <<'PY' "${SAME_JSON}"
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for iid in payload.get("instance_ids", []):
    print(iid)
PY
}

prepared_marker_path() {
  local branch="$1"
  local iid="$2"
  local safe_iid="${iid//\//_}"
  printf '%s/%s/%s.ok\n' "${PREPARED_ROOT}" "${branch}" "${safe_iid}"
}

write_prepared_marker() {
  local branch="$1"
  local iid="$2"
  local runtime_prewarm="$3"
  local log_file="$4"
  local image="$5"
  local marker
  marker="$(prepared_marker_path "${branch}" "${iid}")"
  cat >"${marker}" <<EOF
instance_id=${iid}
branch=${branch}
runtime_prewarm=${runtime_prewarm}
image=${image}
log_file=${log_file}
prepared_at=$(date -Is)
EOF
}

run_branch_prepare() {
  local branch="$1"
  local iid="$2"
  local runtime_prewarm="$3"
  local runtime_warmup_timeout="$4"
  local standalone_dir="$5"
  local log_file="$6"
  local marker image

  marker="$(prepared_marker_path "${branch}" "${iid}")"
  if [[ "${PREPARE_RESUME_MODE}" == "1" && -f "${marker}" ]]; then
    echo "[resume] branch=${branch} instance=${iid} marker exists"
    return 0
  fi

  echo "[prepare] branch=${branch} instance=${iid}"
  HF_HUB_OFFLINE="${HF_HUB_OFFLINE}" \
  HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE}" \
  env \
    INSTANCE_ID="${iid}" \
    LOG_FILE="${log_file}" \
    SWEBENCH_SUBSET="${SWEBENCH_SUBSET}" \
    SWEBENCH_SPLIT="${SWEBENCH_SPLIT}" \
    IMAGE_PULL_TIMEOUT_SEC="${IMAGE_PULL_TIMEOUT_SEC}" \
    RUNTIME_PREWARM="${runtime_prewarm}" \
    RUNTIME_WARMUP_TIMEOUT_SEC="${runtime_warmup_timeout}" \
    PYTHON_STANDALONE_DIR="${standalone_dir}" \
    ENV_FATAL_EXIT_CODE="${ENV_FATAL_EXIT_CODE}" \
    bash "${PREPARE_SCRIPT}"

  image="$(awk -F= '/^instance_image=/{print $2}' "${log_file}" | tail -n 1)"
  write_prepared_marker "${branch}" "${iid}" "${runtime_prewarm}" "${log_file}" "${image}"
}

mapfile -t SELECTED_IDS < <(load_instance_ids)
if [[ "${#SELECTED_IDS[@]}" -eq 0 ]]; then
  echo "same_instances.json contains no instance ids: ${SAME_JSON}" >&2
  exit 2
fi

echo "run_root=${RUN_ROOT}"
echo "same_json=${SAME_JSON}"
echo "instance_count=${#SELECTED_IDS[@]}"
echo "hf_hub_offline=${HF_HUB_OFFLINE}"
echo "hf_datasets_offline=${HF_DATASETS_OFFLINE}"

for iid in "${SELECTED_IDS[@]}"; do
  safe_iid="${iid//\//_}"
  run_branch_prepare \
    "nomem" \
    "${iid}" \
    "${NOMEM_RUNTIME_PREWARM}" \
    "${NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC}" \
    "${NOMEM_PYTHON_STANDALONE_DIR}" \
    "${NOMEM_LOG_DIR}/${safe_iid}.prepare.log"

  run_branch_prepare \
    "with_mem" \
    "${iid}" \
    "${WITHMEM_RUNTIME_PREWARM}" \
    "${WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC}" \
    "${WITHMEM_PYTHON_STANDALONE_DIR}" \
    "${WITHMEM_ROOT}/${safe_iid}.prepare.log"
done

echo "prefetch_complete=1"
echo "prepared_root=${PREPARED_ROOT}"
