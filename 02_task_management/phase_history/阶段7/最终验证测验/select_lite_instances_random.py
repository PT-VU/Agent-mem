#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Select random SWE-bench Lite instances.")
    ap.add_argument("--workspace-root", default="/home/pt/SWE-bench")
    ap.add_argument("--split", default="test")
    ap.add_argument("--count", type=int, default=15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--subset", default="lite")
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-short", action="store_true")
    args = ap.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be >= 1")

    ws_root = Path(args.workspace_root).resolve()
    import sys

    sys.path.insert(0, str(ws_root / "SWE-agent"))
    from sweagent.run.batch_instances import SWEBenchInstances  # type: ignore

    instances = SWEBenchInstances(subset=args.subset, split=args.split).get_instance_configs()
    all_ids = [inst.problem_statement.id for inst in instances]
    if len(all_ids) < args.count and not args.allow_short:
        raise SystemExit(
            f"subset={args.subset} split={args.split} requested={args.count} but only {len(all_ids)} available"
        )

    rng = random.Random(args.seed)
    selected = all_ids[:]
    rng.shuffle(selected)
    selected = selected[: args.count]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subset": args.subset,
        "split": args.split,
        "selection_mode": "random",
        "seed": args.seed,
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
