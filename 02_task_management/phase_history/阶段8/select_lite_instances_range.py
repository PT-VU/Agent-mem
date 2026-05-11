#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Select a 1-based inclusive range from SWE-bench Lite.")
    ap.add_argument("--workspace-root", default="/home/pt/SWE-bench")
    ap.add_argument("--subset", default="lite")
    ap.add_argument("--split", default="test")
    ap.add_argument("--case-start", type=int, default=1, help="1-based inclusive start index")
    ap.add_argument("--case-end", type=int, help="1-based inclusive end index; default is the last case")
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.case_start < 1:
        raise SystemExit("--case-start must be >= 1")
    if args.case_end is not None and args.case_end < args.case_start:
        raise SystemExit("--case-end must be >= --case-start")
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")

    ws_root = Path(args.workspace_root).resolve()
    import sys

    sys.path.insert(0, str(ws_root / "SWE-agent"))
    from sweagent.run.batch_instances import SWEBenchInstances  # type: ignore

    instances = SWEBenchInstances(subset=args.subset, split=args.split).get_instance_configs()
    all_ids = [inst.problem_statement.id for inst in instances]
    total_available = len(all_ids)
    if total_available == 0:
        raise SystemExit(f"subset={args.subset} split={args.split} has no instances")

    case_end = args.case_end if args.case_end is not None else total_available
    if case_end > total_available:
        raise SystemExit(
            f"--case-end={case_end} exceeds total available cases {total_available} "
            f"for subset={args.subset} split={args.split}"
        )

    selected = all_ids[args.case_start - 1 : case_end]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subset": args.subset,
        "split": args.split,
        "selection_mode": "range_1based_inclusive",
        "case_start_1based": args.case_start,
        "case_end_1based": case_end,
        "count_requested": case_end - args.case_start + 1,
        "count_selected": len(selected),
        "total_available": total_available,
        "repeats": args.repeats,
        "instance_ids": selected,
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
