#!/usr/bin/env bash
# 阶段9-v2c：修复 Gate 无限循环（Fix 6）+ apply_feedback 使用 v2 模块（Fix 5）
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
PHASE9_DIR="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段9"
V2_FW_REAL="${PHASE9_DIR}/sweagent_external_tools_v2_2026-04-25"
V2_FW_LINK="${WS_ROOT}/PDDL_work_mem/sweagent_external_tools_v2"
ln -sfn "${V2_FW_REAL}" "${V2_FW_LINK}"

RUN_TAG="${RUN_TAG:-phase9_v2c_kimi_full_12057_withmem_$(date +%Y%m%d_%H%M%S)}"
RUNS_ROOT="${RUNS_ROOT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase9_v2}"
RUN_ROOT="${RUNS_ROOT}/${RUN_TAG}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_moonshot.yaml}"
PROMPT_PROFILE="${PROMPT_PROFILE:-prompt_base}"
REPEATS="${REPEATS:-10}"
export SWEBENCH_SUBSET="full"
export SWEBENCH_SPLIT="test"

mkdir -p "${RUN_ROOT}/orchestrator_logs" "${RUN_ROOT}/orchestrator_state" "${RUN_ROOT}/notes" "${RUN_ROOT}/agent_mem_logs"

INSTANCE_LIST_JSON="${RUN_ROOT}/same_instances.json"
cat > "${INSTANCE_LIST_JSON}" <<JSON
{
  "generated_at": "$(date -Iseconds)",
  "subset": "full",
  "split": "test",
  "selection_mode": "manual_phase9_v2c_single",
  "case_start_1based": 2,
  "case_end_1based": 2,
  "count_requested": 1,
  "count_selected": 1,
  "total_available": 2294,
  "repeats": ${REPEATS},
  "instance_ids": ["astropy__astropy-12057"]
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
  "experiment_type": "phase9_v2c_withmem_only",
  "run_root": "${RUN_ROOT}",
  "framework_version": "phase9_v2c_2026-04-27_with_6_fixes",
  "fixes_applied": [
    "fix1_env_propagation_via_config_file",
    "fix2_scheduler_defer_and_redecide",
    "fix3_gate_pre_submit_diff_inspection",
    "fix4_feedback_consumer_calls_adjust_card",
    "fix5_apply_feedback_uses_v2_modules",
    "fix6_gate_pending_pass_breaks_infinite_loop"
  ],
  "comparison_axis": "v2c (6 bugs fixed) with_mem only on astropy-12057, 10 attempts"
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

export GLOBAL_HEAVY_SLOTS="2"
export WITHMEM_HEAVY_SLOTS="1"
export MAX_ACTIVE_RUN_BATCHES="1"
export PER_INSTANCE_CALL_LIMIT="0"
export WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="1200"
export MAX_WORKERS_EVAL="1"
export EVAL_TIMEOUT_SEC="1200"
export ENV_ERROR_RETRIES="1"
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

GLOBAL_HEAVY_SLOT_DIR="${RUN_ROOT}/resource_slots/same_global"
WITHMEM_HEAVY_SLOT_DIR="${RUN_ROOT}/resource_slots/same_with_mem"
mkdir -p "${GLOBAL_HEAVY_SLOT_DIR}" "${WITHMEM_HEAVY_SLOT_DIR}"
export SWE_AGENT_EXT_TOOLS_LOG_FILE="${RUN_ROOT}/agent_mem_logs/hook_events.jsonl"

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
           PHASE7_PREPARE_SLOTS WITHMEM_RUNTIME_PREWARM WITHMEM_PYTHON_STANDALONE_DIR \
           HF_HUB_OFFLINE HF_DATASETS_OFFLINE; do
    echo "${v}='${!v:-}'"
  done
} > "${MAIN_ENV_FILE}"

SANITIZED_TAG="${RUN_TAG//[^A-Za-z0-9_]/_}"
MAIN_SESSION="${SANITIZED_TAG}_v2c"
MAIN_LOG="${RUN_ROOT}/orchestrator_logs/withmem_only.tmux.log"

if tmux has-session -t "${MAIN_SESSION}" 2>/dev/null; then
  echo "tmux session already running: ${MAIN_SESSION}" >&2; exit 3
fi

tmux new-session -d -s "${MAIN_SESSION}" "
set -a; source '${SWE_AGENT_ENV_FILE}'; source '${MAIN_ENV_FILE}'; set +a
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
=== Phase 9-v2c launch summary (with_mem only, single case) ===
run_root        = ${RUN_ROOT}
case            = astropy__astropy-12057  (10 attempts)
framework       = ${V2_FW_REAL}  [v2c · 6 bugs fixed]
fixes           = +fix5(apply_feedback→v2) +fix6(gate_pending_pass)
tmux_session    = ${MAIN_SESSION}
main_log        = ${MAIN_LOG}
EOF
