#!/usr/bin/env python3
"""
Compare with-mem and no-mem trajectories for the same SWE-bench instances.

Outputs a structured divergence report that can be fed back into memory strategy
iteration.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


FAIL_SIGNAL_RE = re.compile(r"(error|exception|traceback|failed|not found|timeout)", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_traj_file(instance_dir: Path) -> Path | None:
    candidates = sorted(instance_dir.glob("*.traj"))
    return candidates[0] if candidates else None


def _collect_instances(root: Path) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    if not root.exists():
        return out
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        traj = _find_traj_file(child)
        if traj:
            out[child.name] = traj
    return out


def _extract_actions(traj: Dict[str, Any]) -> List[str]:
    actions: List[str] = []
    for step in traj.get("trajectory", []):
        action = str(step.get("action", "")).strip()
        actions.append(action)
    return actions


def _extract_fail_signals(traj: Dict[str, Any]) -> int:
    count = 0
    for step in traj.get("trajectory", []):
        obs = str(step.get("observation", ""))
        if FAIL_SIGNAL_RE.search(obs):
            count += 1
    return count


def _extract_memory_injection_steps(traj: Dict[str, Any]) -> List[int]:
    steps: List[int] = []
    for i, step in enumerate(traj.get("trajectory", []), start=1):
        query = step.get("query", [])
        if not isinstance(query, list):
            continue
        for msg in query:
            if not isinstance(msg, dict):
                continue
            content = str(msg.get("content", ""))
            if "[AgentMem Hints]" in content:
                steps.append(i)
                break
    return steps


def _first_divergence(a: List[str], b: List[str]) -> int | None:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i + 1  # 1-based step index
    if len(a) != len(b):
        return n + 1
    return None


def _normalize_exit_status(status: Any) -> str:
    return str(status or "unknown")


def _summarize_pair(instance_id: str, with_mem: Dict[str, Any], no_mem: Dict[str, Any]) -> Dict[str, Any]:
    with_actions = _extract_actions(with_mem)
    no_actions = _extract_actions(no_mem)
    with_steps = len(with_actions)
    no_steps = len(no_actions)

    step_delta = no_steps - with_steps
    first_div = _first_divergence(with_actions, no_actions)
    inject_steps = _extract_memory_injection_steps(with_mem)
    explainable = False
    if first_div is not None and inject_steps:
        explainable = any(s <= first_div for s in inject_steps)

    with_fail = _extract_fail_signals(with_mem)
    no_fail = _extract_fail_signals(no_mem)

    with_exit = _normalize_exit_status(with_mem.get("info", {}).get("exit_status"))
    no_exit = _normalize_exit_status(no_mem.get("info", {}).get("exit_status"))
    with_success = bool(with_mem.get("info", {}).get("submission")) or with_exit == "submitted"
    no_success = bool(no_mem.get("info", {}).get("submission")) or no_exit == "submitted"
    mem_unique_failure = (not with_success) and no_success
    effective_intervention = bool(
        inject_steps
        and (
            (with_success and not no_success)
            or step_delta > 0
            or (no_fail - with_fail) > 0
        )
    )

    return {
        "instance_id": instance_id,
        "with_mem_steps": with_steps,
        "no_mem_steps": no_steps,
        "step_delta_no_minus_with": step_delta,
        "detour_reduction": max(0, step_delta),
        "detour_increase": max(0, -step_delta),
        "with_mem_exit_status": with_exit,
        "no_mem_exit_status": no_exit,
        "with_mem_success": with_success,
        "no_mem_success": no_success,
        "first_divergence_step": first_div,
        "with_mem_injection_steps": inject_steps,
        "injection_before_or_at_divergence": explainable,
        "effective_intervention": effective_intervention,
        "mem_unique_failure": mem_unique_failure,
        "with_mem_fail_signal_count": with_fail,
        "no_mem_fail_signal_count": no_fail,
        "fail_signal_delta_no_minus_with": no_fail - with_fail,
    }


def build_report(with_mem_dir: Path, no_mem_dir: Path) -> Dict[str, Any]:
    with_map = _collect_instances(with_mem_dir)
    no_map = _collect_instances(no_mem_dir)

    with_ids = set(with_map.keys())
    no_ids = set(no_map.keys())
    paired = sorted(with_ids & no_ids)

    per_instance: List[Dict[str, Any]] = []
    for iid in paired:
        with_traj = _load_json(with_map[iid])
        no_traj = _load_json(no_map[iid])
        per_instance.append(_summarize_pair(iid, with_traj, no_traj))

    improved = [r for r in per_instance if r["step_delta_no_minus_with"] > 0]
    regressed = [r for r in per_instance if r["step_delta_no_minus_with"] < 0]
    equal = [r for r in per_instance if r["step_delta_no_minus_with"] == 0]
    explainable = [r for r in per_instance if r["injection_before_or_at_divergence"]]
    injected = [r for r in per_instance if r["with_mem_injection_steps"]]
    mem_unique_failures = [r for r in per_instance if r["mem_unique_failure"]]
    effective_interventions = [r for r in per_instance if r["effective_intervention"]]

    avg_step_delta = (
        sum(r["step_delta_no_minus_with"] for r in per_instance) / len(per_instance)
        if per_instance
        else 0.0
    )
    avg_fail_signal_delta = (
        sum(r["fail_signal_delta_no_minus_with"] for r in per_instance) / len(per_instance)
        if per_instance
        else 0.0
    )

    top_detour = sorted(per_instance, key=lambda x: x["detour_reduction"], reverse=True)[:20]
    top_regress = sorted(per_instance, key=lambda x: x["detour_increase"], reverse=True)[:20]

    report = {
        "report_version": "v1",
        "generated_at": _now_iso(),
        "inputs": {
            "with_mem_dir": str(with_mem_dir),
            "no_mem_dir": str(no_mem_dir),
        },
        "coverage": {
            "with_mem_instances": len(with_ids),
            "no_mem_instances": len(no_ids),
            "paired_instances": len(paired),
            "with_only_instances": sorted(with_ids - no_ids),
            "no_only_instances": sorted(no_ids - with_ids),
        },
        "summary": {
            "avg_step_delta_no_minus_with": round(avg_step_delta, 4),
            "avg_fail_signal_delta_no_minus_with": round(avg_fail_signal_delta, 4),
            "improved_instances": len(improved),
            "regressed_instances": len(regressed),
            "equal_instances": len(equal),
            "instances_with_mem_injection_detected": len(injected),
            "divergence_explainable_by_injection": len(explainable),
            "mem_unique_failures": len(mem_unique_failures),
            "effective_interventions": len(effective_interventions),
            "effective_intervention_rate": round(
                (len(effective_interventions) / len(injected)) if injected else 0.0,
                4,
            ),
            "divergence_explainable_ratio": round(
                (len(explainable) / len(per_instance)) if per_instance else 0.0,
                4,
            ),
        },
        "detour_reduction_top": top_detour,
        "detour_regression_top": top_regress,
        "memory_intervention_points": [
            {
                "instance_id": r["instance_id"],
                "first_divergence_step": r["first_divergence_step"],
                "with_mem_injection_steps": r["with_mem_injection_steps"],
                "detour_reduction": r["detour_reduction"],
                "effective_intervention": r["effective_intervention"],
            }
            for r in explainable
        ],
        "mem_unique_failures_top": sorted(
            mem_unique_failures,
            key=lambda x: (x["detour_increase"], x["with_mem_fail_signal_count"]),
            reverse=True,
        )[:20],
        "effective_interventions_top": sorted(
            effective_interventions,
            key=lambda x: (x["detour_reduction"], x["fail_signal_delta_no_minus_with"]),
            reverse=True,
        )[:20],
        "per_instance": per_instance,
        "assumptions": [
            "Fail signal count uses regex-based observation scan and is approximate.",
            "Memory intervention detection relies on '[AgentMem Hints]' marker in step query messages.",
            "Step comparison uses action strings and first divergence index.",
        ],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare with-mem/no-mem trajectories.")
    parser.add_argument("--with-mem-dir", required=True, help="with-mem output directory containing instance folders")
    parser.add_argument("--no-mem-dir", required=True, help="no-mem output directory containing instance folders")
    parser.add_argument("--output", required=True, help="Path to write divergence_report.json")
    args = parser.parse_args()

    with_mem_dir = Path(args.with_mem_dir).resolve()
    no_mem_dir = Path(args.no_mem_dir).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    report = build_report(with_mem_dir, no_mem_dir)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote divergence report: {output}")
    print(f"paired_instances={report['coverage']['paired_instances']}")
    print(f"improved_instances={report['summary']['improved_instances']}")
    print(f"regressed_instances={report['summary']['regressed_instances']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
