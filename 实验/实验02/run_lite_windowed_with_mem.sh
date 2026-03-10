#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"

# Backward-compatible entrypoint used in history commands.
# It now targets the current full-first50 with_mem experiment artifacts.
exec "${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/scripts/run_full_first50_with_mem_20min_windowed_prefetch.sh" "$@"

