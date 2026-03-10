#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return data


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _extract_solved_rate(eval_summary: dict[str, Any]) -> float:
    for key in (
        "solved_rate_on_planned",
        "solved_rate_on_submitted",
        "resolved_rate",
        "success_rate",
    ):
        if key in eval_summary:
            return _safe_float(eval_summary.get(key), 0.0)

    resolved = _safe_float(eval_summary.get("resolved_instances"), 0.0)
    planned = _safe_float(eval_summary.get("planned_instances"), 0.0)
    submitted = _safe_float(eval_summary.get("submitted_instances"), 0.0)
    denom = planned if planned > 0 else submitted
    return (resolved / denom) if denom > 0 else 0.0


def _extract_metrics_view(metrics: dict[str, Any]) -> dict[str, float]:
    td = metrics.get("trajectory_diagnostics", {}) if isinstance(metrics.get("trajectory_diagnostics"), dict) else {}
    steps = td.get("step_count_distribution", {}) if isinstance(td.get("step_count_distribution"), dict) else {}
    costs = td.get("instance_cost_distribution", {}) if isinstance(td.get("instance_cost_distribution"), dict) else {}
    return {
        "tool_failed_actions": _safe_float(td.get("tool_failed_actions"), 0.0),
        "mean_steps": _safe_float(steps.get("mean"), 0.0),
        "total_cost": _safe_float(costs.get("total"), 0.0),
    }


def _bootstrap_ci_lower(values: list[float], *, samples: int, seed: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(samples):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    idx = max(0, min(len(means) - 1, int(0.025 * len(means))))
    return means[idx]


def _build_delta_vector(diff_payload: dict[str, Any], instance_ids: list[str]) -> list[float]:
    only_with = {str(x) for x in diff_payload.get("only_with", [])}
    only_no = {str(x) for x in diff_payload.get("only_no", [])}
    vector: list[float] = []
    for iid in instance_ids:
        if iid in only_with:
            vector.append(1.0)
        elif iid in only_no:
            vector.append(-1.0)
        else:
            vector.append(0.0)
    return vector


@dataclass
class PairInput:
    pair_id: str
    no_mem_eval: Path
    with_mem_eval: Path
    no_mem_metrics: Path
    with_mem_metrics: Path
    diff_report: Path
    instance_ids: Path


def evaluate_pairs(
    pairs: list[PairInput],
    *,
    min_relative_improvement: float = 0.03,
    bootstrap_samples: int = 10000,
    bootstrap_seed: int = 42,
) -> dict[str, Any]:
    pair_rows: list[dict[str, Any]] = []
    all_bootstrap_values: list[float] = []
    only_no_counts: list[int] = []
    solved_deltas: list[float] = []
    tool_failed_improve_flags: list[bool] = []
    mean_steps_improve_flags: list[bool] = []
    total_cost_improve_flags: list[bool] = []

    for pair in pairs:
        no_eval = _load_json(pair.no_mem_eval)
        with_eval = _load_json(pair.with_mem_eval)
        no_metrics = _load_json(pair.no_mem_metrics)
        with_metrics = _load_json(pair.with_mem_metrics)
        diff_payload = _load_json(pair.diff_report)

        ids = json.loads(pair.instance_ids.read_text(encoding="utf-8"))
        if not isinstance(ids, list):
            raise ValueError(f"{pair.instance_ids} must contain a JSON list")
        instance_ids = [str(x) for x in ids]

        no_solved = _extract_solved_rate(no_eval)
        with_solved = _extract_solved_rate(with_eval)
        solved_delta = with_solved - no_solved
        solved_deltas.append(solved_delta)

        no_view = _extract_metrics_view(no_metrics)
        with_view = _extract_metrics_view(with_metrics)

        tool_failed_delta = no_view["tool_failed_actions"] - with_view["tool_failed_actions"]
        mean_steps_delta = no_view["mean_steps"] - with_view["mean_steps"]
        total_cost_delta = no_view["total_cost"] - with_view["total_cost"]

        tool_failed_improve = tool_failed_delta > 0
        mean_steps_improve = mean_steps_delta > 0
        total_cost_improve = total_cost_delta > 0
        tool_failed_improve_flags.append(tool_failed_improve)
        mean_steps_improve_flags.append(mean_steps_improve)
        total_cost_improve_flags.append(total_cost_improve)

        only_no_count = len(diff_payload.get("only_no", []))
        only_no_counts.append(only_no_count)

        delta_vector = _build_delta_vector(diff_payload, instance_ids)
        all_bootstrap_values.extend(delta_vector)

        pair_rows.append(
            {
                "pair_id": pair.pair_id,
                "solved_rate_no_mem": round(no_solved, 6),
                "solved_rate_with_mem": round(with_solved, 6),
                "delta_solved_rate": round(solved_delta, 6),
                "metrics_no_mem": no_view,
                "metrics_with_mem": with_view,
                "delta_tool_failed_actions_no_minus_with": round(tool_failed_delta, 6),
                "delta_mean_steps_no_minus_with": round(mean_steps_delta, 6),
                "delta_total_cost_no_minus_with": round(total_cost_delta, 6),
                "tool_failed_improved": tool_failed_improve,
                "mean_steps_improved": mean_steps_improve,
                "total_cost_improved": total_cost_improve,
                "only_no_count": only_no_count,
                "instance_count": len(instance_ids),
            }
        )

    pair_count = len(pair_rows)
    solved_positive_all = pair_count >= 2 and all(d > 0 for d in solved_deltas)
    bootstrap_ci_lower = _bootstrap_ci_lower(
        all_bootstrap_values, samples=bootstrap_samples, seed=bootstrap_seed
    )
    bootstrap_ci_pass = pair_count >= 2 and bootstrap_ci_lower >= 0.0

    tool_failed_consistent = pair_count >= 2 and all(tool_failed_improve_flags)
    mean_steps_consistent = pair_count >= 2 and all(mean_steps_improve_flags)
    total_cost_consistent = pair_count >= 2 and all(total_cost_improve_flags)
    efficiency_any_consistent = tool_failed_consistent or mean_steps_consistent or total_cost_consistent

    only_no_non_increasing = pair_count >= 2 and all(
        only_no_counts[i] <= only_no_counts[0] for i in range(1, len(only_no_counts))
    )

    # At least one efficiency metric should show >= 3% consistent relative gain.
    rel_gain_ok = False
    if pair_count >= 2:
        for key in ("tool_failed_actions", "mean_steps", "total_cost"):
            rel_flags: list[bool] = []
            for row in pair_rows:
                no_v = _safe_float(row["metrics_no_mem"].get(key), 0.0)
                with_v = _safe_float(row["metrics_with_mem"].get(key), 0.0)
                rel_gain = ((no_v - with_v) / no_v) if no_v > 0 else 0.0
                rel_flags.append(rel_gain >= min_relative_improvement)
            if all(rel_flags):
                rel_gain_ok = True
                break

    # Stage-4 section 2.2: satisfy at least 2 items among (solved stable+, tool_failed down, cost/steps down, only_no non-increase)
    criteria_hits = {
        "solved_stable_positive": solved_positive_all,
        "tool_failed_consistent_down": tool_failed_consistent,
        "cost_or_steps_consistent_down": (mean_steps_consistent or total_cost_consistent),
        "only_no_non_increasing": only_no_non_increasing,
    }
    criteria_hit_count = sum(1 for v in criteria_hits.values() if v)

    readiness = {
        "pair_count": pair_count,
        "rules": {
            "rerun_count_at_least_2": pair_count >= 2,
            "delta_solved_rate_positive_in_all_pairs": solved_positive_all,
            "bootstrap_ci95_lower_ge_0": bootstrap_ci_pass,
            "efficiency_metric_consistent_improvement": efficiency_any_consistent,
            "efficiency_metric_relative_gain_ge_3pct": rel_gain_ok,
            "only_no_non_increasing": only_no_non_increasing,
            "improvement_gate_at_least_2_items": criteria_hit_count >= 2,
        },
        "criteria_hits_2_2": criteria_hits,
        "criteria_hit_count_2_2": criteria_hit_count,
        "bootstrap": {
            "sample_count": len(all_bootstrap_values),
            "samples": bootstrap_samples,
            "seed": bootstrap_seed,
            "ci95_lower": round(bootstrap_ci_lower, 6),
        },
        "pairs": pair_rows,
    }
    readiness["stage4_stats_gate_passed"] = all(readiness["rules"].values())
    return readiness


def _load_pairs_config(path: Path) -> list[PairInput]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("pairs config must be a JSON array")
    out: list[PairInput] = []
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"pairs[{idx}] must be an object")
        out.append(
            PairInput(
                pair_id=str(item.get("pair_id", f"pair_{idx}")),
                no_mem_eval=Path(str(item["no_mem_eval"])).resolve(),
                with_mem_eval=Path(str(item["with_mem_eval"])).resolve(),
                no_mem_metrics=Path(str(item["no_mem_metrics"])).resolve(),
                with_mem_metrics=Path(str(item["with_mem_metrics"])).resolve(),
                diff_report=Path(str(item["diff_report"])).resolve(),
                instance_ids=Path(str(item["instance_ids"])).resolve(),
            )
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Stage-4 statistical readiness gates.")
    parser.add_argument("--pairs-config", required=True, help="Path to JSON array describing pair artifacts.")
    parser.add_argument("--output", required=True, help="Output JSON file path.")
    parser.add_argument("--bootstrap-samples", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=42)
    parser.add_argument("--min-relative-improvement", type=float, default=0.03)
    args = parser.parse_args()

    pairs = _load_pairs_config(Path(args.pairs_config).resolve())
    report = evaluate_pairs(
        pairs,
        min_relative_improvement=args.min_relative_improvement,
        bootstrap_samples=args.bootstrap_samples,
        bootstrap_seed=args.bootstrap_seed,
    )
    report["generated_at"] = _now_iso()
    report["pairs_config"] = str(Path(args.pairs_config).resolve())

    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out))
    print(f"stage4_stats_gate_passed={report['stage4_stats_gate_passed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
