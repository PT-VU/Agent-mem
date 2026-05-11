#!/usr/bin/env bash
# 阶段9-v2 升级框架的实验启动脚本
# 复用 phase8 同结构 orchestrator，仅做三项替换：
#   1) RUN_ROOT / RUN_TAG 改到 phase9_v2 命名空间
#   2) 把 SWE_AGENT_EXTERNAL_HOOK_* / SWE_AGENT_EXT_TOOL_*_CMD 指向 v2 框架副本
#   3) 默认开启 5 个 v2 模块的环境变量
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
PHASE9_DIR="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段9"

# ---- v2 框架副本路径（symlink 提供 Python-importable 名字）----
V2_FW_REAL="${PHASE9_DIR}/sweagent_external_tools_v2_2026-04-25"
V2_FW_LINK="${WS_ROOT}/PDDL_work_mem/sweagent_external_tools_v2"
if [[ ! -d "${V2_FW_REAL}" ]]; then
  echo "v2 framework not found: ${V2_FW_REAL}" >&2
  exit 2
fi
ln -sfn "${V2_FW_REAL}" "${V2_FW_LINK}"

# ---- 实验参数 ----
RUN_TAG="${RUN_TAG:-phase9_v2_moonshot_kimi_full_12057_11693_$(date +%Y%m%d_%H%M%S)}"
RUNS_ROOT="${RUNS_ROOT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase9_v2}"
RUN_ROOT="${RUNS_ROOT}/${RUN_TAG}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_moonshot.yaml}"
PROMPT_PROFILE="${PROMPT_PROFILE:-prompt_base}"
REPEATS="${REPEATS:-10}"
SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-full}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"

mkdir -p "${RUN_ROOT}/orchestrator_logs" "${RUN_ROOT}/orchestrator_state" "${RUN_ROOT}/notes"

# ---- 写 same_instances.json：我们直接固定 2 个实例 ----
INSTANCE_LIST_JSON="${RUN_ROOT}/same_instances.json"
if [[ ! -f "${INSTANCE_LIST_JSON}" ]]; then
  cat > "${INSTANCE_LIST_JSON}" <<JSON
{
  "generated_at": "$(date -Iseconds)",
  "subset": "full",
  "split": "test",
  "selection_mode": "manual_phase9_v2",
  "case_start_1based": 1,
  "case_end_1based": 2,
  "count_requested": 2,
  "count_selected": 2,
  "total_available": 2294,
  "repeats": 10,
  "instance_ids": [
    "astropy__astropy-11693",
    "astropy__astropy-12057"
  ]
}
JSON
fi

# ---- 写 run_manifest.json ----
MANIFEST="${RUN_ROOT}/orchestrator_state/run_manifest.json"
if [[ ! -f "${MANIFEST}" ]]; then
  cat > "${MANIFEST}" <<JSON
{
  "generated_at": "$(date -Iseconds)",
  "experiment_type": "phase9_v2_same_only_kimi_formal",
  "run_root": "${RUN_ROOT}",
  "same_instances_json": "${INSTANCE_LIST_JSON}",
  "model_config": "${MODEL_CONFIG}",
  "prompt_profile": "${PROMPT_PROFILE}",
  "repeats": ${REPEATS},
  "groups": ["nomem", "with_mem"],
  "framework_version": "phase9_v2_2026-04-25",
  "framework_path": "${V2_FW_REAL}",
  "framework_symlink": "${V2_FW_LINK}",
  "comparison_axis": "phase9-v2 framework on SWE-bench full test, 2 instances (astropy 11693 + 12057), 10 attempts each, NoMem vs WithMem, Kimi"
}
JSON
fi

# ---- 加载 .env（API key）----
SWE_AGENT_ENV_FILE="${WS_ROOT}/SWE-agent/.env"
if [[ -f "${SWE_AGENT_ENV_FILE}" ]]; then
  set -a; source "${SWE_AGENT_ENV_FILE}"; set +a
fi
if [[ -z "${MOONSHOT_API_KEY:-}" ]]; then
  echo "MOONSHOT_API_KEY required" >&2; exit 2
fi

# ============================================================
# 关键：把 hook 指向 v2 框架副本（START_WITH_TOOLS 也需要切到 v2 的 wrapper，
# 因为下游 runner 的默认值仍指向 source_code/ 下的 v1 wrapper）
# ============================================================
export START_WITH_TOOLS="${V2_FW_LINK}/bin/start_with_external_tools.sh"
export V2_FW_DIR="${V2_FW_LINK}"
# 这些 env 通过 v2 wrapper 内部的 ${VAR:-default} 承接生效
export SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH="${WS_ROOT}/PDDL_work_mem"
export SWE_AGENT_EXTERNAL_HOOK_CLASS="sweagent_external_tools_v2.bridge_hook:ExternalToolBridgeHook"
export SWE_AGENT_EXT_TOOL_A_CMD="${V2_FW_LINK}/bin/run_tool_a.sh"
export SWE_AGENT_EXT_TOOL_B_CMD="${V2_FW_LINK}/bin/run_tool_b.sh"

# ============================================================
# 行动日志保留：把 HOOK 事件 JSONL 钉到 RUN_ROOT 下
# 每条记录都带 instance_id/attempt_id，可后期按 attempt 切分
# 默认值是 /tmp 下单一共享文件，会被覆盖且非永久存储
# ============================================================
mkdir -p "${RUN_ROOT}/agent_mem_logs"
export SWE_AGENT_EXT_TOOLS_LOG_FILE="${RUN_ROOT}/agent_mem_logs/hook_events.jsonl"

# ============================================================
# v2 模块开关（按方案 §6.1 推荐：先开 A/B/Gate=enforce/Reuse/Feedback，L3 走 dry_run）
# 可以通过外部环境变量覆盖每一项。
# ============================================================
export AGENT_MEM_BUG_INVARIANT_VERBATIM="${AGENT_MEM_BUG_INVARIANT_VERBATIM:-1}"
export AGENT_MEM_BUG_ANTI_PATTERN="${AGENT_MEM_BUG_ANTI_PATTERN:-1}"
export AGENT_MEM_PATCH_CONSISTENCY_GATE="${AGENT_MEM_PATCH_CONSISTENCY_GATE:-enforce}"
export AGENT_MEM_REUSE_EXPLORE="${AGENT_MEM_REUSE_EXPLORE:-auto}"
export AGENT_MEM_LOCAL_EFFECTIVE_FEEDBACK="${AGENT_MEM_LOCAL_EFFECTIVE_FEEDBACK:-1}"
# L3 dry_run：先观察日志事件而不真改写动作；确认无误后可改 enforce
export AGENT_MEM_L3_FORCE_SUBMIT="${AGENT_MEM_L3_FORCE_SUBMIT:-dry_run}"
export AGENT_MEM_FORCE_STRATEGY="${AGENT_MEM_FORCE_STRATEGY:-auto}"

# ---- 资源 / 超时（沿用 phase 8 配置） ----
export GLOBAL_HEAVY_SLOTS="${GLOBAL_HEAVY_SLOTS:-2}"
export NOMEM_HEAVY_SLOTS="${NOMEM_HEAVY_SLOTS:-1}"
export WITHMEM_HEAVY_SLOTS="${WITHMEM_HEAVY_SLOTS:-1}"
export MAX_ACTIVE_RUN_BATCHES="${MAX_ACTIVE_RUN_BATCHES:-2}"
export PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
export NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
export WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-1200}"
export MAX_WORKERS_EVAL="${MAX_WORKERS_EVAL:-1}"
export EVAL_TIMEOUT_SEC="${EVAL_TIMEOUT_SEC:-1200}"
export ENV_ERROR_RETRIES="${ENV_ERROR_RETRIES:-1}"
export IMAGE_PULL_TIMEOUT_SEC="${IMAGE_PULL_TIMEOUT_SEC:-1800}"
export PHASE7_PREPARE_SLOTS="${PHASE7_PREPARE_SLOTS:-2}"
export PHASE7_PREPARE_SLOT_POLL_SEC="${PHASE7_PREPARE_SLOT_POLL_SEC:-10}"
export NOMEM_RUNTIME_PREWARM="${NOMEM_RUNTIME_PREWARM:-0}"
export WITHMEM_RUNTIME_PREWARM="${WITHMEM_RUNTIME_PREWARM:-1}"
export NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC="${NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC:-1800}"
export WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC="${WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC:-1800}"
export NOMEM_PYTHON_STANDALONE_DIR="${NOMEM_PYTHON_STANDALONE_DIR:-/root}"
export WITHMEM_PYTHON_STANDALONE_DIR="${WITHMEM_PYTHON_STANDALONE_DIR:-/root}"
export SKIP_INSTANCE_PREPARE="${SKIP_INSTANCE_PREPARE:-0}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export HF_DATASETS_OFFLINE="${HF_DATASETS_OFFLINE:-1}"

# 把 RUN_ROOT 等基础变量也导出，phase8 resume 脚本会读
export RUN_ROOT
export RUN_TAG
export MODEL_CONFIG
export PROMPT_PROFILE
export REPEATS
export SWEBENCH_SUBSET
export SWEBENCH_SPLIT
export SAME_JSON="${INSTANCE_LIST_JSON}"

# ---- tmux 会话 ----
RESUME_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/resume_same_only_phase8.sh"
INVENTORY_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/collect_same_only_trial_inventory.py"
PYTHON_BIN="${WS_ROOT}/SWE-agent/.venv/bin/python"

SANITIZED_TAG="${RUN_TAG//[^A-Za-z0-9_]/_}"
MAIN_SESSION="${MAIN_SESSION:-${SANITIZED_TAG}_v2}"
INDEX_SESSION="${INDEX_SESSION:-${SANITIZED_TAG}_idx}"
MAIN_LOG="${RUN_ROOT}/orchestrator_logs/same_only_resume.tmux.log"
INDEX_LOG="${RUN_ROOT}/orchestrator_logs/trial_indexer.tmux.log"

if tmux has-session -t "${MAIN_SESSION}" 2>/dev/null; then
  echo "main tmux session already running: ${MAIN_SESSION}" >&2; exit 3
fi

# 把所有 v2 + 配置 env 写到 main_tmux.env，便于诊断
MAIN_ENV_FILE="${RUN_ROOT}/orchestrator_state/main_tmux.env"
{
  echo "RUN_ROOT='${RUN_ROOT}'"
  echo "RUN_TAG='${RUN_TAG}'"
  echo "MODEL_CONFIG='${MODEL_CONFIG}'"
  echo "PROMPT_PROFILE='${PROMPT_PROFILE}'"
  echo "REPEATS='${REPEATS}'"
  echo "SWEBENCH_SUBSET='${SWEBENCH_SUBSET}'"
  echo "SWEBENCH_SPLIT='${SWEBENCH_SPLIT}'"
  for v in GLOBAL_HEAVY_SLOTS NOMEM_HEAVY_SLOTS WITHMEM_HEAVY_SLOTS MAX_ACTIVE_RUN_BATCHES PER_INSTANCE_CALL_LIMIT \
           NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC MAX_WORKERS_EVAL EVAL_TIMEOUT_SEC \
           ENV_ERROR_RETRIES IMAGE_PULL_TIMEOUT_SEC PHASE7_PREPARE_SLOTS PHASE7_PREPARE_SLOT_POLL_SEC \
           NOMEM_RUNTIME_PREWARM WITHMEM_RUNTIME_PREWARM NOMEM_RUNTIME_WARMUP_TIMEOUT_SEC WITHMEM_RUNTIME_WARMUP_TIMEOUT_SEC \
           NOMEM_PYTHON_STANDALONE_DIR WITHMEM_PYTHON_STANDALONE_DIR SKIP_INSTANCE_PREPARE HF_HUB_OFFLINE HF_DATASETS_OFFLINE \
           SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH SWE_AGENT_EXTERNAL_HOOK_CLASS SWE_AGENT_EXT_TOOL_A_CMD SWE_AGENT_EXT_TOOL_B_CMD \
           SWE_AGENT_EXT_TOOLS_LOG_FILE START_WITH_TOOLS V2_FW_DIR \
           AGENT_MEM_BUG_INVARIANT_VERBATIM AGENT_MEM_BUG_ANTI_PATTERN AGENT_MEM_PATCH_CONSISTENCY_GATE \
           AGENT_MEM_REUSE_EXPLORE AGENT_MEM_LOCAL_EFFECTIVE_FEEDBACK AGENT_MEM_L3_FORCE_SUBMIT AGENT_MEM_FORCE_STRATEGY; do
    echo "${v}='${!v:-}'"
  done
} > "${MAIN_ENV_FILE}"

tmux new-session -d -s "${MAIN_SESSION}" \
  "set -a; source '${SWE_AGENT_ENV_FILE}'; source '${MAIN_ENV_FILE}'; set +a; '${RESUME_SCRIPT}' >> '${MAIN_LOG}' 2>&1"

tmux new-session -d -s "${INDEX_SESSION}" \
  "while tmux has-session -t '${MAIN_SESSION}' 2>/dev/null; do '${PYTHON_BIN}' '${INVENTORY_SCRIPT}' --run-root '${RUN_ROOT}' >> '${INDEX_LOG}' 2>&1; sleep 30; done; '${PYTHON_BIN}' '${INVENTORY_SCRIPT}' --run-root '${RUN_ROOT}' >> '${INDEX_LOG}' 2>&1"

cat <<EOF
=== Phase 9-v2 launch summary ===
run_root        = ${RUN_ROOT}
same_json       = ${INSTANCE_LIST_JSON}
framework       = ${V2_FW_REAL}
hook_class      = ${SWE_AGENT_EXTERNAL_HOOK_CLASS}
hook_pythonpath = ${SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH}
v2_flags        = INVARIANT=${AGENT_MEM_BUG_INVARIANT_VERBATIM} ANTI=${AGENT_MEM_BUG_ANTI_PATTERN} GATE=${AGENT_MEM_PATCH_CONSISTENCY_GATE} REUSE=${AGENT_MEM_REUSE_EXPLORE} FEEDBACK=${AGENT_MEM_LOCAL_EFFECTIVE_FEEDBACK} L3=${AGENT_MEM_L3_FORCE_SUBMIT}
main_session    = ${MAIN_SESSION}
index_session   = ${INDEX_SESSION}
main_log        = ${MAIN_LOG}
index_log       = ${INDEX_LOG}
trial_inventory = ${RUN_ROOT}/orchestrator_state/trial_inventory.json
EOF
