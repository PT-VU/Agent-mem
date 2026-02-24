#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
SWE_AGENT_ROOT="${WS_ROOT}/SWE-agent"
PERSIST_ROOT="${WS_ROOT}/PDDL_work_mem/persistence"

MODE="${SWE_AGENT_AGENT_MEM_MODE:-with-mem}"
if [[ "${1:-}" == "--mode" ]]; then
  if [[ $# -lt 2 ]]; then
    echo "Missing value for --mode (expected with-mem|no-mem)" >&2
    exit 2
  fi
  MODE="$2"
  shift 2
fi

case "${MODE}" in
  with-mem)
    export SWE_AGENT_EXTERNAL_HOOK_CLASS="${SWE_AGENT_EXTERNAL_HOOK_CLASS:-PDDL_work_mem.tools.sweagent_ext_tools.bridge_hook:ExternalToolBridgeHook}"
    export SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH="${SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH:-${WS_ROOT}}"
    export SWE_AGENT_EXT_TOOL_A_CMD="${SWE_AGENT_EXT_TOOL_A_CMD:-${WS_ROOT}/PDDL_work_mem/tools/sweagent_ext_tools/bin/run_tool_a.sh}"
    export SWE_AGENT_EXT_TOOL_B_CMD="${SWE_AGENT_EXT_TOOL_B_CMD:-${WS_ROOT}/PDDL_work_mem/tools/sweagent_ext_tools/bin/run_tool_b.sh}"
    export SWE_AGENT_EXT_TOOL_TIMEOUT_SEC="${SWE_AGENT_EXT_TOOL_TIMEOUT_SEC:-8.0}"
    export SWE_AGENT_EXT_TOOLS_LOG_FILE="${SWE_AGENT_EXT_TOOLS_LOG_FILE:-/tmp/sweagent_ext_tools.log}"
    export AGENT_MEM_STORAGE_DIR="${AGENT_MEM_STORAGE_DIR:-${PERSIST_ROOT}/graph_store}"
    export AGENT_MEM_EVIDENCE_DIR="${AGENT_MEM_EVIDENCE_DIR:-${PERSIST_ROOT}/evidence_store}"
    export AGENT_MEM_EMBEDDING_MODEL="${AGENT_MEM_EMBEDDING_MODEL:-sentence-transformers}"
    export AGENT_MEM_EMBEDDING_MODEL_NAME="${AGENT_MEM_EMBEDDING_MODEL_NAME:-all-MiniLM-L6-v2}"
    mkdir -p "${AGENT_MEM_STORAGE_DIR}" "${AGENT_MEM_EVIDENCE_DIR}"
    ;;
  no-mem)
    export SWE_AGENT_EXTERNAL_HOOK_CLASS="${SWE_AGENT_EXTERNAL_HOOK_CLASS:-PDDL_work_mem.tools.sweagent_ext_tools.baseline_hook:BaselineLoggingHook}"
    export SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH="${SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH:-${WS_ROOT}}"
    export SWE_AGENT_EXT_TOOLS_LOG_FILE="${SWE_AGENT_EXT_TOOLS_LOG_FILE:-/tmp/sweagent_ext_tools.log}"
    ;;
  *)
    echo "Unsupported mode: ${MODE} (expected with-mem|no-mem)" >&2
    exit 2
    ;;
esac

export SWE_AGENT_EXT_MODE="${MODE}"

if [[ "${1:-}" == "--smoke-test" ]]; then
  exec "${SWE_AGENT_ROOT}/.venv/bin/python" "${WS_ROOT}/PDDL_work_mem/tools/sweagent_ext_tools/tests/smoke_test.py"
fi

if [[ $# -eq 0 ]]; then
  cat <<'USAGE'
Usage:
  start_with_external_tools.sh [--mode with-mem|no-mem] --smoke-test
  start_with_external_tools.sh [--mode with-mem|no-mem] <command> [args...]

Examples:
  start_with_external_tools.sh --mode with-mem --smoke-test
  start_with_external_tools.sh --mode no-mem --smoke-test
  start_with_external_tools.sh --mode with-mem sweagent run --config config/default.yaml ...
USAGE
  exit 1
fi

exec "$@"
