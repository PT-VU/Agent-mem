#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="/home/pt/SWE-bench"
EXP_DIR="$WS_ROOT/PDDL_work_mem/实验/实验02"
OUTDIR="${OUTDIR:-$EXP_DIR/run_outputs_lite_full_mem_retry_debug}"
SWEBENCH_SUBSET="${SWEBENCH_SUBSET:-lite}"
SWEBENCH_SPLIT="${SWEBENCH_SPLIT:-test}"
CACHE_FILE="${CACHE_FILE:-$EXP_DIR/${SWEBENCH_SUBSET}_${SWEBENCH_SPLIT}_instances_cache.json}"
WINDOW_SIZE="${WINDOW_SIZE:-25}"
# Keep this baseline range plus current/next window images.
KEEP_BASE_RANGES="${KEEP_BASE_RANGES:-0:25}"
# auto: first missing index; integer: force start index.
START_INDEX="${START_INDEX:-auto}"
# 1: run all windows until STOP_INDEX/TOTAL; 0: run one window only.
AUTO_CONTINUE="${AUTO_CONTINUE:-1}"
# Optional upper bound (exclusive). "auto" means TOTAL.
STOP_INDEX="${STOP_INDEX:-auto}"
# Safety valve for debug. 0 means unlimited windows.
MAX_WINDOWS="${MAX_WINDOWS:-0}"
# 1: prune builder cache each window to cap disk growth; 0: skip.
PRUNE_BUILD_CACHE_EACH_WINDOW="${PRUNE_BUILD_CACHE_EACH_WINDOW:-1}"
# 0: unlimited calls. >0: per-instance call cap.
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
# 0: keep default from config; >0: override per-instance total execution timeout.
INSTANCE_TOTAL_EXEC_TIMEOUT_SEC="${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC:-0}"
MODEL_CONFIG="${MODEL_CONFIG:-$WS_ROOT/SWE-agent/config/deepseek.yaml}"
NUM_WORKERS="${NUM_WORKERS:-1}"

PY="$WS_ROOT/SWE-agent/.venv/bin/python"
SWEAGENT="$WS_ROOT/SWE-agent/.venv/bin/sweagent"
EXT_WRAPPER="$WS_ROOT/PDDL_work_mem/tools/sweagent_ext_tools/bin/start_with_external_tools.sh"
WINDOW_TOOL="$WS_ROOT/PDDL_work_mem/实验/实验01/windowed_instances.py"

AGENT_MEM_STORAGE_DIR_DEFAULT="$EXP_DIR/persistence/graph_store"
AGENT_MEM_EVIDENCE_DIR_DEFAULT="$EXP_DIR/persistence/evidence_store"
AGENT_MEM_STORAGE_DIR="${AGENT_MEM_STORAGE_DIR:-$AGENT_MEM_STORAGE_DIR_DEFAULT}"
AGENT_MEM_EVIDENCE_DIR="${AGENT_MEM_EVIDENCE_DIR:-$AGENT_MEM_EVIDENCE_DIR_DEFAULT}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Missing python runtime: $PY" >&2
  exit 2
fi

if ! command -v "$SWEAGENT" >/dev/null 2>&1; then
  echo "Missing sweagent runtime: $SWEAGENT" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command unavailable in this WSL distro. Fix Docker Desktop WSL integration first." >&2
  exit 3
fi

if ! docker info >/dev/null 2>&1; then
  echo "docker daemon is not healthy. Restart Docker Desktop + WSL integration first." >&2
  exit 3
fi

mkdir -p "$OUTDIR" "$AGENT_MEM_STORAGE_DIR" "$AGENT_MEM_EVIDENCE_DIR"

# Build or refresh cache when missing.
if [ ! -f "$CACHE_FILE" ]; then
  "$PY" "$WINDOW_TOOL" cache --subset "$SWEBENCH_SUBSET" --split "$SWEBENCH_SPLIT" --cache-file "$CACHE_FILE" >/dev/null
fi

TOTAL="$("$PY" "$WINDOW_TOOL" total --cache-file "$CACHE_FILE" | tail -n 1)"

if [ "$START_INDEX" = "auto" ]; then
  FIRST_MISSING_JSON="$("$PY" "$WINDOW_TOOL" first-missing --cache-file "$CACHE_FILE" --output-dir "$OUTDIR" | tail -n 1)"
  START="$(echo "$FIRST_MISSING_JSON" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["index"])')"
else
  START="$START_INDEX"
fi

if [ "$START" -ge "$TOTAL" ]; then
  echo "All instances are complete. Nothing to run."
  exit 0
fi

if [ "$STOP_INDEX" = "auto" ]; then
  STOP="$TOTAL"
else
  STOP="$STOP_INDEX"
fi

if [ "$STOP" -gt "$TOTAL" ]; then
  STOP="$TOTAL"
fi

if [ "$START" -ge "$STOP" ]; then
  echo "Nothing to run: START_INDEX=$START STOP_INDEX=$STOP TOTAL=$TOTAL"
  exit 0
fi

KEEP_FILE="$(mktemp)"
CURRENT_IMAGES_FILE="$(mktemp)"
NEXT_IMAGES_FILE="$(mktemp)"
ALL_SWEBENCH_FILE="$(mktemp)"
TMP_RANGE_FILE="$(mktemp)"
trap 'rm -f "$KEEP_FILE" "$CURRENT_IMAGES_FILE" "$NEXT_IMAGES_FILE" "$ALL_SWEBENCH_FILE" "$TMP_RANGE_FILE"' EXIT

build_image_list_for_range() {
  local s="$1"
  local e="$2"
  local out="$3"
  if [ "$s" -ge "$e" ]; then
    : > "$out"
    return 0
  fi
  "$PY" "$WINDOW_TOOL" pending-range \
    --cache-file "$CACHE_FILE" \
    --start "$s" \
    --end "$e" \
    --field image \
    --output-dir "$OUTDIR" \
    --unique \
    | rg '^(docker\.io/)?swebench/sweb\.eval\.x86_64\.' \
    | sed 's#^docker\.io/##' > "$out" || true
}

prefetch_images_file() {
  local file="$1"
  local log_file="$2"
  local total_lines
  total_lines="$(wc -l < "$file" | tr -d ' ')"
  if [ "$total_lines" = "0" ]; then
    return 0
  fi
  while IFS= read -r img; do
    [ -z "$img" ] && continue
    if docker image inspect "$img" >/dev/null 2>&1; then
      continue
    fi
    echo "[prefetch] pulling $img" >> "$log_file"
    docker pull "$img" >> "$log_file" 2>&1 || echo "[prefetch] failed $img" >> "$log_file"
  done < "$file"
}

build_keep_file() {
  : > "$KEEP_FILE"
  : > "$TMP_RANGE_FILE"
  IFS=',' read -r -a ranges <<< "$KEEP_BASE_RANGES"
  for r in "${ranges[@]}"; do
    # Expected format start:end
    local_s="${r%%:*}"
    local_e="${r##*:}"
    if [ -n "$local_s" ] && [ -n "$local_e" ]; then
      build_image_list_for_range "$local_s" "$local_e" "$TMP_RANGE_FILE"
      cat "$TMP_RANGE_FILE" >> "$KEEP_FILE"
    fi
  done
  cat "$CURRENT_IMAGES_FILE" >> "$KEEP_FILE"
  cat "$NEXT_IMAGES_FILE" >> "$KEEP_FILE"
  sort -u "$KEEP_FILE" -o "$KEEP_FILE"
}

cleanup_except_keep() {
  local before_count
  local after_count
  local kept
  local removed
  local failed

  kept=0
  removed=0
  failed=0
  docker image ls --format '{{.Repository}}:{{.Tag}}' | rg '^swebench/sweb.eval.x86_64\\.' > "$ALL_SWEBENCH_FILE" || true
  before_count="$(wc -l < "$ALL_SWEBENCH_FILE" | tr -d ' ')"
  while IFS= read -r img; do
    [ -z "$img" ] && continue
    if rg -Fxq "$img" "$KEEP_FILE"; then
      kept=$((kept + 1))
      continue
    fi
    if docker image rm -f "$img" >/dev/null 2>&1; then
      removed=$((removed + 1))
    else
      failed=$((failed + 1))
    fi
  done < "$ALL_SWEBENCH_FILE"
  docker image prune -f >/dev/null 2>&1 || true
  if [ "$PRUNE_BUILD_CACHE_EACH_WINDOW" = "1" ]; then
    docker builder prune -f >/dev/null 2>&1 || true
  fi
  docker image ls --format '{{.Repository}}:{{.Tag}}' | rg '^swebench/sweb.eval.x86_64\\.' > "$ALL_SWEBENCH_FILE" || true
  after_count="$(wc -l < "$ALL_SWEBENCH_FILE" | tr -d ' ')"
  echo "Cleanup result: swebench_before=$before_count kept=$kept removed=$removed failed=$failed swebench_after=$after_count"
}

CURRENT_START="$START"
WINDOW_COUNT=0
EXTRA_AGENT_ARGS=()
if [ "$INSTANCE_TOTAL_EXEC_TIMEOUT_SEC" -gt 0 ] 2>/dev/null; then
  EXTRA_AGENT_ARGS+=(--agent.tools.total_execution_timeout "$INSTANCE_TOTAL_EXEC_TIMEOUT_SEC")
fi

while [ "$CURRENT_START" -lt "$STOP" ]; do
  CURRENT_END=$((CURRENT_START + WINDOW_SIZE))
  if [ "$CURRENT_END" -gt "$STOP" ]; then
    CURRENT_END="$STOP"
  fi
  if [ "$CURRENT_END" -gt "$TOTAL" ]; then
    CURRENT_END="$TOTAL"
  fi

  NEXT_START="$CURRENT_END"
  NEXT_END=$((NEXT_START + WINDOW_SIZE))
  if [ "$NEXT_END" -gt "$STOP" ]; then
    NEXT_END="$STOP"
  fi
  if [ "$NEXT_END" -gt "$TOTAL" ]; then
    NEXT_END="$TOTAL"
  fi

  RUN_TAG="window_${CURRENT_START}_${CURRENT_END}_$(date +%Y%m%d_%H%M%S)"
  EVENTLOG="$EXP_DIR/with_mem_tool_events_${RUN_TAG}.jsonl"
  PREFETCH_LOG="$EXP_DIR/prefetch_with_mem_${RUN_TAG}.log"

  build_image_list_for_range "$CURRENT_START" "$CURRENT_END" "$CURRENT_IMAGES_FILE"
  build_image_list_for_range "$NEXT_START" "$NEXT_END" "$NEXT_IMAGES_FILE"

  echo "Window run plan: start=$CURRENT_START end=$CURRENT_END next_start=$NEXT_START next_end=$NEXT_END stop=$STOP total=$TOTAL"
  echo "Prefetch current window images..."
  prefetch_images_file "$CURRENT_IMAGES_FILE" "$PREFETCH_LOG"

  # Keep baseline/current/next windows only.
  build_keep_file
  echo "Cleaning swebench images outside keep windows..."
  cleanup_except_keep

  if [ "$NEXT_START" -lt "$NEXT_END" ]; then
    echo "Prefetch next window in background..."
    prefetch_images_file "$NEXT_IMAGES_FILE" "$PREFETCH_LOG" &
    PREFETCH_PID="$!"
  else
    PREFETCH_PID=""
  fi

  echo "Running sweagent slice ${CURRENT_START}:${CURRENT_END} (with-mem)"
  AGENT_MEM_STORAGE_DIR="$AGENT_MEM_STORAGE_DIR" \
  AGENT_MEM_EVIDENCE_DIR="$AGENT_MEM_EVIDENCE_DIR" \
  SWE_AGENT_EXT_TOOLS_LOG_FILE="$EVENTLOG" \
    "$EXT_WRAPPER" --mode with-mem \
    "$SWEAGENT" run-batch \
    --config "$MODEL_CONFIG" \
    --instances.type swe_bench \
    --instances.subset "$SWEBENCH_SUBSET" \
    --instances.split "$SWEBENCH_SPLIT" \
    --instances.slice "${CURRENT_START}:${CURRENT_END}" \
    --instances.deployment.remove_images true \
    --num_workers "$NUM_WORKERS" \
    --env_var_path "$WS_ROOT/SWE-agent/.env" \
    --agent.model.per_instance_call_limit "$PER_INSTANCE_CALL_LIMIT" \
    "${EXTRA_AGENT_ARGS[@]}" \
    --output_dir "$OUTDIR"

  if [ -n "$PREFETCH_PID" ]; then
    wait "$PREFETCH_PID" || true
  fi

  echo "Window finished: ${CURRENT_START}:${CURRENT_END}"
  echo "Event log: $EVENTLOG"
  echo "Prefetch log: $PREFETCH_LOG"

  WINDOW_COUNT=$((WINDOW_COUNT + 1))
  CURRENT_START="$CURRENT_END"

  if [ "$AUTO_CONTINUE" != "1" ]; then
    break
  fi
  if [ "$MAX_WINDOWS" -gt 0 ] && [ "$WINDOW_COUNT" -ge "$MAX_WINDOWS" ]; then
    echo "Reached MAX_WINDOWS=$MAX_WINDOWS, stop loop."
    break
  fi
done
