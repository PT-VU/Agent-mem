#!/usr/bin/env bash
# 阶段9-v2：v2 副本下的 run_tool_a，使用显式 WS_ROOT + v2 dispatcher 模块路径
set -euo pipefail
WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_PYTHON="${SWE_AGENT_PYTHON:-${WS_ROOT}/SWE-agent/.venv/bin/python}"
export PYTHONPATH="${WS_ROOT}/PDDL_work_mem:${WS_ROOT}:${PYTHONPATH:-}"
if [[ ! -x "${SWE_AGENT_PYTHON}" ]]; then
  SWE_AGENT_PYTHON="python3"
fi
"${SWE_AGENT_PYTHON}" -m sweagent_external_tools_v2.dispatcher --tool A
