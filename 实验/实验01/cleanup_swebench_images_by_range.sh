#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="/home/pt/SWE-bench"
EXP_DIR="$WS_ROOT/PDDL_work_mem/实验/实验01"
CACHE_FILE="$EXP_DIR/lite_test_instances_cache.json"
PY="$WS_ROOT/SWE-agent/.venv/bin/python"
WINDOW_TOOL="$EXP_DIR/windowed_instances.py"

# Comma-separated index ranges to keep. Example: "0:25,184:209"
KEEP_RANGES="${KEEP_RANGES:-0:25,184:209}"
# 1: prune builder cache after image cleanup; 0: skip.
PRUNE_BUILD_CACHE="${PRUNE_BUILD_CACHE:-1}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command unavailable in this WSL distro. Fix Docker Desktop WSL integration first." >&2
  exit 3
fi

if ! docker info >/dev/null 2>&1; then
  echo "docker daemon is not healthy. Restart Docker Desktop + WSL integration first." >&2
  exit 3
fi

if [ ! -f "$CACHE_FILE" ]; then
  "$PY" "$WINDOW_TOOL" cache --subset lite --split test --cache-file "$CACHE_FILE" >/dev/null
fi

KEEP_FILE="$(mktemp)"
ALL_FILE="$(mktemp)"
TMP_FILE="$(mktemp)"
trap 'rm -f "$KEEP_FILE" "$ALL_FILE" "$TMP_FILE"' EXIT

: > "$KEEP_FILE"
IFS=',' read -r -a ranges <<< "$KEEP_RANGES"
for r in "${ranges[@]}"; do
  s="${r%%:*}"
  e="${r##*:}"
  if [ -z "$s" ] || [ -z "$e" ]; then
    continue
  fi
  "$PY" "$WINDOW_TOOL" range --cache-file "$CACHE_FILE" --start "$s" --end "$e" --field image --unique \
    | rg '^(docker\.io/)?swebench/sweb\.eval\.x86_64\.' \
    | sed 's#^docker\.io/##' > "$TMP_FILE" || true
  cat "$TMP_FILE" >> "$KEEP_FILE"
done
sort -u "$KEEP_FILE" -o "$KEEP_FILE"

docker image ls --format '{{.Repository}}:{{.Tag}}' | rg '^swebench/sweb.eval.x86_64\\.' > "$ALL_FILE" || true

removed=0
kept=0
while IFS= read -r img; do
  [ -z "$img" ] && continue
  if rg -Fxq "$img" "$KEEP_FILE"; then
    kept=$((kept + 1))
    continue
  fi
  docker image rm -f "$img" >/dev/null 2>&1 || true
  removed=$((removed + 1))
done < "$ALL_FILE"

docker image prune -f >/dev/null 2>&1 || true
if [ "$PRUNE_BUILD_CACHE" = "1" ]; then
  docker builder prune -f >/dev/null 2>&1 || true
fi

echo "Cleanup done. keep_ranges=$KEEP_RANGES kept=$kept removed=$removed"
