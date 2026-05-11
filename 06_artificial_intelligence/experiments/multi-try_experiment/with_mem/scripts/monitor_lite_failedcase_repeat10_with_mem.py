#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_BASE_DIR = Path(
    "/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/"
    "multi-try_experiment/with_mem/auto_selected_failedcase_runs"
)


@dataclass
class AttemptState:
    attempt: int
    status: str
    resolved: str
    step: int
    summary_path: str


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _resolve_run_root(run_root: str | None, base_dir: Path) -> Path:
    if run_root:
        return Path(run_root).resolve()
    runs = [p for p in base_dir.iterdir() if p.is_dir()] if base_dir.exists() else []
    if not runs:
        raise SystemExit(f"no run directories found under {base_dir}")
    return max(runs, key=lambda p: p.stat().st_mtime)


def _read_pid_status(run_root: Path) -> str:
    pid_file = run_root / "run.pid"
    if not pid_file.exists():
        return "pid:unknown"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        return "pid:invalid"
    try:
        os.kill(pid, 0)
        return f"pid:{pid} running"
    except OSError:
        return f"pid:{pid} stopped"


def _latest_candidate_dir(run_root: Path, selected_case: dict[str, Any] | None) -> tuple[str, Path | None]:
    if selected_case and selected_case.get("candidate_dir"):
        candidate_dir = Path(str(selected_case["candidate_dir"]))
        return str(selected_case.get("instance_id", candidate_dir.name)), candidate_dir

    candidates_root = run_root / "candidates"
    candidate_dirs = [p for p in candidates_root.iterdir() if p.is_dir()] if candidates_root.exists() else []
    if not candidate_dirs:
        return "-", None
    candidate_dir = max(candidate_dirs, key=lambda p: p.stat().st_mtime)
    return candidate_dir.name, candidate_dir


def _read_current_step(candidate_dir: Path, instance_id: str, attempt: int) -> int:
    tag = f"{attempt:02d}"
    traj_path = candidate_dir / "outputs" / instance_id / f"attempt_{tag}" / instance_id / f"{instance_id}.traj"
    event_log = candidate_dir / "logs" / f"{instance_id}.attempt_{tag}.jsonl"
    step = 0

    traj = _load_json(traj_path)
    if isinstance(traj, dict):
        trajectory = traj.get("trajectory")
        if isinstance(trajectory, list):
            step = max(step, len(trajectory))

    if event_log.exists():
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
            pass

    return step


def _attempt_states(candidate_dir: Path, instance_id: str, repeats: int) -> list[AttemptState]:
    metrics_dir = candidate_dir / "metrics"
    rows: list[AttemptState] = []
    for attempt in range(1, repeats + 1):
        tag = f"{attempt:02d}"
        summary_path = metrics_dir / "attempt_summaries" / f"{instance_id}.attempt_{tag}.summary.json"
        if summary_path.exists():
            summary = _load_json(summary_path) or {}
            resolved_instances = int(summary.get("resolved_instances", 0) or 0)
            incomplete_instances = int(summary.get("incomplete_instances", 0) or 0)
            status = "done"
            if incomplete_instances > 0:
                resolved = "incomplete"
            else:
                resolved = "resolved" if resolved_instances > 0 else "unresolved"
        else:
            attempt_dir = candidate_dir / "outputs" / instance_id / f"attempt_{tag}"
            status = "running" if attempt_dir.exists() else "pending"
            resolved = "-"
        rows.append(
            AttemptState(
                attempt=attempt,
                status=status,
                resolved=resolved,
                step=_read_current_step(candidate_dir, instance_id, attempt),
                summary_path=str(summary_path) if summary_path.exists() else "-",
            )
        )
    return rows


def _current_attempt(rows: list[AttemptState]) -> AttemptState | None:
    for row in rows:
        if row.status == "running":
            return row
    done_rows = [row for row in rows if row.status == "done"]
    if done_rows:
        return done_rows[-1]
    return None


def _render(run_root: Path, repeats: int) -> str:
    historical_candidates = _load_json(run_root / "historical_candidate_ids.json") or {}
    selected_case = _load_json(run_root / "selected_case.json")
    selection_history = _load_json(run_root / "selection_history.json") or []
    instance_id, candidate_dir = _latest_candidate_dir(run_root, selected_case if isinstance(selected_case, dict) else None)

    lines: list[str] = []
    lines.append(f"time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"run_root: {run_root}")
    lines.append(f"status: {_read_pid_status(run_root)}")
    lines.append(f"candidate_source_count: {historical_candidates.get('candidate_count', 0) if isinstance(historical_candidates, dict) else 0}")

    if isinstance(selected_case, dict) and selected_case:
        lines.append(
            "selected_case: "
            f"{selected_case.get('instance_id', '-')} "
            f"(candidate_index={selected_case.get('candidate_index', '-')})"
        )
    else:
        lines.append("selected_case: pending")

    if candidate_dir is None:
        lines.append("current_candidate: none")
        lines.append("attempts: no candidate directory yet")
    else:
        lines.append(f"current_candidate: {instance_id}")
        rows = _attempt_states(candidate_dir, instance_id, repeats)
        current = _current_attempt(rows)
        if current is None:
            lines.append("current_attempt: none")
        else:
            lines.append(
                f"current_attempt: {current.attempt:02d} "
                f"status={current.status} step={current.step} eval={current.resolved}"
            )
        lines.append("")
        lines.append("attempt history:")
        lines.append("attempt | status   | step | official_eval")
        for row in rows:
            lines.append(
                f"{row.attempt:02d}      | {row.status:<8} | {row.step:>4} | {row.resolved}"
            )

    lines.append("")
    lines.append("selection history:")
    if isinstance(selection_history, list) and selection_history:
        for row in selection_history[-10:]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- {row.get('instance_id', '-')}: decision={row.get('decision', '-')}, "
                f"first_attempt_resolved={row.get('first_attempt_resolved', '-')}"
            )
    else:
        lines.append("- no selection decisions yet")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", default=None)
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    run_root = _resolve_run_root(args.run_root, Path(args.base_dir))
    while True:
        content = _render(run_root, args.repeats)
        if args.once:
            print(content)
            return 0
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write(content + "\n")
        sys.stdout.flush()
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
