#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
RUNS_ROOT="${RUNS_ROOT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase8}"
RUN_TAG="${RUN_TAG:-}"
RUN_ROOT="${RUN_ROOT:-}"

if [[ -z "${RUN_ROOT}" ]]; then
  if [[ -n "${RUN_TAG}" ]]; then
    RUN_ROOT="${RUNS_ROOT}/${RUN_TAG}"
  else
    RUN_ROOT="$(ls -1dt "${RUNS_ROOT}"/phase8_same_only_* 2>/dev/null | head -n 1 || true)"
  fi
fi

if [[ -z "${RUN_ROOT}" || ! -d "${RUN_ROOT}" ]]; then
  echo "unable to resolve RUN_ROOT under ${RUNS_ROOT}" >&2
  exit 2
fi

RUN_TAG="$(basename "${RUN_ROOT}")"
SANITIZED_TAG="${RUN_TAG//[^A-Za-z0-9_]/_}"
WITHMEM_SESSION="${WITHMEM_SESSION:-${SANITIZED_TAG}_withmem}"
NOMEM_SESSION="${NOMEM_SESSION:-${SANITIZED_TAG}_nomem_rerun}"

WITHMEM_GLOBAL_SLOTS="${WITHMEM_GLOBAL_SLOTS:-2}"
WITHMEM_LOCAL_SLOTS="${WITHMEM_LOCAL_SLOTS:-1}"
WITHMEM_MAX_ACTIVE_RUN_BATCHES="${WITHMEM_MAX_ACTIVE_RUN_BATCHES:-2}"
NOMEM_GLOBAL_SLOTS="${NOMEM_GLOBAL_SLOTS:-2}"
NOMEM_LOCAL_SLOTS="${NOMEM_LOCAL_SLOTS:-1}"

WITHMEM_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/resume_withmem_same_only_phase8.sh"
NOMEM_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/rerun_nomem_docker_failures_phase8.sh"

WITHMEM_LOG="${RUN_ROOT}/same_problem/with_mem/resume_withmem.tmux.log"
NOMEM_LOG="${RUN_ROOT}/same_problem/nomem/rerun_docker_failures_58/tmux.parallel.log"

mkdir -p "$(dirname "${WITHMEM_LOG}")" "$(dirname "${NOMEM_LOG}")"

cleanup_stale_slot_dir() {
  local dir="$1"
  [[ -d "${dir}" ]] || return 0
  local slot
  for slot in "${dir}"/slot_*; do
    [[ -d "${slot}" ]] || continue
    local pid_file="${slot}/pid"
    if [[ ! -f "${pid_file}" ]]; then
      rm -rf "${slot}"
      continue
    fi
    local pid
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
      rm -rf "${slot}"
    fi
  done
}

cleanup_stale_slot_dir "${RUN_ROOT}/resource_slots/same_global"
cleanup_stale_slot_dir "${RUN_ROOT}/resource_slots/same_with_mem"
cleanup_stale_slot_dir "${RUN_ROOT}/resource_slots/same_nomem_rerun"

if tmux has-session -t "${WITHMEM_SESSION}" 2>/dev/null; then
  tmux kill-session -t "${WITHMEM_SESSION}"
fi
if tmux has-session -t "${NOMEM_SESSION}" 2>/dev/null; then
  tmux kill-session -t "${NOMEM_SESSION}"
fi

tmux new-session -d -s "${WITHMEM_SESSION}" \
  "env RUN_ROOT='${RUN_ROOT}' RUN_TAG='${RUN_TAG}' MAX_ACTIVE_RUN_BATCHES='${WITHMEM_MAX_ACTIVE_RUN_BATCHES}' PHASE7_GLOBAL_HEAVY_SLOTS='${WITHMEM_GLOBAL_SLOTS}' PHASE7_HEAVY_SLOTS='${WITHMEM_LOCAL_SLOTS}' '${WITHMEM_SCRIPT}' >> '${WITHMEM_LOG}' 2>&1"

tmux new-session -d -s "${NOMEM_SESSION}" \
  "env RUN_ROOT='${RUN_ROOT}' RUN_TAG='${RUN_TAG}' PHASE7_GLOBAL_HEAVY_SLOTS='${NOMEM_GLOBAL_SLOTS}' PHASE7_HEAVY_SLOTS='${NOMEM_LOCAL_SLOTS}' '${NOMEM_SCRIPT}' >> '${NOMEM_LOG}' 2>&1"

cat <<EOF
run_root=${RUN_ROOT}
withmem_session=${WITHMEM_SESSION}
nomem_session=${NOMEM_SESSION}
withmem_log=${WITHMEM_LOG}
nomem_log=${NOMEM_LOG}
EOF
