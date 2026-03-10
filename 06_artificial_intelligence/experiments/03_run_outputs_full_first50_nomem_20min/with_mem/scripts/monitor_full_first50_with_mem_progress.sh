#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
CACHE_FILE="${CACHE_FILE:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/cache/full_test_instances_cache.json}"
OUTDIR="${OUTDIR:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/outputs/run_outputs_full_first50_with_mem_20min}"
RUN_BATCH_LOG="${RUN_BATCH_LOG:-${OUTDIR}/run_batch.log}"
LOG_DIR="${LOG_DIR:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/logs}"
WINDOW_LOG_GLOB="${WINDOW_LOG_GLOB:-${LOG_DIR}/run_with_mem_window_*.log}"

INTERVAL="${INTERVAL:-10}"
ONCE="${ONCE:-0}"
NO_CLEAR="${NO_CLEAR:-0}"
STALE_WARN_SECONDS="${STALE_WARN_SECONDS:-1800}"
PROCESS_PATTERN='[r]un_full_first50_with_mem_20min.sh|[r]un_full_first50_with_mem_20min_windowed_prefetch.sh|[r]un_lite_windowed_with_mem.sh|[s]weagent run-batch --instances.subset full|[s]weagent run-batch --config /home/pt/SWE-bench/SWE-agent/config/deepseek.yaml --instances.type swe_bench --instances.subset full'

snapshot() {
  local now docker_status proc_lines proc_state proc_health process_table pids_csv
  local running_instance latest_window_log latest_window_mtime latest_window_age
  local run_batch_log_age docker_pull_err_count uncaught_count
  now="$(date '+%F %T %Z')"

  if docker info >/dev/null 2>&1; then
    docker_status="up"
  else
    docker_status="down"
  fi

  proc_lines="$(pgrep -af "${PROCESS_PATTERN}" || true)"
  if [[ -z "${proc_lines}" ]]; then
    proc_lines="(none)"
    proc_state="stopped"
    process_table="(none)"
  fi
  if [[ "${proc_lines}" != "(none)" ]]; then
    proc_state="running"
    pids_csv="$(pgrep -f "${PROCESS_PATTERN}" | tr '\n' ',' | sed 's/,$//')"
    if [[ -n "${pids_csv}" ]]; then
      process_table="$(ps -o pid,ppid,stat,etime,%cpu,%mem,cmd -p "${pids_csv}" 2>/dev/null || true)"
      if [[ -z "${process_table}" ]]; then
        process_table="(none)"
      fi
    else
      process_table="(none)"
    fi
  fi

  if [[ -f "${RUN_BATCH_LOG}" ]]; then
    running_instance="$(rg -N 'Running on instance ' "${RUN_BATCH_LOG}" | tail -n 1 | sed 's/.*Running on instance //')"
    run_batch_log_age="$(( $(date +%s) - $(stat -c %Y "${RUN_BATCH_LOG}") ))"
  else
    running_instance=""
    run_batch_log_age="-1"
  fi
  if [[ -z "${running_instance}" ]]; then
    running_instance="unknown"
  fi

  latest_window_log="$(ls -t ${WINDOW_LOG_GLOB} 2>/dev/null | head -n 1 || true)"
  if [[ -n "${latest_window_log}" && -f "${latest_window_log}" ]]; then
    latest_window_mtime="$(stat -c '%y' "${latest_window_log}")"
    latest_window_age="$(( $(date +%s) - $(stat -c %Y "${latest_window_log}") ))"
  else
    latest_window_mtime="n/a"
    latest_window_age="-1"
  fi

  docker_pull_err_count="$( (rg -N 'Uncaught DockerPullError' ${WINDOW_LOG_GLOB} 2>/dev/null || true) | wc -l | tr -d ' ' )"
  uncaught_count="$( (rg -N 'Uncaught ' ${WINDOW_LOG_GLOB} 2>/dev/null || true) | wc -l | tr -d ' ' )"

  proc_health="ok"
  if [[ "${proc_state}" == "running" && "${run_batch_log_age}" -ge "${STALE_WARN_SECONDS}" ]]; then
    proc_health="stale_suspect"
  fi

  echo "================ WITH_MEM FULL50 PROGRESS ================"
  echo "time: ${now}"
  echo "docker: ${docker_status}"
  echo "process_state: ${proc_state}"
  echo "process_health: ${proc_health} (stale_warn_seconds=${STALE_WARN_SECONDS})"
  echo "running_instance(last from run_batch.log): ${running_instance}"
  echo "run_batch_log_age_sec: ${run_batch_log_age}"
  echo "latest_window_log: ${latest_window_log:-n/a}"
  echo "latest_window_log_mtime: ${latest_window_mtime}"
  echo "latest_window_log_age_sec: ${latest_window_age}"
  echo "errors: uncaught=${uncaught_count}, docker_pull=${docker_pull_err_count}"
  echo "processes:"
  echo "${proc_lines}"
  echo "process_table:"
  echo "${process_table}"
  if [[ -f "${RUN_BATCH_LOG}" ]]; then
    echo "recent_instances_from_run_batch.log:"
    rg -N 'Running on instance ' "${RUN_BATCH_LOG}" | tail -n 3 || true
  fi
  echo "----------------------------------------------------------"

  SWE-agent/.venv/bin/python - <<'PY' "${CACHE_FILE}" "${OUTDIR}"
import json
import pathlib
import sys

cache = pathlib.Path(sys.argv[1])
outdir = pathlib.Path(sys.argv[2])

if not cache.exists():
    print("cache_missing=true")
    raise SystemExit(0)

ids = json.loads(cache.read_text(encoding="utf-8"))[:50]
done = []
for i, iid in enumerate(ids):
    if (outdir / iid / f"{iid}.traj").exists():
        done.append((i, iid))

remaining = [(i, iid) for i, iid in enumerate(ids) if (outdir / iid / f"{iid}.traj").exists() is False]

print(f"progress: {len(done)}/50 ({len(done) / 50:.1%})")
if done:
    print(f"last_done_index: {done[-1][0]}")
    print(f"last_done_instance: {done[-1][1]}")
if remaining:
    print(f"next_incomplete_index: {remaining[0][0]}")
    print(f"next_incomplete_instance: {remaining[0][1]}")
else:
    print("next_incomplete_index: 50")
    print("next_incomplete_instance: none")
PY
  echo "=========================================================="
}

if [[ "${ONCE}" == "1" ]]; then
  snapshot
  exit 0
fi

while true; do
  if [[ "${NO_CLEAR}" != "1" ]]; then
    clear
  fi
  snapshot
  sleep "${INTERVAL}"
done
