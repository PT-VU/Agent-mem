#!/usr/bin/env bash
# Usage: bash monitor_f1f2.sh <RUN_ROOT>
# Shows per-instance, per-attempt R/U/I progress for a with_mem watchdog run.

RUN_ROOT="${1:?Usage: $0 <RUN_ROOT>}"

SUMMARIES_DIR="${RUN_ROOT}/same_problem/with_mem/metrics/attempt_summaries"

# nomem baseline paths
NOMEM_EXPAND4="/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase9_v2/phase9_v2c_expand4_20260429_075835/same_problem/nomem/metrics/attempt_summaries"
NOMEM_134648="/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase9_v2/phase9_v2_moonshot_kimi_full_12057_11693_20260426_134648/same_problem/nomem/metrics/attempt_summaries"

declare -A NOMEM_DIRS=(
  ["sympy__sympy-22383"]="${NOMEM_EXPAND4}"
  ["astropy__astropy-11693"]="${NOMEM_134648}"
  ["astropy__astropy-12057"]="${NOMEM_134648}"
)
declare -A NOMEM_TOTAL=(
  ["sympy__sympy-22383"]="9"
  ["astropy__astropy-11693"]="10"
  ["astropy__astropy-12057"]="10"
)

python3 << PYEOF
import json, glob, os, datetime

run_root = "${RUN_ROOT}"
summaries_dir = "${SUMMARIES_DIR}"
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

instances = ["sympy__sympy-22383", "astropy__astropy-11693", "astropy__astropy-12057"]
nomem_dirs = {
    "sympy__sympy-22383":   "${NOMEM_EXPAND4}",
    "astropy__astropy-11693": "${NOMEM_134648}",
    "astropy__astropy-12057": "${NOMEM_134648}",
}
nomem_totals = {
    "sympy__sympy-22383":   9,
    "astropy__astropy-11693": 10,
    "astropy__astropy-12057": 10,
}

print(f"{'='*70}")
print(f"  F1+F2 Progress Monitor   {now}")
print(f"  run: {os.path.basename(run_root)}")
print(f"{'='*70}")

total_wm_r = total_wm_u = total_wm_i = total_wm_done = 0
total_nm_r = 0; total_nm_total = 0

for inst in instances:
    # with_mem eval reports (per-instance path)
    eval_pattern = f"{run_root}/same_problem/with_mem/{inst}/candidates/{inst}/metrics/attempt_reports/{inst}.attempt_*.official_eval.json"
    wm_files = sorted(glob.glob(eval_pattern))
    wm_r = wm_u = wm_i = 0
    for sf in wm_files:
        try:
            with open(sf) as fh: s = json.load(fh)
            rid = s.get("resolved_ids", [])
            uid = s.get("unresolved_ids", [])
            if rid:
                wm_r += 1
            elif uid:
                wm_u += 1
            else:
                wm_i += 1
        except Exception:
            pass
    wm_done = len(wm_files)

    # nomem summaries
    nm_dir = nomem_dirs[inst]
    nm_files = sorted(glob.glob(f"{nm_dir}/{inst}.attempt_*.summary.json"))
    nm_r = nm_u = nm_i = 0
    for sf in nm_files:
        try:
            with open(sf) as fh: s = json.load(fh)
            nm_r += s.get("resolved_instances", 0)
            nm_u += s.get("unresolved_instances", 0)
            nm_i += s.get("incomplete_instances", 0)
        except Exception:
            pass
    nm_done = nomem_totals[inst]

    pct = f"{wm_r/10*100:.0f}%" if wm_done >= 10 else f"({wm_done}/10 done)"
    nm_pct = f"{nm_r/nm_done*100:.0f}%" if nm_done > 0 else "?"
    delta = f"+{wm_r - nm_r}" if wm_r >= nm_r else str(wm_r - nm_r)

    short = inst.replace("__", "/").replace("sympy-", "sy-").replace("astropy-", "ap-")
    print(f"\n  {inst}")
    print(f"    with_mem: {wm_r:2d}R {wm_u:2d}U {wm_i:2d}I / {wm_done:2d}   {pct}")
    print(f"    nomem:    {nm_r:2d}R {nm_u:2d}U {nm_i:2d}I / {nm_done:2d}   {nm_pct}  (Δ {delta}R)")

    total_wm_r += wm_r; total_wm_u += wm_u; total_wm_i += wm_i; total_wm_done += wm_done
    total_nm_r += nm_r; total_nm_total += nm_done

print(f"\n{'─'*70}")
print(f"  TOTAL with_mem : {total_wm_r:2d}R {total_wm_u:2d}U {total_wm_i:2d}I / {total_wm_done:2d} attempts")
print(f"  TOTAL nomem    : {total_nm_r:2d}R / {total_nm_total:2d} attempts")
delta_total = total_wm_r - total_nm_r
print(f"  Delta          : {'+' if delta_total>=0 else ''}{delta_total}R")

# tmux session check
import subprocess
tag = os.path.basename(run_root)
sanitized = ''.join(c if c.isalnum() or c=='_' else '_' for c in tag)
session = f"{sanitized}_wm"
try:
    r = subprocess.run(["tmux", "has-session", "-t", session], capture_output=True)
    running = r.returncode == 0
except Exception:
    running = False
print(f"\n  tmux [{session}]: {'RUNNING' if running else 'STOPPED/DONE'}")

exit_file = f"{run_root}/orchestrator_state/withmem_only.exit"
if os.path.exists(exit_file):
    code = open(exit_file).read().strip()
    print(f"  exit code: {code}")
print(f"{'='*70}")
PYEOF
