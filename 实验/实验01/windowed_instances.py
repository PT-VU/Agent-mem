#!/usr/bin/env python3
"""Utilities for SWE-bench Lite windowed execution and resume.

This script is intentionally standalone so bash wrappers can query:
- full ordered instance list (id + image)
- first missing instance index for resume
- image/id list for an index range
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from swerex.deployment.config import DockerDeploymentConfig
from sweagent.run.batch_instances import SWEBenchInstances


def _generate_cache(subset: str, split: str) -> list[dict[str, str | int]]:
    src = SWEBenchInstances(
        subset=subset,  # type: ignore[arg-type]
        split=split,  # type: ignore[arg-type]
        deployment=DockerDeploymentConfig(image="python:3.11"),
    )
    instances = src.get_instance_configs()
    rows: list[dict[str, str | int]] = []
    for idx, inst in enumerate(instances):
        rows.append(
            {
                "index": idx,
                "id": inst.problem_statement.id,
                "image": str(inst.env.deployment.image),
            }
        )
    return rows


def _load_cache(cache_file: Path) -> list[dict[str, str | int]]:
    return json.loads(cache_file.read_text(encoding="utf-8"))


def _instance_done(output_dir: Path, instance_id: str) -> bool:
    traj = output_dir / instance_id / f"{instance_id}.traj"
    if not traj.exists():
        return False
    try:
        obj = json.loads(traj.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(obj.get("info", {}).get("exit_status"))


def cmd_cache(args: argparse.Namespace) -> int:
    rows = _generate_cache(args.subset, args.split)
    args.cache_file.parent.mkdir(parents=True, exist_ok=True)
    args.cache_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.cache_file)
    print(f"total={len(rows)}")
    return 0


def cmd_total(args: argparse.Namespace) -> int:
    rows = _load_cache(args.cache_file)
    print(len(rows))
    return 0


def cmd_range(args: argparse.Namespace) -> int:
    rows = _load_cache(args.cache_file)
    start = max(0, args.start)
    end = min(len(rows), args.end)
    key = args.field
    out = [str(row[key]) for row in rows[start:end]]
    if args.unique:
        out = sorted(set(out))
    for item in out:
        print(item)
    return 0


def cmd_pending_range(args: argparse.Namespace) -> int:
    rows = _load_cache(args.cache_file)
    start = max(0, args.start)
    end = min(len(rows), args.end)
    key = args.field
    out: list[str] = []
    for row in rows[start:end]:
        instance_id = str(row["id"])
        if _instance_done(args.output_dir, instance_id):
            continue
        out.append(str(row[key]))
    if args.unique:
        out = sorted(set(out))
    for item in out:
        print(item)
    return 0


def cmd_done_count(args: argparse.Namespace) -> int:
    rows = _load_cache(args.cache_file)
    done = 0
    for row in rows:
        instance_id = str(row["id"])
        if _instance_done(args.output_dir, instance_id):
            done += 1
    print(done)
    return 0


def cmd_first_missing(args: argparse.Namespace) -> int:
    rows = _load_cache(args.cache_file)
    first_idx = len(rows)
    first_id = ""
    for row in rows:
        idx = int(row["index"])
        instance_id = str(row["id"])
        if not _instance_done(args.output_dir, instance_id):
            first_idx = idx
            first_id = instance_id
            break
    print(json.dumps({"index": first_idx, "id": first_id, "total": len(rows)}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cache = sub.add_parser("cache")
    p_cache.add_argument("--subset", default="lite")
    p_cache.add_argument("--split", default="test")
    p_cache.add_argument("--cache-file", type=Path, required=True)
    p_cache.set_defaults(func=cmd_cache)

    p_total = sub.add_parser("total")
    p_total.add_argument("--cache-file", type=Path, required=True)
    p_total.set_defaults(func=cmd_total)

    p_range = sub.add_parser("range")
    p_range.add_argument("--cache-file", type=Path, required=True)
    p_range.add_argument("--start", type=int, required=True)
    p_range.add_argument("--end", type=int, required=True)
    p_range.add_argument("--field", choices=["id", "image"], required=True)
    p_range.add_argument("--unique", action="store_true")
    p_range.set_defaults(func=cmd_range)

    p_pending_range = sub.add_parser("pending-range")
    p_pending_range.add_argument("--cache-file", type=Path, required=True)
    p_pending_range.add_argument("--start", type=int, required=True)
    p_pending_range.add_argument("--end", type=int, required=True)
    p_pending_range.add_argument("--field", choices=["id", "image"], required=True)
    p_pending_range.add_argument("--output-dir", type=Path, required=True)
    p_pending_range.add_argument("--unique", action="store_true")
    p_pending_range.set_defaults(func=cmd_pending_range)

    p_done = sub.add_parser("done-count")
    p_done.add_argument("--cache-file", type=Path, required=True)
    p_done.add_argument("--output-dir", type=Path, required=True)
    p_done.set_defaults(func=cmd_done_count)

    p_missing = sub.add_parser("first-missing")
    p_missing.add_argument("--cache-file", type=Path, required=True)
    p_missing.add_argument("--output-dir", type=Path, required=True)
    p_missing.set_defaults(func=cmd_first_missing)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
