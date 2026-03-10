#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
INTERVAL="${INTERVAL:-8}"

RUN1_OUTDIR="${RUN1_OUTDIR:-$WS_ROOT/PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/with_mem/outputs/run_outputs_lite_first50_with_mem}"
RUN1_LOG="${RUN1_LOG:-$WS_ROOT/PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/with_mem/logs/run_with_mem_window_0_25.log}"
RUN1_TOTAL="${RUN1_TOTAL:-50}"

RUN2_BASE="${RUN2_BASE:-$WS_ROOT/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/comparison_runs}"
RUN2_DIR="${RUN2_DIR:-$(ls -1dt "$RUN2_BASE"/first25_repeat10_slide25_* 2>/dev/null | head -n1 || true)}"

count_traj() {
  local dir="$1"
  if [[ -d "$dir" ]]; then
    find "$dir" -type f -name '*.traj' | wc -l | tr -d ' '
  else
    echo "0"
  fi
}

latest_instance_line() {
  local file="$1"
  if [[ -f "$file" ]]; then
    grep -E 'Running on instance|❌ Failed on|submitted|Uncaught' "$file" | tail -n1 || true
  fi
}

while true; do
  clear
  echo "=== Experiment Progress Monitor ==="
  date '+%F %T %Z'
  echo

  echo "[Process A] first50_slide25 with-mem"
  pgrep -af 'run_lite_first50_with_mem\.sh|sweagent run-batch .*--instances\.subset lite .*--instances\.slice' || echo "PID: not running"
  r1_done="$(count_traj "$RUN1_OUTDIR")"
  echo "Progress: ${r1_done}/${RUN1_TOTAL}"
  echo "Latest:"
  latest_instance_line "$RUN1_LOG"
  echo

  echo "[Process B] first25_repeat10_slide25 (latest run dir)"
  if [[ -n "$RUN2_DIR" && -d "$RUN2_DIR" ]]; then
    echo "RUN2_DIR=$RUN2_DIR"
    pgrep -af 'run_first25_repeat10_with_vs_no_mem_and_eval\.sh|run_multi_try_no_mem_20min\.sh|run_multi_try_with_mem_20min\.sh|sweagent run-batch .*--instances\.filter' || echo "PID: not running"
    no_dir="$RUN2_DIR/no_mem/outputs"
    with_dir="$RUN2_DIR/with_mem/outputs"
    no_done="$(count_traj "$no_dir")"
    with_done="$(count_traj "$with_dir")"
    echo "no_mem traj:  ${no_done}"
    echo "with_mem traj:${with_done}"
    latest_no="$(find "$RUN2_DIR/no_mem" -type f -name run_batch.log -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | awk '{print $2}')"
    latest_with="$(find "$RUN2_DIR/with_mem" -type f -name run_batch.log -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | awk '{print $2}')"
    echo "Latest no_mem:"
    latest_instance_line "${latest_no:-/dev/null}"
    echo "Latest with_mem:"
    latest_instance_line "${latest_with:-/dev/null}"
  else
    echo "RUN2_DIR not found under $RUN2_BASE"
  fi
  echo

  echo "Refresh in ${INTERVAL}s  (Ctrl+C to exit)"
  sleep "$INTERVAL"
done

