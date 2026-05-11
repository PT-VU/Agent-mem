#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_BASE_DIR = Path(
    "/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/final_validation"
)


@dataclass
class RunProgress:
    label: str
    health: str
    current_case_index: int
    total_cases: int
    current_instance_id: str
    current_repo: str
    current_attempt: int
    total_attempts: int
    current_step: int
    resolved: int
    unresolved: int
    incomplete: int
    pending: int
    done: int
    last_update_age_sec: int | None


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _run_is_completed(run_root: Path) -> bool:
    state_dir = run_root / "orchestrator_state"
    return (state_dir / "same_problem.done.ok").exists() and (state_dir / "cross_problem.done.ok").exists()


def _run_has_live_slot(run_root: Path) -> bool:
    slot_root = run_root / "resource_slots"
    if not slot_root.exists():
        return False
    candidate_roots = [slot_root] + [p for p in slot_root.iterdir() if p.is_dir()]
    for slot_dir in candidate_roots:
        for slot in slot_dir.iterdir():
            if not slot.is_dir():
                continue
            pid_file = slot / "pid"
            if not pid_file.exists():
                continue
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
                os.kill(pid, 0)
                return True
            except Exception:
                continue
    return False


def _run_last_activity(run_root: Path) -> float:
    candidates = [
        _max_mtime_under(run_root / "resource_slots"),
        _max_mtime_under(run_root / "orchestrator_logs"),
        _max_mtime_under(run_root / "same_problem"),
        _max_mtime_under(run_root / "cross_problem"),
        _max_mtime_under(run_root / "orchestrator_state"),
    ]
    filtered = [x for x in candidates if x is not None]
    if filtered:
        return max(filtered)
    return run_root.stat().st_mtime


def _phase_rank(path: Path) -> int:
    for part in path.parts:
        lower = part.lower()
        if lower.startswith("phase") and lower[5:].isdigit():
            return int(lower[5:])
    return -1


def _looks_like_run_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(
        (path / child).exists()
        for child in (
            "orchestrator_state",
            "orchestrator_logs",
            "same_problem",
            "cross_problem",
            "resource_slots",
        )
    )


def _collect_run_roots(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    if _looks_like_run_root(base_dir):
        return [base_dir]
    runs: list[Path] = []
    for path in base_dir.rglob("*"):
        if _looks_like_run_root(path):
            runs.append(path)
    return runs


def _resolve_run_root(run_root: str | None, base_dir: Path) -> Path:
    if run_root:
        return Path(run_root).resolve()
    runs = _collect_run_roots(base_dir)
    if not runs:
        raise SystemExit(f"no run directories found under {base_dir}")

    def sort_key(path: Path) -> tuple[int, int, float]:
        return (_phase_rank(path), int(_run_has_live_slot(path)), _run_last_activity(path))

    live_runs = [p for p in runs if _run_has_live_slot(p)]
    if live_runs:
        return max(live_runs, key=sort_key)

    incomplete_runs = [p for p in runs if not _run_is_completed(p)]
    if incomplete_runs:
        return max(incomplete_runs, key=sort_key)

    return max(runs, key=sort_key)


def _load_instance_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    payload = _load_json(path)
    if isinstance(payload, dict):
        ids = payload.get("instance_ids")
        if isinstance(ids, list):
            return [str(x) for x in ids if str(x).strip()]
    if isinstance(payload, list):
        return [str(x) for x in payload if str(x).strip()]
    return []


def _load_same_instance_ids(run_root: Path) -> list[str]:
    candidates = [
        run_root / "same_instances.json",
        run_root / "orchestrator_state" / "same_instances.json",
        run_root / "same_problem" / "nomem" / "cache" / "instance_ids.json",
        run_root / "same_problem" / "with_mem" / "instance_ids.json",
    ]
    for path in candidates:
        ids = _load_instance_ids(path)
        if ids:
            return ids
    return []


def _max_mtime_under(root: Path) -> float | None:
    if not root.exists():
        return None
    mtimes: list[float] = []
    try:
        for path in root.rglob("*"):
            try:
                mtimes.append(path.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        return None
    if not mtimes:
        try:
            return root.stat().st_mtime
        except OSError:
            return None
    return max(mtimes)


def _age_seconds(ts: float | None) -> int | None:
    if ts is None:
        return None
    return max(0, int(time.time() - ts))


def _format_age(age: int | None) -> str:
    if age is None:
        return "-"
    mins, sec = divmod(age, 60)
    hour, mins = divmod(mins, 60)
    if hour:
        return f"{hour}h{mins:02d}m"
    if mins:
        return f"{mins}m{sec:02d}s"
    return f"{sec}s"


def _read_step(traj_path: Path, event_logs: list[Path]) -> int:
    step = 0
    traj = _load_json(traj_path)
    if isinstance(traj, dict):
        trajectory = traj.get("trajectory")
        if isinstance(trajectory, list):
            step = max(step, len(trajectory))
    for event_log in event_logs:
        if not event_log.exists():
            continue
        try:
            for raw in event_log.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not raw.strip():
                    continue
                row = json.loads(raw)
                payload = row.get("payload")
                if isinstance(payload, dict):
                    step_idx = payload.get("step_index")
                    if isinstance(step_idx, int):
                        step = max(step, step_idx)
        except Exception:
            continue
    return step


def _summary_outcome(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict):
        return "pending"
    if int(summary.get("resolved_instances", 0) or 0) > 0:
        return "resolved"
    if int(summary.get("incomplete_instances", 0) or 0) > 0:
        return "incomplete"
    if int(summary.get("submitted_instances", 0) or 0) > 0 or "resolved_instances" in summary:
        return "unresolved"
    return "pending"


def _attempt_execution_complete(attempt_dir: Path, instance_id: str) -> bool:
    if not attempt_dir.exists():
        return False
    if (attempt_dir / "run_batch_exit_statuses.yaml").exists():
        return True
    if (attempt_dir / "preds.json").exists():
        return True
    instance_dir = attempt_dir / instance_id
    return (instance_dir / f"{instance_id}.traj").exists() and (instance_dir / f"{instance_id}.pred").exists()


def _slot_status(slot_dir: Path) -> list[str]:
    rows: list[str] = []
    if not slot_dir.exists():
        return rows
    for slot in sorted(p for p in slot_dir.iterdir() if p.is_dir()):
        pid_file = slot / "pid"
        if not pid_file.exists():
            rows.append(f"{slot.name}:empty")
            continue
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            rows.append(f"{slot.name}:pid={pid} running")
        except Exception:
            rows.append(f"{slot.name}:stale")
    return rows


def _render_slot_groups(resource_root: Path) -> list[str]:
    if not resource_root.exists():
        return ["重资源槽位: -"]
    child_dirs = [p for p in resource_root.iterdir() if p.is_dir()]
    if not child_dirs:
        return ["重资源槽位: -"]
    if any(child.name.startswith("slot_") for child in child_dirs):
        rows = _slot_status(resource_root)
        return ["重资源槽位: " + (", ".join(rows) if rows else "-")]

    lines: list[str] = []
    for child in sorted(child_dirs):
        rows = _slot_status(child)
        if child.name == "same":
            label = "同题槽位"
        elif child.name == "cross":
            label = "跨题槽位"
        elif child.name == "heavy":
            label = "重资源槽位"
        else:
            label = f"{child.name} 槽位"
        lines.append(f"{label}: " + (", ".join(rows) if rows else "-"))
    return lines


def _branch_health(expected_done: int, done_count: int, started: bool, age_sec: int | None, stale_sec: int) -> str:
    if expected_done > 0 and done_count >= expected_done:
        return "completed"
    if not started:
        return "pending"
    if age_sec is None:
        return "running"
    return "running" if age_sec <= stale_sec else "stalled"


def _same_nomem_progress(run_root: Path, same_repeats: int, stale_sec: int) -> RunProgress:
    root = run_root / "same_problem" / "nomem"
    ids = _load_same_instance_ids(run_root)
    resolved = unresolved = incomplete = 0
    done = 0
    current_attempt = 0
    current_step = 0
    current_state = "pending"
    branch_started = False
    current_case_index = 0
    instance_id = "-"

    for idx, iid in enumerate(ids, start=1):
        for attempt in range(1, same_repeats + 1):
            tag = f"{attempt:02d}"
            summary_path = root / "metrics" / "attempt_summaries" / f"{iid}.attempt_{tag}.summary.json"
            attempt_dir = root / "outputs" / iid / f"attempt_{tag}"
            log_path = root / "logs" / iid / f"attempt_{tag}.log"
            summary = _load_json(summary_path) if summary_path.exists() else None
            outcome = _summary_outcome(summary if isinstance(summary, dict) else None)
            exec_complete = _attempt_execution_complete(attempt_dir, iid)
            if outcome == "resolved":
                resolved += 1
                done += 1
                branch_started = True
            elif outcome == "unresolved":
                unresolved += 1
                done += 1
                branch_started = True
            elif outcome == "incomplete":
                incomplete += 1
                done += 1
                branch_started = True
            elif exec_complete:
                done += 1
                branch_started = True
            else:
                branch_started = branch_started or attempt_dir.exists() or log_path.exists()
            if current_state == "pending":
                if outcome == "pending" and not exec_complete and (attempt_dir.exists() or log_path.exists()):
                    current_case_index = idx
                    instance_id = iid
                    current_attempt = attempt
                    current_state = "running"
                elif outcome != "pending" or exec_complete:
                    current_case_index = idx
                    instance_id = iid
                    current_attempt = attempt

    if current_state == "running" and instance_id != "-":
        tag = f"{current_attempt:02d}"
        traj = root / "outputs" / instance_id / f"attempt_{tag}" / instance_id / f"{instance_id}.traj"
        event_log = root / "logs" / instance_id / f"attempt_{tag}.jsonl"
        current_step = _read_step(traj, [event_log])
    elif ids and done > 0:
        current_case_index = current_case_index or len(ids)
        instance_id = instance_id if instance_id != "-" else ids[min(len(ids), max(1, current_case_index)) - 1]

    last_age = _age_seconds(_max_mtime_under(root))
    total_cases = len(ids)
    expected_done = total_cases * same_repeats if total_cases else same_repeats
    pending = max(0, expected_done - done)
    if total_cases == 0:
        current_case_index = 0
    return RunProgress(
        label="same/no_mem",
        health=_branch_health(expected_done, done, branch_started, last_age, stale_sec),
        current_case_index=current_case_index,
        total_cases=total_cases,
        current_instance_id=instance_id,
        current_repo="-",
        current_attempt=current_attempt,
        total_attempts=same_repeats,
        current_step=current_step,
        resolved=resolved,
        unresolved=unresolved,
        incomplete=incomplete,
        pending=pending,
        done=done,
        last_update_age_sec=last_age,
    )


def _resolve_same_v21_root(run_root: Path) -> Path | None:
    same_root = run_root / "same_problem"
    new_root = same_root / "with_mem"
    if new_root.exists():
        return new_root
    if not same_root.exists():
        return None
    candidates = [p for p in same_root.iterdir() if p.is_dir() and p.name != "nomem"]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _same_v21_progress(run_root: Path, same_repeats: int, stale_sec: int) -> RunProgress:
    root = _resolve_same_v21_root(run_root)
    if root is None:
      ids = _load_same_instance_ids(run_root)
      return RunProgress("same/with_mem", "pending", 0, len(ids), "-", "-", 0, same_repeats, 0, 0, 0, 0, len(ids) * same_repeats, 0, None)
    ids = _load_same_instance_ids(run_root)
    resolved = unresolved = incomplete = pending = done = 0
    current_attempt = 0
    current_state = "pending"
    branch_started = False
    current_case_index = 0
    instance_id = "-"
    current_step = 0

    if (root / "instance_ids.json").exists():
        for idx, iid in enumerate(ids, start=1):
            candidate_dir = root / iid.replace("/", "_") / "candidates" / iid
            for attempt in range(1, same_repeats + 1):
                tag = f"{attempt:02d}"
                summary_path = candidate_dir / "metrics" / "attempt_summaries" / f"{iid}.attempt_{tag}.summary.json"
                attempt_dir = candidate_dir / "outputs" / iid / f"attempt_{tag}"
                summary = _load_json(summary_path) if summary_path.exists() else None
                outcome = _summary_outcome(summary if isinstance(summary, dict) else None)
                if outcome == "resolved":
                    resolved += 1
                    done += 1
                    branch_started = True
                elif outcome == "unresolved":
                    unresolved += 1
                    done += 1
                    branch_started = True
                elif outcome == "incomplete":
                    incomplete += 1
                    done += 1
                    branch_started = True
                else:
                    pending += 1
                    branch_started = branch_started or attempt_dir.exists()
                if current_state == "pending":
                    if outcome == "pending" and attempt_dir.exists():
                        current_case_index = idx
                        instance_id = iid
                        current_attempt = attempt
                        current_state = "running"
                    elif outcome != "pending":
                        current_case_index = idx
                        instance_id = iid
                        current_attempt = attempt
            if current_state == "running":
                pass
        if current_state == "running" and instance_id != "-":
            tag = f"{current_attempt:02d}"
            candidate_dir = root / instance_id.replace("/", "_") / "candidates" / instance_id
            traj = candidate_dir / "outputs" / instance_id / f"attempt_{tag}" / instance_id / f"{instance_id}.traj"
            event_log = candidate_dir / "logs" / f"{instance_id}.attempt_{tag}.jsonl"
            current_step = _read_step(traj, [event_log])
        elif ids and done > 0:
            current_case_index = current_case_index or len(ids)
            instance_id = instance_id if instance_id != "-" else ids[min(len(ids), max(1, current_case_index)) - 1]
        total_cases = len(ids)
    else:
        selected = _load_json(root / "selected_case.json")
        if isinstance(selected, dict) and selected.get("instance_id"):
            instance_id = str(selected["instance_id"])
            candidate_dir = Path(str(selected.get("candidate_dir", root / "candidates" / instance_id)))
        else:
            candidate_dirs = [p for p in (root / "candidates").iterdir() if p.is_dir()] if (root / "candidates").exists() else []
            candidate_dir = max(candidate_dirs, key=lambda p: p.stat().st_mtime) if candidate_dirs else root
            instance_id = candidate_dir.name if candidate_dir != root else "-"
        for attempt in range(1, same_repeats + 1):
            tag = f"{attempt:02d}"
            summary_path = candidate_dir / "metrics" / "attempt_summaries" / f"{instance_id}.attempt_{tag}.summary.json"
            attempt_dir = candidate_dir / "outputs" / instance_id / f"attempt_{tag}"
            summary = _load_json(summary_path) if summary_path.exists() else None
            outcome = _summary_outcome(summary if isinstance(summary, dict) else None)
            if outcome == "resolved":
                resolved += 1
                done += 1
                branch_started = True
            elif outcome == "unresolved":
                unresolved += 1
                done += 1
                branch_started = True
            elif outcome == "incomplete":
                incomplete += 1
                done += 1
                branch_started = True
            else:
                pending += 1
                branch_started = branch_started or attempt_dir.exists()
            if current_state == "pending":
                if outcome == "pending" and attempt_dir.exists():
                    current_attempt = attempt
                    current_state = "running"
                elif done:
                    current_attempt = attempt
        if current_state == "running":
            tag = f"{current_attempt:02d}"
            traj = candidate_dir / "outputs" / instance_id / f"attempt_{tag}" / instance_id / f"{instance_id}.traj"
            event_log = candidate_dir / "logs" / f"{instance_id}.attempt_{tag}.jsonl"
            current_step = _read_step(traj, [event_log])
        total_cases = 1 if instance_id != "-" else 0
        current_case_index = 1 if instance_id != "-" else 0

    last_age = _age_seconds(_max_mtime_under(root))
    expected_done = total_cases * same_repeats if total_cases else same_repeats
    return RunProgress(
        label="same/with_mem",
        health=_branch_health(expected_done, done, branch_started, last_age, stale_sec),
        current_case_index=current_case_index,
        total_cases=total_cases,
        current_instance_id=instance_id,
        current_repo="-",
        current_attempt=current_attempt,
        total_attempts=same_repeats,
        current_step=current_step,
        resolved=resolved,
        unresolved=unresolved,
        incomplete=incomplete,
        pending=pending,
        done=done,
        last_update_age_sec=last_age,
    )


def _cross_order(run_root: Path) -> list[tuple[str, list[str]]]:
    state_dir = run_root / "orchestrator_state"
    run_config = _load_json(state_dir / "run_config.json")
    configured_labels: list[str] = []
    if isinstance(run_config, dict):
        if run_config.get("cross_repo_a"):
            configured_labels.append(str(run_config["cross_repo_a"]))
        if run_config.get("cross_repo_b"):
            configured_labels.append(str(run_config["cross_repo_b"]))
    order: list[tuple[str, list[str]]] = []
    repo_a_path = state_dir / "repo_a_instances.json"
    repo_b_path = state_dir / "repo_b_instances.json"
    if repo_a_path.exists():
        order.append((repo_a_path.stem.replace("_instances", ""), _load_instance_ids(repo_a_path)))
    if repo_b_path.exists():
        order.append((repo_b_path.stem.replace("_instances", ""), _load_instance_ids(repo_b_path)))
    if order:
        remapped: list[tuple[str, list[str]]] = []
        cross_root = run_root / "cross_problem"
        labels = sorted([p.name for p in cross_root.iterdir() if p.is_dir()]) if cross_root.exists() else []
        for idx, (_, ids) in enumerate(order):
            if idx < len(configured_labels):
                label = configured_labels[idx]
            elif idx < len(labels):
                label = labels[idx]
            else:
                label = f"repo_{idx+1}"
            remapped.append((label, ids))
        return remapped
    cross_root = run_root / "cross_problem"
    rows: list[tuple[str, list[str]]] = []
    if cross_root.exists():
        for repo_dir in sorted(p for p in cross_root.iterdir() if p.is_dir()):
            cache_path = repo_dir / "nomem_fresh" / "cache" / "instance_ids.json"
            ids = _load_instance_ids(cache_path)
            rows.append((repo_dir.name, ids))
    return rows


def _cross_branch_progress(run_root: Path, branch_name: str, subdir_name: str, stale_sec: int, feedback_required: bool) -> RunProgress:
    order = _cross_order(run_root)
    total_cases = sum(len(ids) for _, ids in order)
    resolved = unresolved = incomplete = pending = done = 0
    current_instance = "-"
    current_repo = "-"
    current_case_index = 0
    current_step = 0
    global_index = 0
    branch_started = False
    last_age_candidates: list[int] = []

    for repo, ids in order:
        root = run_root / "cross_problem" / repo / subdir_name
        root_age = _age_seconds(_max_mtime_under(root))
        if root_age is not None:
            last_age_candidates.append(root_age)
        for iid in ids:
            global_index += 1
            summary_path = root / "metrics" / "attempt_summaries" / f"{iid}.attempt_01.summary.json"
            feedback_path = root / "metrics" / "attempt_feedback" / f"{iid}.attempt_01.feedback.json"
            output_dir = root / "outputs" / iid / "attempt_01"
            summary = _load_json(summary_path) if summary_path.exists() else None
            outcome = _summary_outcome(summary if isinstance(summary, dict) else None)
            if feedback_required and summary_path.exists() and not feedback_path.exists():
                outcome = "pending"
            if outcome == "resolved":
                resolved += 1
                done += 1
            elif outcome == "unresolved":
                unresolved += 1
                done += 1
            elif outcome == "incomplete":
                incomplete += 1
                done += 1
            else:
                pending += 1
            if outcome == "pending":
                if output_dir.exists() and current_instance == "-":
                    current_instance = iid
                    current_repo = repo
                    current_case_index = global_index
                    traj = output_dir / iid / f"{iid}.traj"
                    if subdir_name == "nomem_fresh":
                        event_logs = [root / "logs" / iid / "attempt_01.jsonl"]
                    else:
                        event_logs = [root / "logs" / f"{iid}.attempt_01.jsonl"]
                    current_step = _read_step(traj, event_logs)
                branch_started = branch_started or output_dir.exists()
            else:
                branch_started = True

    if current_instance == "-" and done > 0:
        global_index = 0
        for repo, ids in order:
            for iid in ids:
                global_index += 1
                root = run_root / "cross_problem" / repo / subdir_name
                summary_path = root / "metrics" / "attempt_summaries" / f"{iid}.attempt_01.summary.json"
                feedback_path = root / "metrics" / "attempt_feedback" / f"{iid}.attempt_01.feedback.json"
                if summary_path.exists() and (not feedback_required or feedback_path.exists()):
                    current_instance = iid
                    current_repo = repo
                    current_case_index = global_index
    last_age = min(last_age_candidates) if last_age_candidates else None
    return RunProgress(
        label=branch_name,
        health=_branch_health(total_cases, done, branch_started, last_age, stale_sec),
        current_case_index=current_case_index,
        total_cases=total_cases,
        current_instance_id=current_instance,
        current_repo=current_repo,
        current_attempt=1 if current_instance != "-" else 0,
        total_attempts=1,
        current_step=current_step,
        resolved=resolved,
        unresolved=unresolved,
        incomplete=incomplete,
        pending=pending,
        done=done,
        last_update_age_sec=last_age,
    )


def _render_progress(p: RunProgress) -> list[str]:
    return [
        p.label,
        _health_zh(p.health),
        f"{p.current_case_index}/{p.total_cases}",
        p.current_repo,
        p.current_instance_id,
        f"{p.current_attempt}/{p.total_attempts}",
        str(p.current_step),
        str(p.done),
        str(p.resolved),
        str(p.unresolved),
        str(p.incomplete),
        str(p.pending),
        _format_age(p.last_update_age_sec),
    ]


def _health_zh(value: str) -> str:
    mapping = {
        "pending": "未开始",
        "running": "运行中",
        "stalled": "疑似卡住",
        "completed": "已完成",
        "failed": "失败",
    }
    return mapping.get(value, value)


def _render_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def fmt(row: list[str]) -> str:
        return " | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row))

    sep = "-+-".join("-" * w for w in widths)
    lines = [fmt(headers), sep]
    lines.extend(fmt(row) for row in rows)
    return lines


def _orchestrator_health(run_root: Path, stale_sec: int) -> str:
    state_dir = run_root / "orchestrator_state"
    same_done = (state_dir / "same_problem.done.ok").exists()
    cross_done = (state_dir / "cross_problem.done.ok").exists()
    same_exit = (state_dir / "same_problem.exit")
    cross_exit = (state_dir / "cross_problem.exit")
    if same_done and cross_done:
        return "completed"
    if any(path.exists() and path.read_text(encoding="utf-8").strip() not in {"0", ""} for path in [same_exit, cross_exit] if path.exists()):
        return "failed"
    age = _age_seconds(_max_mtime_under(run_root / "orchestrator_logs"))
    return "running" if age is not None and age <= stale_sec else "stalled"


def _render(run_root: Path, same_repeats: int, stale_sec: int) -> str:
    lines: list[str] = []
    lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"运行目录: {run_root}")
    lines.append(f"总控状态: {_health_zh(_orchestrator_health(run_root, stale_sec))}")

    lines.extend(_render_slot_groups(run_root / "resource_slots"))
    lines.append("")

    same_nomem = _same_nomem_progress(run_root, same_repeats, stale_sec)
    same_v21 = _same_v21_progress(run_root, same_repeats, stale_sec)
    cross_nomem = _cross_branch_progress(run_root, "cross/no_mem", "nomem_fresh", stale_sec, feedback_required=False)
    cross_v21 = _cross_branch_progress(run_root, "cross/with_mem", "v21_carryover", stale_sec, feedback_required=True)

    progress_headers = [
        "分支",
        "健康状态",
        "当前实例序号",
        "Repo/Topic",
        "当前实例",
        "当前尝试",
        "当前Step",
        "已完成",
        "成功",
        "失败",
        "不完整",
        "待处理",
        "最近更新",
    ]
    progress_rows = [
        _render_progress(same_nomem),
        _render_progress(same_v21),
        _render_progress(cross_nomem),
        _render_progress(cross_v21),
    ]
    progress_rows[0][0] = "同题 / NoMem"
    progress_rows[1][0] = "同题 / WithMem"
    progress_rows[2][0] = "跨题 / NoMem"
    progress_rows[3][0] = "跨题 / WithMem"
    lines.append("总览表")
    lines.extend(_render_table(progress_headers, progress_rows))
    lines.append("")

    order = _cross_order(run_root)
    if order:
        lines.append("跨题 Repo/Topic 统计")
        repo_rows: list[list[str]] = []
        for repo, ids in order:
            nomem_root = run_root / "cross_problem" / repo / "nomem_fresh" / "metrics" / "attempt_summaries"
            v21_root = run_root / "cross_problem" / repo / "v21_carryover" / "metrics" / "attempt_summaries"
            nomem_resolved = nomem_unresolved = nomem_incomplete = 0
            v21_resolved = v21_unresolved = v21_incomplete = 0
            for iid in ids:
                nsum = _load_json(nomem_root / f"{iid}.attempt_01.summary.json")
                vsum = _load_json(v21_root / f"{iid}.attempt_01.summary.json")
                nout = _summary_outcome(nsum if isinstance(nsum, dict) else None)
                vout = _summary_outcome(vsum if isinstance(vsum, dict) else None)
                if nout == "resolved":
                    nomem_resolved += 1
                elif nout == "unresolved":
                    nomem_unresolved += 1
                elif nout == "incomplete":
                    nomem_incomplete += 1
                if vout == "resolved":
                    v21_resolved += 1
                elif vout == "unresolved":
                    v21_unresolved += 1
                elif vout == "incomplete":
                    v21_incomplete += 1
            repo_rows.append(
                [
                    repo,
                    str(len(ids)),
                    str(nomem_resolved),
                    str(nomem_unresolved),
                    str(nomem_incomplete),
                    str(v21_resolved),
                    str(v21_unresolved),
                    str(v21_incomplete),
                ]
            )
        lines.extend(
            _render_table(
                ["Repo/Topic", "题目数", "NoMem成功", "NoMem失败", "NoMem不完整", "WithMem成功", "WithMem失败", "WithMem不完整"],
                repo_rows,
            )
        )

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Monitor phase7 final validation run.")
    ap.add_argument("--run-root", default=None)
    ap.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    ap.add_argument("--same-repeats", type=int, default=10)
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--stale-sec", type=int, default=900)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Render one snapshot and exit.")
    mode.add_argument("--watch", action="store_true", help="Continuously refresh the monitor output.")
    args = ap.parse_args()

    run_root = _resolve_run_root(args.run_root, Path(args.base_dir))
    watch_mode = args.watch or not args.once
    while True:
        content = _render(run_root, args.same_repeats, args.stale_sec)
        if not watch_mode:
            print(content)
            return 0
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write(content + "\n")
        sys.stdout.flush()
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
