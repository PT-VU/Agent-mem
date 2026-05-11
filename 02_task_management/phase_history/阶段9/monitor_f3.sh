#!/usr/bin/env bash
# Usage: bash monitor_f3.sh <RUN_ROOT>
# 监控 F3 9实例 nomem+with_mem 双模式实验进度

RUN_ROOT="${1:?Usage: $0 <RUN_ROOT>}"

python3 << PYEOF
import json, glob, os, datetime, subprocess

RUN_ROOT = "${RUN_ROOT}"
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

instances = [
    "django__django-12284",
    "django__django-16139",
    "django__django-12497",
    "sympy__sympy-24066",
    "sympy__sympy-13031",
    "sympy__sympy-13551",
    "astropy__astropy-12907",
    "astropy__astropy-14995",
    "astropy__astropy-13033",
]

def read_eval_reports(pattern):
    """读 official_eval.json (with_mem路径格式)"""
    files = sorted(glob.glob(pattern))
    r = u = i = 0
    for f in files:
        try:
            d = json.load(open(f))
            if d.get('resolved_ids'):   r += 1
            elif d.get('unresolved_ids'): u += 1
            else:                          i += 1
        except: pass
    return r, u, i, len(files)

def read_summaries(pattern):
    """读 attempt_summaries/*.summary.json (nomem路径格式)"""
    files = sorted(glob.glob(pattern))
    r = u = i = 0
    for f in files:
        try:
            d = json.load(open(f))
            r += d.get('resolved_instances', 0)
            u += d.get('unresolved_instances', 0)
            i += d.get('incomplete_instances', 0)
        except: pass
    return r, u, i, len(files)

print(f"{'='*72}")
print(f"  F3 进度监控   {now}")
print(f"  run: {os.path.basename(RUN_ROOT)}")
print(f"{'='*72}")
print(f"  {'实例':<40} {'with_mem':>20}   {'nomem':>20}")
print(f"  {'-'*40} {'-'*20}   {'-'*20}")

tot_wm_r=tot_wm_u=tot_wm_i=tot_wm_done=0
tot_nm_r=tot_nm_u=tot_nm_i=tot_nm_done=0

for inst in instances:
    # with_mem: official_eval.json路径
    wm_pat = f"{RUN_ROOT}/same_problem/with_mem/{inst}/candidates/{inst}/metrics/attempt_reports/{inst}.attempt_*.official_eval.json"
    wm_r, wm_u, wm_i, wm_done = read_eval_reports(wm_pat)

    # nomem: attempt_summaries路径
    nm_pat = f"{RUN_ROOT}/same_problem/nomem/metrics/attempt_summaries/{inst}.attempt_*.summary.json"
    nm_r, nm_u, nm_i, nm_done = read_summaries(nm_pat)

    wm_str = f"{wm_r}R {wm_u}U {wm_i}I /{wm_done:3d}"
    nm_str = f"{nm_r}R {nm_u}U {nm_i}I /{nm_done:3d}"
    delta = wm_r - nm_r
    flag = f"  Δ{'+' if delta>=0 else ''}{delta}R"

    short = inst.split('__')[1][:32]
    print(f"  {short:<40} {wm_str:>20}   {nm_str:>20}{flag}")

    tot_wm_r+=wm_r; tot_wm_u+=wm_u; tot_wm_i+=wm_i; tot_wm_done+=wm_done
    tot_nm_r+=nm_r; tot_nm_u+=nm_u; tot_nm_i+=nm_i; tot_nm_done+=nm_done

print(f"  {'─'*72}")
wm_pct = f"{tot_wm_r/tot_wm_done*100:.0f}%" if tot_wm_done else "—"
nm_pct = f"{tot_nm_r/tot_nm_done*100:.0f}%" if tot_nm_done else "—"
print(f"  {'合计':<40} {f'{tot_wm_r}R {tot_wm_u}U {tot_wm_i}I /{tot_wm_done}':>20}   {f'{tot_nm_r}R {tot_nm_u}U {tot_nm_i}I /{tot_nm_done}':>20}")
print(f"  {'解出率':<40} {wm_pct:>20}   {nm_pct:>20}")
print(f"  {'进度':<40} {f'{tot_wm_done}/90':>20}   {f'{tot_nm_done}/90':>20}")

# tmux状态
tag = os.path.basename(RUN_ROOT)
sanitized = ''.join(c if c.isalnum() or c=='_' else '_' for c in tag)
main_session = f"{sanitized}_main"
try:
    rc = subprocess.run(["tmux","has-session","-t",main_session],capture_output=True).returncode
    running = rc == 0
except: running = False

exit_f = f"{RUN_ROOT}/orchestrator_state/main.exit"
exit_code = open(exit_f).read().strip() if os.path.exists(exit_f) else "—"
print(f"\n  tmux [{main_session}]: {'🟢 RUNNING' if running else '🔴 STOPPED'}")
if exit_code != "—": print(f"  exit code: {exit_code}")
print(f"{'='*72}")
PYEOF
