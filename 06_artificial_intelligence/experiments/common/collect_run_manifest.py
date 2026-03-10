#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_cache_ids(cache_file: Path) -> list[str]:
    if not cache_file.exists():
        return []
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [str(x) for x in data]
    return []


def _safe_git_rev(workspace_root: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(workspace_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None
    return out or None


def _load_exit_status(traj_path: Path) -> str:
    try:
        payload = json.loads(traj_path.read_text(encoding="utf-8"))
    except Exception:
        return "unreadable"
    info = payload.get("info")
    if not isinstance(info, dict):
        return "unknown"
    return str(info.get("exit_status", "unknown"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create standardized experiment manifest.")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--mode", required=True, choices=["with-mem", "no-mem"])
    parser.add_argument("--subset", required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cache-file", default="")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--stop-index", type=int, default=0)
    parser.add_argument("--run-script", default="")
    parser.add_argument("--model-config", default="")
    parser.add_argument("--event-log-glob", default="")
    parser.add_argument("--require-event-logs", action="store_true")
    parser.add_argument("--manifest-out", required=True)
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    cache_file = Path(args.cache_file).resolve() if args.cache_file else None
    manifest_out = Path(args.manifest_out).resolve()

    all_ids = _read_cache_ids(cache_file) if cache_file else []
    if all_ids and args.stop_index > 0:
        planned_ids = all_ids[args.start_index : args.stop_index]
    elif all_ids:
        planned_ids = all_ids[args.start_index :]
    else:
        planned_ids = []

    traj_paths = sorted(output_dir.glob("*/*.traj"))
    completed_ids = sorted({p.stem for p in traj_paths})
    completed_status: dict[str, str] = {p.stem: _load_exit_status(p) for p in traj_paths}
    completed_with_status = sorted(
        [iid for iid in completed_ids if completed_status.get(iid) not in {"unknown", "unreadable"}]
    )

    if planned_ids:
        pending_ids = [iid for iid in planned_ids if iid not in completed_ids]
    else:
        pending_ids = []

    planned_count = len(planned_ids) if planned_ids else len(completed_ids)
    completed_count = len(completed_with_status)
    completion_ratio = (completed_count / planned_count) if planned_count else 0.0

    event_logs: list[str] = []
    if args.event_log_glob:
        event_logs = sorted(str(p) for p in workspace_root.glob(args.event_log_glob))
    if args.require_event_logs and args.event_log_glob and not event_logs:
        print(
            f"ERROR: no event logs matched glob={args.event_log_glob}",
            flush=True,
        )
        return 1

    manifest: dict[str, Any] = {
        "schema_version": "v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": args.experiment_id,
        "mode": args.mode,
        "dataset": {
            "subset": args.subset,
            "split": args.split,
            "start_index": args.start_index,
            "stop_index": args.stop_index,
        },
        "paths": {
            "workspace_root": str(workspace_root),
            "output_dir": str(output_dir),
            "cache_file": str(cache_file) if cache_file else "",
            "run_script": args.run_script,
            "model_config": args.model_config,
            "event_logs": event_logs,
        },
        "progress": {
            "planned_instances": planned_count,
            "completed_instances": completed_count,
            "completion_ratio": round(completion_ratio, 6),
            "pending_instances": len(pending_ids),
            "pending_sample": pending_ids[:10],
            "completed_sample": completed_with_status[:10],
        },
        "git": {
            "workspace_head": _safe_git_rev(workspace_root),
        },
    }

    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(manifest_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
