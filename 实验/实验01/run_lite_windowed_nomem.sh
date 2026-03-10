#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"

# Backward-compatible entrypoint for historical command compatibility.
exec "${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/no_mem/scripts/run_full_first50_nomem_20min.sh" "$@"

