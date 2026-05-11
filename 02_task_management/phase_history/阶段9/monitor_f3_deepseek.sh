#!/usr/bin/env bash
# Usage: bash monitor_f3_deepseek.sh <RUN_ROOT>
# 监控 DeepSeek V4 Pro F3 实验进度，并与 Kimi F3 对比

RUN_ROOT="${1:?Usage: $0 <RUN_ROOT>}"
KIMI_F3="/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase9_v2/phase9_f3_9inst_both_watchdog_20260506_045411"

python3 << PYEOF
import json, glob, os, datetime, subprocess

RUN_ROOT = "${RUN_ROOT}"
KIMI_F3  = "${KIMI_F3}"
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

instances = [
    "django__django-12284", "django__django-16139", "django__django-12497",
    "sympy__sympy-24066",   "sympy__sympy-13031",   "sympy__sympy-13551",
    "astropy__astropy-12907","astropy__astropy-14995","astropy__astropy-13033",
]

def read_evals(run, inst, mode):
    if mode == "with_mem":
        pat = f"{run}/same_problem/with_mem/{inst}/candidates/{inst}/metrics/attempt_reports/{inst}.attempt_*.official_eval.json"
    else:
        pat = f"{run}/same_problem/nomem/metrics/attempt_summaries/{inst}.attempt_*.summary.json"
    files = sorted(glob.glob(pat))
    r = u = i = 0
    for f in files:
        try:
            d = json.load(open(f))
            if mode == "with_mem":
                if d.get('resolved_ids'):     r += 1
                elif d.get('unresolved_ids'): u += 1
                else:                          i += 1
            else:
                r += d.get('resolved_instances', 0)
                u += d.get('unresolved_instances', 0)
                i += d.get('incomplete_instances', 0)
        except: pass
    return r, u, i, len(files)

tag = os.path.basename(RUN_ROOT)
sanitized = ''.join(c if c.isalnum() or c=='_' else '_' for c in tag)
try:
    rc = subprocess.run(["tmux","has-session","-t",f"{sanitized}_main"],capture_output=True).returncode
    running = rc == 0
except: running = False

print(f"{'='*78}")
print(f"  DeepSeek V4 Pro 进度监控   {now}")
print(f"  {'🟢 RUNNING' if running else '🔴 STOPPED'}  |  run: {os.path.basename(RUN_ROOT)}")
print(f"{'='*78}")
print(f"  {'实例':<30}  {'DS nomem':>9}  {'DS wm':>9}  {'Δ DS':>6}  ||  {'KI nomem':>9}  {'KI wm':>9}  {'Δ KI':>6}")
print(f"  {'-'*76}")

tot = {k: 0 for k in ['ds_nm_r','ds_nm_n','ds_wm_r','ds_wm_n','ki_nm_r','ki_nm_n','ki_wm_r','ki_wm_n']}

for inst in instances:
    ds_nm_r,_,_,ds_nm_n = read_evals(RUN_ROOT, inst, "nomem")
    ds_wm_r,_,_,ds_wm_n = read_evals(RUN_ROOT, inst, "with_mem")
    ki_nm_r,_,_,ki_nm_n = read_evals(KIMI_F3,  inst, "nomem")
    ki_wm_r,_,_,ki_wm_n = read_evals(KIMI_F3,  inst, "with_mem")

    ds_nm = f"{ds_nm_r}/{ds_nm_n}" if ds_nm_n else "—"
    ds_wm = f"{ds_wm_r}/{ds_wm_n}" if ds_wm_n else "—"
    ki_nm = f"{ki_nm_r}/{ki_nm_n}" if ki_nm_n else "—"
    ki_wm = f"{ki_wm_r}/{ki_wm_n}" if ki_wm_n else "—"
    ds_d  = f"{ds_wm_r-ds_nm_r:+d}" if ds_wm_n and ds_nm_n else "—"
    ki_d  = f"{ki_wm_r-ki_nm_r:+d}" if ki_wm_n and ki_nm_n else "—"

    short = inst.split('__')[1]
    print(f"  {short:<30}  {ds_nm:>9}  {ds_wm:>9}  {ds_d:>6}  ||  {ki_nm:>9}  {ki_wm:>9}  {ki_d:>6}")

    for k,v in [('ds_nm_r',ds_nm_r),('ds_nm_n',ds_nm_n),('ds_wm_r',ds_wm_r),('ds_wm_n',ds_wm_n),
                ('ki_nm_r',ki_nm_r),('ki_nm_n',ki_nm_n),('ki_wm_r',ki_wm_r),('ki_wm_n',ki_wm_n)]:
        tot[k] += v

print(f"  {'─'*76}")
ds_nm_pct = f"{tot['ds_nm_r']/tot['ds_nm_n']*100:.0f}%" if tot['ds_nm_n'] else "—"
ds_wm_pct = f"{tot['ds_wm_r']/tot['ds_wm_n']*100:.0f}%" if tot['ds_wm_n'] else "—"
ki_nm_pct = f"{tot['ki_nm_r']/tot['ki_nm_n']*100:.0f}%" if tot['ki_nm_n'] else "—"
ki_wm_pct = f"{tot['ki_wm_r']/tot['ki_wm_n']*100:.0f}%" if tot['ki_wm_n'] else "—"
print(f"  {'合计':<30}  {ds_nm_pct:>9}  {ds_wm_pct:>9}  {'':>6}  ||  {ki_nm_pct:>9}  {ki_wm_pct:>9}")
print(f"  {'进度':<30}  {tot['ds_nm_n']:>4}/90    {tot['ds_wm_n']:>4}/90  {'':>6}  ||  {tot['ki_nm_n']:>4}/90    {tot['ki_wm_n']:>4}/90")
print(f"{'='*78}")
PYEOF
