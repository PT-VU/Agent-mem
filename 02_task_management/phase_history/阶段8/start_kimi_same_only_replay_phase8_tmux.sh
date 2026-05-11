#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
RUNS_ROOT="${RUNS_ROOT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase8}"
SOURCE_RUN_ROOT="${SOURCE_RUN_ROOT:-${RUNS_ROOT}/phase8_same_only_001}"
SOURCE_SAME_JSON="${SOURCE_SAME_JSON:-${SOURCE_RUN_ROOT}/same_instances.json}"
MODEL_CONFIG="${MODEL_CONFIG:-${WS_ROOT}/SWE-agent/config/kimi25_siliconflow.yaml}"
PROMPT_PROFILE="${PROMPT_PROFILE:-prompt_base}"
RUN_TAG="${RUN_TAG:-phase8_same_only_kimi_replay_$(date +%Y%m%d_%H%M%S)}"
RUN_ROOT="${RUN_ROOT:-${RUNS_ROOT}/${RUN_TAG}}"
REPEATS="${REPEATS:-10}"
GLOBAL_HEAVY_SLOTS="${GLOBAL_HEAVY_SLOTS:-2}"
NOMEM_HEAVY_SLOTS="${NOMEM_HEAVY_SLOTS:-1}"
WITHMEM_HEAVY_SLOTS="${WITHMEM_HEAVY_SLOTS:-1}"
MAX_ACTIVE_RUN_BATCHES="${MAX_ACTIVE_RUN_BATCHES:-2}"
RESUME_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/resume_same_only_phase8.sh"
INVENTORY_SCRIPT="${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段8/collect_same_only_trial_inventory.py"

if [[ -z "${SILICONFLOW_API_KEY:-}" ]]; then
  echo "SILICONFLOW_API_KEY is required" >&2
  exit 2
fi
if [[ ! -f "${SOURCE_SAME_JSON}" ]]; then
  echo "source same instance list not found: ${SOURCE_SAME_JSON}" >&2
  exit 2
fi
if [[ -e "${RUN_ROOT}" ]]; then
  echo "target RUN_ROOT already exists: ${RUN_ROOT}" >&2
  exit 2
fi

mkdir -p "${RUN_ROOT}/orchestrator_logs" "${RUN_ROOT}/orchestrator_state" "${RUN_ROOT}/notes"
cp "${SOURCE_SAME_JSON}" "${RUN_ROOT}/same_instances.json"

SANITIZED_TAG="${RUN_TAG//[^A-Za-z0-9_]/_}"
MAIN_SESSION="${MAIN_SESSION:-${SANITIZED_TAG}_same_only}"
INDEX_SESSION="${INDEX_SESSION:-${SANITIZED_TAG}_trial_index}"
MAIN_LOG="${RUN_ROOT}/orchestrator_logs/same_only_resume.tmux.log"
INDEX_LOG="${RUN_ROOT}/orchestrator_logs/trial_indexer.tmux.log"

cat > "${RUN_ROOT}/orchestrator_state/run_manifest.json" <<EOF
{
  "generated_at": "$(date --iso-8601=seconds)",
  "experiment_type": "same_only_kimi_replay",
  "run_root": "${RUN_ROOT}",
  "source_run_root": "${SOURCE_RUN_ROOT}",
  "same_instances_json": "${RUN_ROOT}/same_instances.json",
  "model_config": "${MODEL_CONFIG}",
  "prompt_profile": "${PROMPT_PROFILE}",
  "repeats": ${REPEATS},
  "groups": ["nomem", "with_mem"],
  "comparison_axis": "same 15 instances, 10 attempts each, NoMem vs WithMem, Kimi via SiliconFlow",
  "recording": {
    "nomem": [
      "logs/<instance>/attempt_XX.log",
      "logs/<instance>/attempt_XX.jsonl",
      "metrics/attempt_reports/*.official_eval.json",
      "metrics/attempt_summaries/*.summary.json",
      "metrics/attempt_context/*.context.json"
    ],
    "with_mem": [
      "candidates/<instance>/logs/<instance>.attempt_XX.log",
      "candidates/<instance>/logs/<instance>.attempt_XX.jsonl",
      "candidates/<instance>/metrics/attempt_reports/*.official_eval.json",
      "candidates/<instance>/metrics/attempt_summaries/*.summary.json",
      "candidates/<instance>/metrics/attempt_feedback/*.feedback.json",
      "candidates/<instance>/metrics/attempt_context/*.context.json",
      "candidates/<instance>/metrics/run_context.json",
      "candidates/<instance>/persistence/{graph_store,sidecar_store,evidence_store}"
    ],
    "trial_inventory_json": "${RUN_ROOT}/orchestrator_state/trial_inventory.json"
  }
}
EOF

cat > "${RUN_ROOT}/notes/trial_recording_plan.md" <<'EOF'
# Trial Recording Plan

本次 Kimi 复现实验保留以下 trial 级数据，供后续 mem 分析：

1. 每个 attempt 的外层运行日志（`.log`）
2. 每个 attempt 的事件流（`.jsonl`）
3. 每个 attempt 的 official eval report / summary / feedback / context
4. WithMem 的 run_context 与 persistence（graph/sidecar/evidence）
5. 运行中周期性刷新 `orchestrator_state/trial_inventory.json`，作为分析入口索引

重点分析对象：

- `memory_hint_buffered`
- `memory_injected`
- `memory_gate_evaluation`
- `memory_intervention_feedback`
- attempt 级 resolved / unresolved / incomplete
- case 内 attempts 的先后依赖与路径变化
EOF

if tmux has-session -t "${MAIN_SESSION}" 2>/dev/null; then
  tmux kill-session -t "${MAIN_SESSION}"
fi
if tmux has-session -t "${INDEX_SESSION}" 2>/dev/null; then
  tmux kill-session -t "${INDEX_SESSION}"
fi

"${WS_ROOT}/SWE-agent/.venv/bin/python" "${INVENTORY_SCRIPT}" --run-root "${RUN_ROOT}" >/dev/null

tmux new-session -d -s "${MAIN_SESSION}" \
  "env SILICONFLOW_API_KEY='${SILICONFLOW_API_KEY}' RUN_ROOT='${RUN_ROOT}' RUN_TAG='${RUN_TAG}' MODEL_CONFIG='${MODEL_CONFIG}' PROMPT_PROFILE='${PROMPT_PROFILE}' REPEATS='${REPEATS}' GLOBAL_HEAVY_SLOTS='${GLOBAL_HEAVY_SLOTS}' NOMEM_HEAVY_SLOTS='${NOMEM_HEAVY_SLOTS}' WITHMEM_HEAVY_SLOTS='${WITHMEM_HEAVY_SLOTS}' MAX_ACTIVE_RUN_BATCHES='${MAX_ACTIVE_RUN_BATCHES}' '${RESUME_SCRIPT}' >> '${MAIN_LOG}' 2>&1"

tmux new-session -d -s "${INDEX_SESSION}" \
  "while tmux has-session -t '${MAIN_SESSION}' 2>/dev/null; do '${WS_ROOT}/SWE-agent/.venv/bin/python' '${INVENTORY_SCRIPT}' --run-root '${RUN_ROOT}' >> '${INDEX_LOG}' 2>&1; sleep 60; done; '${WS_ROOT}/SWE-agent/.venv/bin/python' '${INVENTORY_SCRIPT}' --run-root '${RUN_ROOT}' >> '${INDEX_LOG}' 2>&1"

cat <<EOF
run_root=${RUN_ROOT}
main_session=${MAIN_SESSION}
index_session=${INDEX_SESSION}
main_log=${MAIN_LOG}
index_log=${INDEX_LOG}
trial_inventory=${RUN_ROOT}/orchestrator_state/trial_inventory.json
EOF
