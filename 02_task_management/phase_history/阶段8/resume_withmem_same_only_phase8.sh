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

SAME_JSON="${SAME_JSON:-${RUN_ROOT}/same_instances.json}"
if [[ ! -f "${SAME_JSON}" ]]; then
  echo "same instance list not found: ${SAME_JSON}" >&2
  exit 2
fi

REPEATS="${REPEATS:-10}"
PROMPT_PROFILE="${PROMPT_PROFILE:-prompt_base}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_siliconflow.yaml}"
RESUME_MODE="${RESUME_MODE:-1}"
REDO_EXISTING="${REDO_EXISTING:-0}"
MAX_ACTIVE_RUN_BATCHES="${MAX_ACTIVE_RUN_BATCHES:-2}"
PHASE7_GLOBAL_HEAVY_SLOT_DIR="${PHASE7_GLOBAL_HEAVY_SLOT_DIR:-${RUN_ROOT}/resource_slots/same_global}"
PHASE7_GLOBAL_HEAVY_SLOTS="${PHASE7_GLOBAL_HEAVY_SLOTS:-2}"
PHASE7_HEAVY_SLOT_DIR="${PHASE7_HEAVY_SLOT_DIR:-${RUN_ROOT}/resource_slots/same_with_mem}"
PHASE7_HEAVY_SLOTS="${PHASE7_HEAVY_SLOTS:-1}"

export RUN_ROOT INSTANCE_LIST_JSON="${SAME_JSON}" REPEATS PROMPT_PROFILE MODEL_CONFIG
export RESUME_MODE REDO_EXISTING MAX_ACTIVE_RUN_BATCHES
export PHASE7_GLOBAL_HEAVY_SLOT_DIR PHASE7_GLOBAL_HEAVY_SLOTS
export PHASE7_HEAVY_SLOT_DIR PHASE7_HEAVY_SLOTS

exec "${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段7/最终验证测验/run_same_problem_v21_phase7.sh"
