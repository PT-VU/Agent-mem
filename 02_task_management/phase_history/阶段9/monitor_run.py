#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段9-v2 实验监控器

用法:
    python3 monitor_run.py                       # 自动盯所有 phase9_v2 RUN_ROOT
    python3 monitor_run.py --once                # 只渲染一次
    python3 monitor_run.py --refresh 3           # 每 3 秒刷新
    python3 monitor_run.py --root <RUN_ROOT>     # 只看一个 RUN_ROOT
    python3 monitor_run.py --parent <DIR>        # 自定义 RUN_ROOT 父目录
    python3 monitor_run.py --all                 # 显示所有 RUN_ROOT（含已结束）
    python3 monitor_run.py --include-finished    # 把已收尾的 attempt 也展开（默认折叠）

显示字段：
    case · attempt · step · status · resolved · incomplete · tokens(in/out) · cost · last_activity

数据源：
    metrics/attempt_summaries/<inst>.attempt_NN.summary.json   → resolved / incomplete
    <attempt_dir>/<inst>/<inst>.traj                            → tokens · cost · api_calls (attempt 结束后)
    <inst>.attempt_NN.jsonl 或 attempt_NN.jsonl                → 实时 step (count plan_generated events)
    attempt 目录下所有文件的 max mtime                            → last_activity
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_PARENT = Path(
    "/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase9_v2"
)
LEGACY_PARENT = Path(
    "/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation/phase9"
)
GROUPS = ("nomem", "with_mem")
ATTEMPT_RE = re.compile(r"^attempt_(\d+)$")


# ---------- ANSI ----------
def supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("TERM", "") not in {"dumb", ""}


C_RESET = "\033[0m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"
C_GREY = "\033[90m"


def color(s: str, c: str) -> str:
    if not supports_color():
        return s
    return f"{c}{s}{C_RESET}"


def clear_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
    else:
        sys.stdout.write("\n" + "=" * 80 + "\n")


# ---------- helpers ----------
def fmt_int(n: int) -> str:
    return f"{n:,}"


def fmt_age(seconds: float) -> str:
    if seconds < 0:
        return "?"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h{m:02d}m"


def newest_mtime(root: Path) -> float:
    best = 0.0
    try:
        for p in root.rglob("*"):
            try:
                m = p.stat().st_mtime
                if m > best:
                    best = m
            except OSError:
                pass
    except OSError:
        pass
    return best


def safe_load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def count_jsonl_events(path: Path, target_event: str = "plan_generated") -> int:
    if not path.exists():
        return 0
    n = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                # 该 jsonl 是 sweagent 的事件流 (BaselineLoggingHook 也写入)
                # 字符串扫描足够，无需 json.loads（性能更好）
                if f'"event": "{target_event}"' in line or f'"event":"{target_event}"' in line:
                    n += 1
    except OSError:
        pass
    return n


def attempt_paths_nomem(run_root: Path, inst: str, n: int) -> dict:
    """nomem 一组的目录布局。"""
    safe_n = f"attempt_{n:02d}"
    base_outputs = run_root / "same_problem" / "nomem" / "outputs" / inst / safe_n
    return {
        "outputs_dir": base_outputs,
        "instance_subdir": base_outputs / inst,
        "summary": run_root / "same_problem" / "nomem" / "metrics" / "attempt_summaries" / f"{inst}.{safe_n}.summary.json",
        "official_eval": run_root / "same_problem" / "nomem" / "metrics" / "attempt_reports" / f"{inst}.{safe_n}.official_eval.json",
        "events_jsonl": run_root / "same_problem" / "nomem" / "logs" / inst / f"{safe_n}.jsonl",
    }


def attempt_paths_withmem(run_root: Path, inst: str, n: int) -> dict:
    """with_mem 一组的目录布局（多一层 candidates/<inst>/）。"""
    safe_n = f"attempt_{n:02d}"
    cand = run_root / "same_problem" / "with_mem" / inst / "candidates" / inst
    base_outputs = cand / "outputs" / inst / safe_n
    return {
        "outputs_dir": base_outputs,
        "instance_subdir": base_outputs / inst,
        "summary": cand / "metrics" / "attempt_summaries" / f"{inst}.{safe_n}.summary.json",
        "official_eval": cand / "metrics" / "attempt_reports" / f"{inst}.{safe_n}.official_eval.json",
        "events_jsonl": cand / "logs" / f"{inst}.{safe_n}.jsonl",
        "feedback": cand / "metrics" / "attempt_feedback" / f"{inst}.{safe_n}.feedback.json",
    }


@dataclass
class AttemptStat:
    group: str
    instance: str
    attempt: int
    step: int = 0
    status: str = "pending"  # pending | running | resolved | unresolved | incomplete | submitted | error
    tokens_in: int = 0
    tokens_out: int = 0
    api_calls: int = 0
    cost: float = 0.0
    last_activity: float = 0.0  # epoch
    finished: bool = False


@dataclass
class RunStats:
    run_root: Path
    instance_ids: list[str] = field(default_factory=list)
    repeats: int = 0
    attempts: list[AttemptStat] = field(default_factory=list)
    last_resume_log_mtime: float = 0.0
    cost_progress: str = ""  # 来自 resume.tmux.log 的 ($x.xx) 进度条
    nomem_exit: str | None = None
    withmem_exit: str | None = None


# ---------- discovery ----------
def discover_run_roots(parent: Path, include_legacy: bool = False) -> list[Path]:
    roots: list[Path] = []
    parents = [parent]
    if include_legacy and LEGACY_PARENT.exists():
        parents.append(LEGACY_PARENT)
    for p in parents:
        if not p.exists():
            continue
        for child in sorted(p.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if child.is_dir() and (child / "orchestrator_state").exists():
                roots.append(child)
    return roots


def is_active(run_root: Path) -> bool:
    """RUN_ROOT 是否还在运行（双 lane 的 .exit 都没写）。"""
    e1 = run_root / "orchestrator_state" / "same_only_nomem.exit"
    e2 = run_root / "orchestrator_state" / "same_only_withmem.exit"
    return not (e1.exists() and e2.exists())


# ---------- per-RUN_ROOT scan ----------
def scan_run_root(run_root: Path) -> RunStats:
    stats = RunStats(run_root=run_root)

    # instance list
    sjson = run_root / "same_instances.json"
    if sjson.exists():
        d = safe_load_json(sjson)
        stats.instance_ids = list(d.get("instance_ids") or [])
        stats.repeats = int(d.get("repeats") or 0) or 10

    # exit codes
    e_nomem = run_root / "orchestrator_state" / "same_only_nomem.exit"
    e_with = run_root / "orchestrator_state" / "same_only_withmem.exit"
    if e_nomem.exists():
        stats.nomem_exit = e_nomem.read_text().strip()
    if e_with.exists():
        stats.withmem_exit = e_with.read_text().strip()

    # resume.tmux.log: extract latest cost progress line
    resume_log = run_root / "orchestrator_logs" / "same_only_resume.tmux.log"
    if resume_log.exists():
        try:
            stats.last_resume_log_mtime = resume_log.stat().st_mtime
            with resume_log.open("r", encoding="utf-8", errors="replace") as f:
                # 只读末尾 32KB，足够找最近的 cost 行
                f.seek(0, os.SEEK_END)
                end = f.tell()
                f.seek(max(0, end - 32 * 1024))
                tail = f.read()
            for line in reversed(tail.splitlines()):
                m = re.search(r"\(\$([0-9]+\.[0-9]+)\)", line)
                if m:
                    stats.cost_progress = f"${m.group(1)}"
                    break
        except OSError:
            pass

    # per group × instance × attempt
    for group in GROUPS:
        for inst in stats.instance_ids:
            for n in range(1, stats.repeats + 1):
                paths = attempt_paths_nomem(run_root, inst, n) if group == "nomem" else attempt_paths_withmem(run_root, inst, n)
                a = AttemptStat(group=group, instance=inst, attempt=n)

                # 是否存在 outputs 目录
                outputs_dir: Path = paths["outputs_dir"]
                instance_subdir: Path = paths["instance_subdir"]
                summary_path: Path = paths["summary"]
                official_path: Path = paths["official_eval"]
                events_path: Path = paths["events_jsonl"]

                # 状态判定
                if summary_path.exists():
                    a.finished = True
                    s = safe_load_json(summary_path)
                    # 优先级：resolved > incomplete > error > unresolved > submitted（最弱）
                    # 这是因为同一 attempt 可能同时是 submitted=1 且 unresolved=1
                    if int(s.get("resolved_instances", 0) or 0) > 0:
                        a.status = "resolved"
                    elif int(s.get("incomplete_instances", 0) or 0) > 0:
                        a.status = "incomplete"
                    elif int(s.get("error_instances", 0) or 0) > 0:
                        a.status = "error"
                    elif int(s.get("unresolved_instances", 0) or 0) > 0:
                        a.status = "unresolved"
                    elif int(s.get("submitted_instances", 0) or 0) > 0:
                        a.status = "submitted"
                    else:
                        a.status = "submitted"
                    # official eval 优先纠正：以官方测评为准
                    if official_path.exists():
                        oe = safe_load_json(official_path)
                        rids = oe.get("resolved_ids") or []
                        urids = oe.get("unresolved_ids") or 0
                        eids = oe.get("error_ids") or 0
                        iids = oe.get("incomplete_ids") or 0
                        if isinstance(rids, list) and rids:
                            a.status = "resolved"
                        elif isinstance(rids, int) and rids > 0:
                            a.status = "resolved"
                        elif (isinstance(iids, int) and iids > 0) or (isinstance(iids, list) and iids):
                            a.status = "incomplete"
                        elif (isinstance(eids, int) and eids > 0) or (isinstance(eids, list) and eids):
                            a.status = "error"
                        elif (isinstance(urids, int) and urids > 0) or (isinstance(urids, list) and urids):
                            a.status = "unresolved"
                elif outputs_dir.exists():
                    # 目录已建但没收尾 → 进行中或被打断
                    a.status = "running"
                    a.finished = False
                else:
                    a.status = "pending"

                # 实时 step（事件 jsonl 中 plan_generated 计数）
                a.step = count_jsonl_events(events_path, "plan_generated")

                # 已结束尝试：从 traj 取 token / cost
                if a.finished:
                    traj_path = instance_subdir / f"{inst}.traj"
                    if traj_path.exists():
                        try:
                            with traj_path.open("r", encoding="utf-8", errors="replace") as f:
                                # 直接 json.load
                                td = json.load(f)
                            mstats = (td.get("info") or {}).get("model_stats") or {}
                            a.tokens_in = int(mstats.get("tokens_sent", 0) or 0)
                            a.tokens_out = int(mstats.get("tokens_received", 0) or 0)
                            a.api_calls = int(mstats.get("api_calls", 0) or 0)
                            a.cost = float(mstats.get("instance_cost", 0.0) or 0.0)
                            # step 用 traj 的 trajectory 长度更稳
                            traj_steps = td.get("trajectory")
                            if isinstance(traj_steps, list) and traj_steps:
                                a.step = max(a.step, len(traj_steps))
                        except Exception:
                            pass

                # last activity（任何相关文件 mtime 最大值）
                candidates: list[Path] = [
                    outputs_dir, instance_subdir, summary_path, events_path,
                ]
                for p in candidates:
                    try:
                        if p.exists():
                            m = p.stat().st_mtime
                            if m > a.last_activity:
                                a.last_activity = m
                    except OSError:
                        pass
                # 同时考虑 instance_subdir 下文件的 mtime
                if instance_subdir.exists():
                    try:
                        for f in instance_subdir.iterdir():
                            try:
                                m = f.stat().st_mtime
                                if m > a.last_activity:
                                    a.last_activity = m
                            except OSError:
                                pass
                    except OSError:
                        pass

                stats.attempts.append(a)
    return stats


# ---------- render ----------
def status_color(status: str) -> str:
    return {
        "resolved": C_GREEN,
        "running": C_CYAN,
        "incomplete": C_YELLOW,
        "submitted": C_GREY,
        "unresolved": C_GREY,
        "error": C_RED,
        "pending": C_DIM,
    }.get(status, C_RESET)


def render(stats_list: list[RunStats], *, include_finished: bool, refresh: int) -> None:
    clear_screen()
    now = time.time()
    print(color(f"=== Phase 9-v2 monitor · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · refresh {refresh}s ===", C_BOLD))

    if not stats_list:
        print(color("(no RUN_ROOT discovered yet)", C_DIM))
        return

    for stats in stats_list:
        run_label = stats.run_root.name
        active_marker = "● ACTIVE" if is_active(stats.run_root) else "○ done"
        print()
        print(color(f"[{active_marker}] {run_label}", C_BOLD))
        print(f"  RUN_ROOT={stats.run_root}")
        print(f"  instances={stats.instance_ids}  repeats={stats.repeats}")
        log_age = now - stats.last_resume_log_mtime if stats.last_resume_log_mtime else -1
        cost_str = stats.cost_progress or "$?"
        print(f"  resume_log_age={fmt_age(log_age)}  cost={cost_str}  exit(nomem/withmem)={stats.nomem_exit}/{stats.withmem_exit}")

        # 聚合
        agg: dict[str, dict[str, int | float]] = {
            g: {"resolved": 0, "incomplete": 0, "submitted": 0, "unresolved": 0, "error": 0, "running": 0, "pending": 0,
                "tokens_in": 0, "tokens_out": 0, "api_calls": 0, "cost": 0.0}
            for g in GROUPS
        }
        for a in stats.attempts:
            row = agg[a.group]
            row[a.status] = int(row.get(a.status, 0)) + 1
            row["tokens_in"] = int(row["tokens_in"]) + a.tokens_in
            row["tokens_out"] = int(row["tokens_out"]) + a.tokens_out
            row["api_calls"] = int(row["api_calls"]) + a.api_calls
            row["cost"] = float(row["cost"]) + a.cost

        # 表头
        print()
        print(color(
            f"  {'group':<8} {'case':<26} {'att':>3} {'step':>4} {'status':<11} {'tokens(in/out)':>22} {'api':>4} {'cost':>8} {'last_act':>10}",
            C_DIM,
        ))
        for a in stats.attempts:
            if a.status == "pending" and not include_finished:
                continue
            if a.finished and not include_finished:
                # 完成的也展示，但稍微变暗
                pass
            inst_short = a.instance.replace("astropy__", "")
            tokens_str = f"{fmt_int(a.tokens_in)}/{fmt_int(a.tokens_out)}"
            cost_str = f"${a.cost:.4f}" if a.cost else "-"
            age = fmt_age(now - a.last_activity) if a.last_activity > 0 else "-"
            line = (
                f"  {a.group:<8} {inst_short:<26} {a.attempt:>3} {a.step:>4} "
                f"{a.status:<11} {tokens_str:>22} {a.api_calls:>4} {cost_str:>8} {age:>10}"
            )
            print(color(line, status_color(a.status)))

        # 聚合行
        print()
        for g in GROUPS:
            r = agg[g]
            tot = sum(int(r[k]) for k in ("resolved", "incomplete", "submitted", "unresolved", "error", "running", "pending"))
            line = (
                f"  {g:<8} resolved={int(r['resolved'])}  incomplete={int(r['incomplete'])}  "
                f"running={int(r['running'])}  pending={int(r['pending'])}  "
                f"submitted={int(r['submitted'])}  unresolved={int(r['unresolved'])}  error={int(r['error'])}  "
                f"| tokens={fmt_int(int(r['tokens_in']))}/{fmt_int(int(r['tokens_out']))}  "
                f"api={int(r['api_calls'])}  cost=${float(r['cost']):.4f}  total={tot}"
            )
            print(color(line, C_BOLD))

        # 总计
        ti = sum(int(agg[g]["tokens_in"]) for g in GROUPS)
        to = sum(int(agg[g]["tokens_out"]) for g in GROUPS)
        rs = sum(int(agg[g]["resolved"]) for g in GROUPS)
        ic = sum(int(agg[g]["incomplete"]) for g in GROUPS)
        co = sum(float(agg[g]["cost"]) for g in GROUPS)
        api = sum(int(agg[g]["api_calls"]) for g in GROUPS)
        print()
        print(color(
            f"  TOTAL    resolved={rs}  incomplete={ic}  | tokens={fmt_int(ti)}/{fmt_int(to)}  api={api}  cost=${co:.4f}",
            C_BOLD,
        ))

        # 如果 v2 events 文件存在，附加 v2 摘要
        hook_path = stats.run_root / "agent_mem_logs" / "hook_events.jsonl"
        if hook_path.exists():
            try:
                v2_counts: dict[str, int] = {}
                v2_decisions: dict[str, int] = {}
                with hook_path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            d = json.loads(line)
                        except Exception:
                            continue
                        ev = (d.get("payload") or {}).get("event") or ""
                        if ev.startswith("v2_"):
                            v2_counts[ev] = v2_counts.get(ev, 0) + 1
                            if ev == "v2_patch_consistency_gate":
                                dec = (d.get("payload") or {}).get("decision") or "?"
                                v2_decisions[dec] = v2_decisions.get(dec, 0) + 1
                if v2_counts:
                    print()
                    print(color("  v2 events:", C_CYAN))
                    for k in sorted(v2_counts):
                        extra = ""
                        if k == "v2_patch_consistency_gate" and v2_decisions:
                            extra = "  [" + " ".join(f"{kk}={vv}" for kk, vv in sorted(v2_decisions.items())) + "]"
                        print(f"    {k}: {v2_counts[k]}{extra}")
            except OSError:
                pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="Single RUN_ROOT to monitor (overrides discovery)")
    ap.add_argument("--parent", default=str(DEFAULT_PARENT), help="Parent dir under which RUN_ROOTs live")
    ap.add_argument("--all", action="store_true", help="Show all RUN_ROOTs (active and finished)")
    ap.add_argument("--include-finished", action="store_true", help="Show all attempts including pending/finished detail")
    ap.add_argument("--once", action="store_true", help="Render once and exit")
    ap.add_argument("--refresh", type=int, default=5, help="Refresh interval in seconds (default 5)")
    ap.add_argument("--include-legacy", action="store_true", help="Also scan legacy phase9/ parent")
    args = ap.parse_args()

    while True:
        roots: list[Path] = []
        if args.root:
            roots = [Path(args.root)]
        else:
            all_roots = discover_run_roots(Path(args.parent), include_legacy=args.include_legacy)
            if args.all:
                roots = all_roots
            else:
                # active 优先；如果没有 active，默认显示最近 3 个
                active = [r for r in all_roots if is_active(r)]
                roots = active if active else all_roots[:3]

        stats_list = [scan_run_root(r) for r in roots]
        render(stats_list, include_finished=args.include_finished, refresh=args.refresh)

        if args.once:
            return
        try:
            time.sleep(max(1, args.refresh))
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
