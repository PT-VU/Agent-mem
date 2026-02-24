#!/usr/bin/env bash
set -euo pipefail
export SWE_AGENT_EXT_TOOLS_LOG_FILE="/home/pt/SWE-bench/PDDL_work_mem/实验/实验01/no_mem_tool_events_lite_full_retry_20260219_173136.jsonl"
exec /home/pt/SWE-bench/PDDL_work_mem/tools/sweagent_ext_tools/bin/start_with_external_tools.sh --mode no-mem   /home/pt/SWE-bench/SWE-agent/.venv/bin/sweagent run-batch   --config /home/pt/SWE-bench/SWE-agent/config/deepseek.yaml   --instances.type swe_bench   --instances.subset lite   --instances.split test   --num_workers 1   --env_var_path /home/pt/SWE-bench/SWE-agent/.env   --agent.model.per_instance_call_limit 6   --output_dir "/home/pt/SWE-bench/PDDL_work_mem/实验/实验01/run_outputs_lite_full_nomem_retry_20260219_173136"
