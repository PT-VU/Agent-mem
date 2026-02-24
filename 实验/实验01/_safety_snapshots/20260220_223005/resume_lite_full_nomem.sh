#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="/home/pt/SWE-bench"
OUTDIR="$WS_ROOT/PDDL_work_mem/实验/实验01/run_outputs_lite_full_nomem_retry_debug"
EVENTLOG="$WS_ROOT/PDDL_work_mem/实验/实验01/no_mem_tool_events_lite_full_resume.jsonl"

if ! docker info >/dev/null 2>&1; then
  echo "docker is not healthy in this WSL distro. Please restart Docker Desktop + WSL integration, then retry." >&2
  exit 2
fi

SWE_AGENT_EXT_TOOLS_LOG_FILE="$EVENTLOG" \
  "$WS_ROOT/PDDL_work_mem/tools/sweagent_ext_tools/bin/start_with_external_tools.sh" \
  --mode no-mem \
  "$WS_ROOT/SWE-agent/.venv/bin/sweagent" run-batch \
  --config "$WS_ROOT/SWE-agent/config/deepseek.yaml" \
  --instances.type swe_bench \
  --instances.subset lite \
  --instances.split test \
  --instances.deployment.remove_images true \
  --skip_existing true \
  --num_workers 1 \
  --env_var_path "$WS_ROOT/SWE-agent/.env" \
  --agent.model.per_instance_call_limit 6 \
  --output_dir "$OUTDIR" \
  "$@"
