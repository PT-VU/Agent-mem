#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be JSON object")
    return data


def _extract_ids(report: dict[str, Any], key: str) -> set[str]:
    raw = report.get(key, [])
    if not isinstance(raw, list):
        return set()
    return {str(x) for x in raw}


def _extract_solved_rate(report: dict[str, Any]) -> float:
    resolved = float(report.get("resolved_instances", 0) or 0)
    total = float(report.get("total_instances", 0) or 0)
    submitted = float(report.get("submitted_instances", 0) or 0)
    denom = total if total > 0 else submitted
    return (resolved / denom) if denom > 0 else 0.0


def _load_instance_ids(path: Path | None, no_report: dict[str, Any], with_report: dict[str, Any]) -> list[str]:
    if path is not None and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(x) for x in data]

    union_ids = set()
    for key in (
        "resolved_ids",
        "unresolved_ids",
        "completed_ids",
        "submitted_ids",
        "incomplete_ids",
        "error_ids",
    ):
        union_ids |= _extract_ids(no_report, key)
        union_ids |= _extract_ids(with_report, key)
    return sorted(union_ids)


def build_diff_report(
    no_report: dict[str, Any], with_report: dict[str, Any], instance_ids: list[str]
) -> dict[str, Any]:
    no_resolved = _extract_ids(no_report, "resolved_ids")
    with_resolved = _extract_ids(with_report, "resolved_ids")

    only_with = sorted(with_resolved - no_resolved)
    only_no = sorted(no_resolved - with_resolved)
    both_resolved = sorted(no_resolved & with_resolved)

    all_ids = set(instance_ids)
    both_unresolved = sorted(
        iid for iid in all_ids if iid not in with_resolved and iid not in no_resolved
    )

    no_rate = _extract_solved_rate(no_report)
    with_rate = _extract_solved_rate(with_report)

    return {
        "report_version": "v1",
        "generated_at": _now_iso(),
        "instance_count": len(instance_ids),
        "no_mem": {
            "resolved_instances": int(no_report.get("resolved_instances", len(no_resolved))),
            "unresolved_instances": int(no_report.get("unresolved_instances", 0) or 0),
            "solved_rate_on_planned": round(no_rate, 6),
        },
        "with_mem": {
            "resolved_instances": int(with_report.get("resolved_instances", len(with_resolved))),
            "unresolved_instances": int(with_report.get("unresolved_instances", 0) or 0),
            "solved_rate_on_planned": round(with_rate, 6),
        },
        "delta_solved_rate": round(with_rate - no_rate, 6),
        "only_with": only_with,
        "only_no": only_no,
        "both_resolved": both_resolved,
        "both_unresolved": both_unresolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare official eval reports (with_mem vs no_mem).")
    parser.add_argument("--no-mem-report", required=True)
    parser.add_argument("--with-mem-report", required=True)
    parser.add_argument("--instance-ids-json", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    no_path = Path(args.no_mem_report).resolve()
    with_path = Path(args.with_mem_report).resolve()
    ids_path = Path(args.instance_ids_json).resolve() if args.instance_ids_json else None
    out = Path(args.output).resolve()

    no_report = _load_json(no_path)
    with_report = _load_json(with_path)
    instance_ids = _load_instance_ids(ids_path, no_report, with_report)
    report = build_diff_report(no_report, with_report, instance_ids)
    report["inputs"] = {
        "no_mem_report": str(no_path),
        "with_mem_report": str(with_path),
        "instance_ids_json": str(ids_path) if ids_path else "",
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
