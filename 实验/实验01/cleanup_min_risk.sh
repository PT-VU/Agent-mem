#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="/home/pt/SWE-bench"
EXP_DIR="$WS_ROOT/PDDL_work_mem/实验/实验01"
OUTDIR="$EXP_DIR/run_outputs_lite_full_nomem_retry_debug"
STAMP="$(date +%Y%m%d_%H%M%S)"
SNAP_DIR="$EXP_DIR/_safety_snapshots/$STAMP"
TRASH_DIR="$EXP_DIR/_trash_invalid/$STAMP"
AGGRESSIVE=0

if [ "${1:-}" = "--aggressive" ]; then
  AGGRESSIVE=1
fi

mkdir -p "$SNAP_DIR" "$TRASH_DIR"

if ! docker info >/dev/null 2>&1; then
  echo "docker is not healthy. Restart Docker Desktop and retry." >&2
  exit 2
fi

# Never clean while run-batch is active.
if pgrep -fa "sweagent run-batch" >/dev/null 2>&1; then
  echo "Detected active sweagent run-batch process. Stop it first, then rerun cleanup." >&2
  exit 3
fi

cp -a "$EXP_DIR/README.md" "$SNAP_DIR/" 2>/dev/null || true
cp -a "$EXP_DIR/metrics_experiment01.json" "$SNAP_DIR/" 2>/dev/null || true
cp -a "$EXP_DIR/instances_lite_exp01.json" "$SNAP_DIR/" 2>/dev/null || true
cp -a "$EXP_DIR/instances_lite_exp01_local.yaml" "$SNAP_DIR/" 2>/dev/null || true
cp -a "$EXP_DIR/resume_lite_full_nomem.sh" "$SNAP_DIR/" 2>/dev/null || true
cp -a "$OUTDIR/run_batch.log" "$SNAP_DIR/" 2>/dev/null || true
cp -a "$OUTDIR/run_batch.config.yaml" "$SNAP_DIR/" 2>/dev/null || true

python3 - <<'PY' > "$SNAP_DIR/run_status_before.txt"
import json,glob,os
root='PDDL_work_mem/实验/实验01/run_outputs_lite_full_nomem_retry_debug'
dirs=[d for d in glob.glob(root+'/*') if os.path.isdir(d)]
complete=0
incomplete=[]
no_traj=[]
for d in sorted(dirs):
    trajs=glob.glob(d+'/*.traj')
    if not trajs:
        no_traj.append(os.path.basename(d))
        continue
    try:
        obj=json.load(open(trajs[0]))
        es=obj.get('info',{}).get('exit_status')
    except Exception:
        es=None
    if es:
        complete+=1
    else:
        incomplete.append(os.path.basename(d))
print(f'instance_dirs={len(dirs)}')
print(f'complete_with_exit_status={complete}')
print(f'incomplete_with_traj_no_exit={len(incomplete)}')
print(f'no_traj={len(no_traj)}')
print('no_traj_first20=' + ','.join(no_traj[:20]))
print('incomplete_first20=' + ','.join(incomplete[:20]))
PY

docker system df > "$SNAP_DIR/docker_system_df_before.txt"
df -h > "$SNAP_DIR/df_before.txt"

# Move stale pid files and empty launcher logs to trash (preserve, do not hard-delete).
for f in "$EXP_DIR"/*.pid; do
  [ -e "$f" ] || continue
  p="$(cat "$f" 2>/dev/null || true)"
  if [ -z "$p" ] || ! ps -p "$p" >/dev/null 2>&1; then
    mv "$f" "$TRASH_DIR/"
  fi
done

find "$EXP_DIR" -maxdepth 1 -type f -name "*.log" -size 0 -print0 | xargs -0 -r -I {} mv "{}" "$TRASH_DIR/"

# Minimal-risk Docker cleanup: only dangling layers and build cache.
if [ "$AGGRESSIVE" -eq 1 ]; then
  timeout 1800 docker image prune -a -f > "$SNAP_DIR/docker_image_prune.txt" || true
else
  timeout 900 docker image prune -f > "$SNAP_DIR/docker_image_prune.txt" || true
fi
timeout 180 docker builder prune -f > "$SNAP_DIR/docker_builder_prune.txt" || true

docker system df > "$SNAP_DIR/docker_system_df_after.txt"
df -h > "$SNAP_DIR/df_after.txt"

echo "Cleanup finished."
echo "Snapshot: $SNAP_DIR"
echo "Trash:    $TRASH_DIR"
