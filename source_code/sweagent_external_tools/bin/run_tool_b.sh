#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
SWE_AGENT_PYTHON="${WS_ROOT}/SWE-agent/.venv/bin/python"
export PYTHONPATH="${WS_ROOT}:${PYTHONPATH:-}"
if [[ ! -x "${SWE_AGENT_PYTHON}" ]]; then
  SWE_AGENT_PYTHON="python3"
fi
"${SWE_AGENT_PYTHON}" -m PDDL_work_mem.source_code.sweagent_external_tools.dispatcher --tool B
