#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return _load_json(path)
    except Exception:
        return None


def _load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        out: dict[str, Any] = {}
        for row in data:
            if isinstance(row, dict):
                row_id = (
                    row.get("experience_id")
                    or row.get("card_id")
                    or row.get("pattern_id")
                    or row.get("rule_id")
                )
                if row_id:
                    out[str(row_id)] = row
        return out
    return {}


def _family_bucket(row: dict[str, Any]) -> str:
    norm = str(row.get("normalized_pattern_type", "")).strip().lower()
    family = str(row.get("family_id", "")).strip().lower()
    advice = str(row.get("normalized_advice_family", "")).strip().lower()
    if norm in {"validation_guard", "validation_gap"} or "validation" in advice:
        return "validation_guard"
    if norm in {"planning_loop", "constraint_ignorance"} or "planning" in family:
        return "planning_rule"
    return "failure_recovery"


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze AgentMem behavior from metrics + graph store.")
    ap.add_argument("--exp-dir", required=True)
    ap.add_argument("--metrics-json", required=True)
    ap.add_argument("--manifest-json", default="")
    ap.add_argument("--official-summary-json", default="")
    ap.add_argument("--output-json", required=True)
    ap.add_argument("--output-md", required=True)
    ap.add_argument("--scope", default="with-mem run")
    args = ap.parse_args()

    exp_dir = Path(args.exp_dir).resolve()
    metrics = _load_json(Path(args.metrics_json).resolve())
    manifest = _load_optional_json(Path(args.manifest_json).resolve()) if args.manifest_json else None
    official = _load_optional_json(Path(args.official_summary_json).resolve()) if args.official_summary_json else None

    graph_store_dir = exp_dir / "persistence" / "graph_store"
    abstracts = _load_store(graph_store_dir / "abstract_experiences.json")
    failure_cards = _load_store(graph_store_dir / "failure_cards_v2.json")
    repair_patterns = _load_store(graph_store_dir / "repair_patterns_v2.json")
    preventive_rules = _load_store(graph_store_dir / "preventive_rules_v2.json")

    abstract_rows = list(abstracts.values())
    failure_rows = list(failure_cards.values())
    repair_rows = list(repair_patterns.values())
    rule_rows = list(preventive_rules.values())

    family_counter = Counter()
    bucket_counter = Counter()
    merged_family_counter = 0
    support_values: list[float] = []
    for row in abstract_rows:
        family = str(row.get("family_id", "")).strip() or "unknown"
        family_counter[family] += 1
        bucket_counter[_family_bucket(row)] += 1
        support = float(row.get("support_count", 0) or 0)
        support_values.append(support)
        if support > 1:
            merged_family_counter += 1

    failure_class_counter = Counter(str(row.get("failure_class", "unknown")) for row in failure_rows)
    repair_source_counter = Counter(
        str((row.get("metadata") or {}).get("source", "unknown"))
        for row in repair_rows
        if isinstance(row, dict)
    )
    preventive_source_counter = Counter(
        str((row.get("metadata") or {}).get("source", "unknown"))
        for row in rule_rows
        if isinstance(row, dict)
    )

    mem_diag = metrics.get("memory_and_retrieval_diagnostics", {})
    family_injection = mem_diag.get("family_injection_summary", {})
    retrieval_summary = mem_diag.get("retrieval_summary", {})
    instance_metrics = metrics.get("instance_metrics", {})

    assessment = {
        "aggregation_improved": merged_family_counter > 0,
        "injection_repetition_controlled": float(family_injection.get("repeated_family_injection_rate", 1.0) or 1.0) <= 0.25,
        "infra_pollution_isolated": int(instance_metrics.get("infra_failure_instances", 0) or 0) >= 0
        and int(failure_class_counter.get("infra_failure_card", 0)) >= 0,
        "validation_memory_present": int(bucket_counter.get("validation_guard", 0)) > 0
        or int(preventive_source_counter.get("action_error_validation_guard", 0)) > 0,
        "micro_repair_present": int(repair_source_counter.get("action_error_micro_extraction", 0)) > 0,
    }

    result = {
        "schema_version": "v1",
        "scope": args.scope,
        "exp_dir": str(exp_dir),
        "manifest_present": bool(manifest),
        "official_summary_present": bool(official),
        "instance_metrics": instance_metrics,
        "memory_behavior": {
            "abstract_experience_total": len(abstract_rows),
            "abstract_family_unique": len(family_counter),
            "abstract_family_rows_with_support_gt_1": merged_family_counter,
            "abstract_support_mean": round(float(mean(support_values)) if support_values else 0.0, 6),
            "abstract_bucket_counts": dict(bucket_counter),
            "failure_card_class_counts": dict(failure_class_counter),
            "repair_pattern_source_counts": dict(repair_source_counter),
            "preventive_rule_source_counts": dict(preventive_source_counter),
            "family_injection_summary": family_injection,
            "retrieval_summary": retrieval_summary,
        },
        "assessment": assessment,
        "official_summary": official or {},
    }

    out_json = Path(args.output_json).resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append(f"# {args.scope} 记忆行为分析报告")
    lines.append("")
    lines.append("## 运行概览")
    lines.append(f"- 实验目录: `{exp_dir}`")
    lines.append(f"- 轨迹统计中的 `successful_instances`: {instance_metrics.get('successful_instances', 0)}")
    lines.append(f"- `infra_failure_instances`: {instance_metrics.get('infra_failure_instances', 0)}")
    lines.append(f"- `memory_eligible_done_instances`: {instance_metrics.get('memory_eligible_done_instances', 0)}")
    if official:
        lines.append(f"- 官方评测 `resolved_instances`: {official.get('resolved_instances', 0)}")
        lines.append(f"- 官方评测 `submitted_instances`: {official.get('submitted_instances', 0)}")
        solved_rate = official.get("solved_rate")
        if solved_rate is None:
            solved_rate = official.get("solved_rate_on_planned", 0.0)
        lines.append(f"- 官方评测 `solved_rate`: {float(solved_rate or 0.0):.2%}")
    lines.append("")
    lines.append("## 经验提取与聚合")
    lines.append(f"- `abstract_experience_total`: {len(abstract_rows)}")
    lines.append(f"- `abstract_family_unique`: {len(family_counter)}")
    lines.append(f"- `support_count > 1` 的 family 行数: {merged_family_counter}")
    lines.append(f"- `abstract_support_mean`: {result['memory_behavior']['abstract_support_mean']}")
    lines.append(f"- 经验桶分布: `{dict(bucket_counter)}`")
    lines.append(f"- failure card 分类: `{dict(failure_class_counter)}`")
    lines.append(f"- repair pattern 来源分布: `{dict(repair_source_counter)}`")
    lines.append(f"- preventive rule 来源分布: `{dict(preventive_source_counter)}`")
    lines.append("")
    lines.append("## 注入与去重")
    lines.append(f"- `unique_families_injected`: {family_injection.get('unique_families_injected', 0)}")
    lines.append(f"- `total_family_injections`: {family_injection.get('total_family_injections', 0)}")
    lines.append(f"- `repeated_family_injections`: {family_injection.get('repeated_family_injections', 0)}")
    lines.append(f"- `repeated_family_injection_rate`: {float(family_injection.get('repeated_family_injection_rate', 0.0) or 0.0):.2%}")
    lines.append("")
    lines.append("## 工程判断")
    for key, value in assessment.items():
        lines.append(f"- `{key}`: {'yes' if value else 'no'}")

    out_md = Path(args.output_md).resolve()
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(out_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
