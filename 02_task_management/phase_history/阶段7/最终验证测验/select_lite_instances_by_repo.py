#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Select SWE-bench Lite instances by repo prefix.")
    ap.add_argument("--workspace-root", default="/home/pt/SWE-bench")
    ap.add_argument("--repo", required=True, help="repo prefix, e.g. astropy or django")
    ap.add_argument("--split", default="test")
    ap.add_argument("--count", type=int, default=25)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-short", action="store_true")
    args = ap.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be >= 1")
    if args.start < 0:
        raise SystemExit("--start must be >= 0")

    ws_root = Path(args.workspace_root).resolve()
    import sys

    sys.path.insert(0, str(ws_root / "SWE-agent"))
    from sweagent.run.batch_instances import SWEBenchInstances  # type: ignore

    instances = SWEBenchInstances(subset="lite", split=args.split).get_instance_configs()
    repo_prefix = f"{args.repo}__"
    matched = [inst.problem_statement.id for inst in instances if inst.problem_statement.id.startswith(repo_prefix)]
    selected = matched[args.start : args.start + args.count]
    if len(selected) < args.count and not args.allow_short:
        raise SystemExit(
            f"repo={args.repo} split={args.split} requested={args.count} start={args.start} but only {len(selected)} selected"
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subset": "lite",
        "split": args.split,
        "repo": args.repo,
        "start": args.start,
        "count_requested": args.count,
        "count_selected": len(selected),
        "instance_ids": selected,
    }
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
