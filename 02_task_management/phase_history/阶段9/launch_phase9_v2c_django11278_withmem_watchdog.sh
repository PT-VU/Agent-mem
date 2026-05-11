#!/usr/bin/env bash
# Phase 9-v2c: django__django-11278, with_mem only, 10 attempts
# New: watchdog overhead-aware timer (bridge-hook time excluded from budget)
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
PHASE9_DIR="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段9"
V2_FW_REAL="${PHASE9_DIR}/sweagent_external_tools_v2_2026-04-25"
V2_FW_LINK="${WS_ROOT}/PDDL_work_mem/sweagent_external_tools_v2"
ln -sfn "${V2_FW_REAL}" "${V2_FW_LINK}"

RUN_TAG="${RUN_TAG:-phase9_v2c_django11278_wm_watchdog_$(date +%Y%m%d_%H%M%S)}"
RUNS_ROOT="${RUNS_ROOT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase9_v2}"
RUN_ROOT="${RUNS_ROOT}/${RUN_TAG}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_moonshot.yaml}"
PROMPT_PROFILE="${PROMPT_PROFILE:-prompt_base}"
REPEATS="${REPEATS:-10}"
export SWEBENCH_SUBSET="full"
export SWEBENCH_SPLIT="test"

mkdir -p "${RUN_ROOT}/orchestrator_logs" "${RUN_ROOT}/orchestrator_state" \
          "${RUN_ROOT}/notes" "${RUN_ROOT}/agent_mem_logs"

INSTANCE_LIST_JSON="${RUN_ROOT}/same_instances.json"
cat > "${INSTANCE_LIST_JSON}" <<JSON
{
  "generated_at": "$(date -Iseconds)",
  "subset": "full",
  "split": "test",
  "selection_mode": "manual_phase9_v2c_django11278_watchdog",
  "count_selected": 1,
  "repeats": ${REPEATS},
  "instance_ids": ["django__django-11278"]
}
JSON

cat > "${RUN_ROOT}/agent_mem_logs/v2_config.json" <<'JSON'
{
  "AGENT_MEM_BUG_INVARIANT_VERBATIM": "1",
  "AGENT_MEM_BUG_ANTI_PATTERN": "1",
  "AGENT_MEM_PATCH_CONSISTENCY_GATE": "enforce",
  "AGENT_MEM_REUSE_EXPLORE": "auto",
  "AGENT_MEM_LOCAL_EFFECTIVE_FEEDBACK": "1",
  "AGENT_MEM_L3_FORCE_SUBMIT": "dry_run",
  "AGENT_MEM_FORCE_STRATEGY": "auto"
}
JSON

cat > "${RUN_ROOT}/orchestrator_state/run_manifest.json" <<JSON
{
  "generated_at": "$(date -Iseconds)",
  "experiment_type": "phase9_v2c_django11278_withmem_watchdog",
  "run_root": "${RUN_ROOT}",
  "framework_version": "phase9_v2c_6fixes_watchdog",
  "change": "watchdog overhead-aware timer: bridge-hook time excluded from 1200s budget",
  "comparison": "nomem results from phase9_v2c_expand4_20260429_075835 (2R 1U 7I)"
}
JSON

SWE_AGENT_ENV_FILE="${WS_ROOT}/SWE-agent/.env"
if [[ -f "${SWE_AGENT_ENV_FILE}" ]]; then set -a; source "${SWE_AGENT_ENV_FILE}"; set +a; fi
if [[ -z "${MOONSHOT_API_KEY:-}" ]]; then echo "MOONSHOT_API_KEY required" >&2; exit 2; fi

export START_WITH_TOOLS="${V2_FW_LINK}/bin/start_with_external_tools.sh"
export V2_FW_DIR="${V2_FW_LINK}"
export SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH="${WS_ROOT}/PDDL_work_mem"
export SWE_AGENT_EXTERNAL_HOOK_CLASS="sweagent_external_tools_v2.bridge_hook:ExternalToolBridgeHook"
export SWE_AGENT_EXT_TOOL_A_CMD="${V2_FW_LINK}/bin/run_tool_a.sh"
export SWE_AGENT_EXT_TOOL_B_CMD="${V2_FW_LINK}/bin/run_tool_b.sh"
export AGENT_MEM_V2_CONFIG_FILE="${RUN_ROOT}/agent_mem_logs/v2_config.json"
export RUN_ROOT

export AGENT_MEM_BUG_INVARIANT_VERBATIM="1"
export AGENT_MEM_BUG_ANTI_PATTERN="1"
export AGENT_MEM_PATCH_CONSISTENCY_GATE="enforce"
export AGENT_MEM_REUSE_EXPLORE="auto"
export AGENT_MEM_LOCAL_EFFECTIVE_FEEDBACK="1"
export AGENT_MEM_L3_FORCE_SUBMIT="dry_run"
export AGENT_MEM_FORCE_STRATEGY="auto"

export GLOBAL_HEAVY_SLOTS="1"
export WITHMEM_HEAVY_SLOTS="1"
export MAX_ACTIVE_RUN_BATCHES="1"
export PER_INSTANCE_CALL_LIMIT="0"
# Same 1200s budget as before — but now bridge-hook overhead is excluded by watchdog
export WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="1200"
export MAX_WORKERS_EVAL="1"
export EVAL_TIMEOUT_SEC="1200"
export ENV_ERROR_RETRIES="5"
export ENV_RETRY_WAIT_SEC="30"
export ENV_FATAL_EXIT_CODE="86"
export IMAGE_PULL_TIMEOUT_SEC="1800"
export PHASE7_PREPARE_SLOTS="1"
export PHASE7_PREPARE_SLOT_POLL_SEC="10"
export WITHMEM_RUNTIME_PREWARM="1"
export WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC="1800"
export WITHMEM_PYTHON_STANDALONE_DIR="/root"
export SKIP_INSTANCE_PREPARE="0"
export HF_HUB_OFFLINE="1"
export HF_DATASETS_OFFLINE="1"
export RESUME_MODE="1"
export REDO_EXISTING="0"
export DRY_RUN="0"
export SWE_AGENT_EXT_TOOLS_LOG_FILE="${RUN_ROOT}/agent_mem_logs/hook_events.jsonl"
# Watchdog path (also defaults in run_lite script, explicit here for clarity)
export WATCHDOG_PY="${V2_FW_LINK}/bin/watchdog.py"

GLOBAL_HEAVY_SLOT_DIR="${RUN_ROOT}/resource_slots/same_global"
WITHMEM_HEAVY_SLOT_DIR="${RUN_ROOT}/resource_slots/same_with_mem"
mkdir -p "${GLOBAL_HEAVY_SLOT_DIR}" "${WITHMEM_HEAVY_SLOT_DIR}"

WITHMEM_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段7/最终验证测验/run_same_problem_v21_phase7.sh"

MAIN_ENV_FILE="${RUN_ROOT}/orchestrator_state/main_tmux.env"
{
  for v in RUN_ROOT RUN_TAG MODEL_CONFIG PROMPT_PROFILE REPEATS SWEBENCH_SUBSET SWEBENCH_SPLIT \
           START_WITH_TOOLS V2_FW_DIR SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH SWE_AGENT_EXTERNAL_HOOK_CLASS \
           SWE_AGENT_EXT_TOOL_A_CMD SWE_AGENT_EXT_TOOL_B_CMD SWE_AGENT_EXT_TOOLS_LOG_FILE \
           AGENT_MEM_V2_CONFIG_FILE AGENT_MEM_BUG_INVARIANT_VERBATIM AGENT_MEM_BUG_ANTI_PATTERN \
           AGENT_MEM_PATCH_CONSISTENCY_GATE AGENT_MEM_REUSE_EXPLORE AGENT_MEM_LOCAL_EFFECTIVE_FEEDBACK \
           AGENT_MEM_L3_FORCE_SUBMIT AGENT_MEM_FORCE_STRATEGY \
           WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC EVAL_TIMEOUT_SEC IMAGE_PULL_TIMEOUT_SEC \
           ENV_ERROR_RETRIES ENV_RETRY_WAIT_SEC \
           PHASE7_PREPARE_SLOTS WITHMEM_RUNTIME_PREWARM WITHMEM_PYTHON_STANDALONE_DIR \
           HF_HUB_OFFLINE HF_DATASETS_OFFLINE WATCHDOG_PY; do
    echo "${v}='${!v:-}'"
  done
} > "${MAIN_ENV_FILE}"

SANITIZED_TAG="${RUN_TAG//[^A-Za-z0-9_]/_}"
MAIN_SESSION="${SANITIZED_TAG}_wm"
MAIN_LOG="${RUN_ROOT}/orchestrator_logs/withmem_only.tmux.log"

if tmux has-session -t "${MAIN_SESSION}" 2>/dev/null; then
  echo "tmux session already running: ${MAIN_SESSION}" >&2; exit 3
fi

tmux new-session -d -s "${MAIN_SESSION}" "
set -a
source '${SWE_AGENT_ENV_FILE}'
source '${MAIN_ENV_FILE}'
set +a
export INSTANCE_LIST_JSON='${INSTANCE_LIST_JSON}'
export PHASE7_GLOBAL_HEAVY_SLOT_DIR='${GLOBAL_HEAVY_SLOT_DIR}'
export PHASE7_GLOBAL_HEAVY_SLOTS='${GLOBAL_HEAVY_SLOTS}'
export PHASE7_GLOBAL_HEAVY_SLOT_POLL_SEC='10'
export PHASE7_HEAVY_SLOT_DIR='${WITHMEM_HEAVY_SLOT_DIR}'
export PHASE7_HEAVY_SLOTS='${WITHMEM_HEAVY_SLOTS}'
export PHASE7_HEAVY_SLOT_POLL_SEC='10'
export INSTANCE_TOTAL_EXEC_TIMEOUT_SEC='${WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}'
'${WITHMEM_SCRIPT}' >> '${MAIN_LOG}' 2>&1
echo \$? > '${RUN_ROOT}/orchestrator_state/withmem_only.exit'
"

cat <<EOF
=== Phase 9-v2c django-11278 with_mem watchdog launch ===
run_root      = ${RUN_ROOT}
case          = django__django-11278  (${REPEATS} attempts)
framework     = ${V2_FW_REAL}  [v2c + watchdog overhead timer]
budget        = ${WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}s  (bridge-hook time excluded)
tmux_session  = ${MAIN_SESSION}
main_log      = ${MAIN_LOG}

Compare against:
  nomem baseline  phase9_v2c_expand4_20260429_075835  →  2R 1U 7I / 10
EOF
