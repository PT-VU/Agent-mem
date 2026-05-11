#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    env = os.environ.copy()
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("HF_DATASETS_OFFLINE", "1")
    subprocess.run(cmd, check=True, env=env)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill official eval / summary for phase8 same-problem no-mem attempts.")
    ap.add_argument("--workspace-root", default="/home/pt/SWE-bench")
    ap.add_argument("--run-root", required=True)
    ap.add_argument("--python-bin", default="/home/pt/SWE-bench/SWE-agent/.venv/bin/python")
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    run_root = Path(args.run_root).resolve()
    python_bin = str(Path(args.python_bin).expanduser())

    same_json = run_root / "same_instances.json"
    if not same_json.exists():
        raise SystemExit(f"missing same_instances.json: {same_json}")
    instance_ids = json.loads(same_json.read_text(encoding="utf-8")).get("instance_ids", [])
    if not instance_ids:
        raise SystemExit("no instance ids found in same_instances.json")

    eval_step = workspace_root / "PDDL_work_mem/02_task_management/phase_history/阶段7/最终验证测验/official_eval_step.py"
    if not eval_step.exists():
        raise SystemExit(f"missing official eval step script: {eval_step}")

    base = run_root / "same_problem" / "nomem"
    metrics_dir = base / "metrics"
    reports_dir = metrics_dir / "attempt_reports"
    summaries_dir = metrics_dir / "attempt_summaries"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    totals = {"attempts": 0, "executed": 0, "processed": 0, "skipped": 0}
    for instance_id in instance_ids:
        for attempt in range(1, args.repeats + 1):
            totals["attempts"] += 1
            tag = f"{attempt:02d}"
            attempt_dir = base / "outputs" / instance_id / f"attempt_{tag}"
            if not attempt_dir.exists():
                continue
            totals["executed"] += 1

            pred_json = reports_dir / f"{instance_id}.attempt_{tag}.predictions.json"
            report_json = reports_dir / f"{instance_id}.attempt_{tag}.official_eval.json"
            summary_json = summaries_dir / f"{instance_id}.attempt_{tag}.summary.json"
            if summary_json.exists() and not args.force:
                totals["skipped"] += 1
                continue

            cmd = [
                python_bin,
                str(eval_step),
                "--workspace-root",
                str(workspace_root),
                "--python-bin",
                python_bin,
                "--instance-id",
                instance_id,
                "--attempt-dir",
                str(attempt_dir),
                "--predictions-json",
                str(pred_json),
                "--report-json",
                str(report_json),
                "--summary-json",
                str(summary_json),
                "--run-id",
                f"phase8_same_nomem_{instance_id}_attempt_{tag}",
                "--scope",
                f"Phase8 same-problem no-mem {instance_id} attempt {tag}",
                "--dataset",
                "SWE-bench/SWE-bench test",
                "--split",
                "test",
            ]
            print(f"[eval] instance={instance_id} attempt={tag}", flush=True)
            run(cmd)
            totals["processed"] += 1

    # Write rollup file compatible with existing readers.
    rows: list[dict] = []
    for instance_id in instance_ids:
        attempts: list[dict] = []
        for attempt in range(1, args.repeats + 1):
            tag = f"{attempt:02d}"
            summary_path = summaries_dir / f"{instance_id}.attempt_{tag}.summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
            attempts.append(
                {
                    "attempt": attempt,
                    "summary_path": str(summary_path),
                    "submitted_instances": summary.get("submitted_instances", 0),
                    "resolved_instances": summary.get("resolved_instances", 0),
                    "unresolved_instances": summary.get("unresolved_instances", 0),
                    "incomplete_instances": summary.get("incomplete_instances", 0),
                    "solved_rate_on_planned": summary.get("solved_rate_on_planned", 0.0),
                    "memory_mode": "no_mem",
                }
            )
        rows.append({"instance_id": instance_id, "attempts": attempts})

    rollup_path = metrics_dir / "attempt_summaries.json"
    rollup_path.write_text(
        json.dumps(
            {
                "instance_ids": instance_ids,
                "repeats": args.repeats,
                "instances": rows,
                "backfill_totals": totals,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"totals": totals, "rollup_path": str(rollup_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
