#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
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


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    vals = sorted(values)
    k = (len(vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(vals[int(k)])
    d0 = vals[f] * (c - k)
    d1 = vals[c] * (k - f)
    return float(d0 + d1)


def _dist(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0, "p90": 0.0}
    return {
        "min": float(min(values)),
        "max": float(max(values)),
        "mean": float(mean(values)),
        "median": float(median(values)),
        "p90": float(_percentile(values, 0.90)),
    }


def _action_family(action: str) -> str:
    text = (action or "").strip()
    if not text:
        return "empty"
    if text.startswith("str_replace_editor"):
        parts = text.split()
        op = parts[1] if len(parts) >= 2 else "unknown"
        return f"str_replace_editor.{op}"
    return "bash"


def _classify_tool_failure(action_family: str, observation: str) -> str | None:
    obs = (observation or "").lower()
    if not obs:
        return None

    if action_family.startswith("str_replace_editor"):
        if "no replacement was performed" in obs or "did not appear exactly" in obs or "no changes made" in obs:
            return "str_replace_noop"
        if "already exists" in obs:
            return "file_exists"
        if "no such file" in obs or "not found" in obs:
            return "file_not_found"
        if "invalid command" in obs or "malformed command" in obs or "malformed request" in obs:
            return "invalid_editor_command"

    if action_family == "bash":
        if "permission denied" in obs:
            return "permission_denied"
        if "timed out" in obs or "timeout" in obs:
            return "timeout"
        if "no such file or directory" in obs:
            return "file_not_found"
        if "bash: " in obs and ("command not found" in obs or "event not found" in obs):
            return "bash_runtime_error"
        if "returned non-zero" in obs or "command failed" in obs:
            return "command_nonzero_exit"
        if re.search(r"\bexit code\b[^0-9]*[1-9][0-9]*", obs):
            return "command_nonzero_exit"
    return None


def _classify_process_error(text: str) -> str | None:
    low = (text or "").lower()
    if "modulenotfounderror" in low:
        return "module_not_found"
    if "filenotfounderror" in low or "no such file or directory" in low:
        return "file_not_found"
    if "importerror" in low:
        return "import_error"
    if "assertionerror" in low or "assert " in low:
        return "assertion_failure"
    if "syntaxerror" in low:
        return "syntax_error"
    if "traceback" in low:
        return "traceback"
    if "exception" in low:
        return "exception"
    if "test failed" in low or "failures:" in low:
        return "test_failure"
    return None


def _classify_infra_failure(info: dict[str, Any], traj: list[dict[str, Any]]) -> str | None:
    exit_status = str(info.get("exit_status", "") or "").lower()
    text_parts = [exit_status]
    for step in traj[-6:]:
        if not isinstance(step, dict):
            continue
        text_parts.append(str(step.get("observation", "")))
        text_parts.append(str(step.get("response", "")))
        text_parts.append(str(step.get("action", "")))
    body = "\n".join(text_parts).lower()
    markers = (
        ("insufficient balance", "llm_insufficient_balance"),
        ("dockerpullerror", "docker_pull_error"),
        ("docker pull", "docker_pull_error"),
        ("docker build", "docker_build_error"),
        ("daemon unavailable", "docker_daemon_unavailable"),
        ("docker daemon", "docker_daemon_unavailable"),
        ("no space left on device", "disk_full"),
        ("sigbus", "docker_sigbus"),
    )
    for token, reason in markers:
        if token in body:
            return reason
    if exit_status == "exit_environment_error" and any(tok in body for tok in ("docker", "daemon", "balance", "disk")):
        return "environment_runtime_failure"
    return None


def _contains_fail_signal(text: str) -> bool:
    low = (text or "").lower()
    return any(token in low for token in ("error", "exception", "traceback", "failed", "not found", "timeout"))


def _tokenize_for_match(text: str) -> set[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "then",
        "only",
        "when",
        "use",
        "these",
        "hint",
        "hints",
        "relevant",
        "current",
        "repository",
        "state",
        "consider",
        "try",
        "run",
    }
    tokens = {tok for tok in re.findall(r"[a-zA-Z0-9_./:-]+", (text or "").lower()) if tok}
    return {tok for tok in tokens if len(tok) >= 3 and tok not in stop}


def _extract_hints_from_query(query: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for msg in query:
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content", ""))
        if "[AgentMem Hints]" not in content:
            continue
        for line in content.splitlines():
            m = re.match(r"^\s*\d+\.\s+(.*)\s*$", line)
            if m:
                hint = m.group(1).strip()
                if hint:
                    hints.append(hint)
    return hints


def _repeat_ratio(actions: list[str]) -> float:
    cleaned = [a.strip() for a in actions if a and a.strip()]
    if len(cleaned) <= 1:
        return 0.0
    unique = len(set(cleaned))
    return max(0.0, 1.0 - (unique / len(cleaned)))


def _compute_intervention_quality(traj_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    total_injections = 0
    accepted_injections = 0
    recovery_candidates = 0
    recovered_after_injection = 0
    regress_after_injection = 0
    trajectories_with_injection = 0
    trajectories_with_drop = 0
    drop_magnitudes: list[float] = []

    for payload in traj_payloads:
        traj = payload.get("trajectory", []) if isinstance(payload.get("trajectory"), list) else []
        if not traj:
            continue

        injection_steps: list[int] = []
        actions: list[str] = [str(step.get("action", "")) if isinstance(step, dict) else "" for step in traj]

        for idx, step in enumerate(traj, start=1):
            if not isinstance(step, dict):
                continue
            query = step.get("query")
            if not isinstance(query, list):
                continue
            hints = _extract_hints_from_query(query)
            if not hints:
                continue

            total_injections += 1
            injection_steps.append(idx)
            action_text = str(step.get("action", ""))
            hint_tokens = _tokenize_for_match(" ".join(hints))
            action_tokens = _tokenize_for_match(action_text)
            if hint_tokens and action_tokens and hint_tokens.intersection(action_tokens):
                accepted_injections += 1

            prev_window = traj[max(0, idx - 3) : idx - 1]
            next_window = traj[idx : min(len(traj), idx + 2)]
            pre_fail = sum(
                1
                for s in prev_window
                if isinstance(s, dict) and _contains_fail_signal(str(s.get("observation", "")))
            )
            post_fail = sum(
                1
                for s in next_window
                if isinstance(s, dict) and _contains_fail_signal(str(s.get("observation", "")))
            )
            if pre_fail > 0:
                recovery_candidates += 1
                if post_fail == 0:
                    recovered_after_injection += 1
            if post_fail > pre_fail:
                regress_after_injection += 1

        if injection_steps:
            trajectories_with_injection += 1
            first_idx = min(injection_steps)
            before_ratio = _repeat_ratio(actions[: max(0, first_idx - 1)])
            after_ratio = _repeat_ratio(actions[first_idx - 1 :])
            drop = before_ratio - after_ratio
            if drop > 0:
                trajectories_with_drop += 1
                drop_magnitudes.append(drop)

    return {
        "total_injection_events": total_injections,
        "accepted_injection_events": accepted_injections,
        "hint_accept_rate": round(_safe_div(accepted_injections, total_injections), 6),
        "recovery_candidates_after_injection": recovery_candidates,
        "recovered_after_injection": recovered_after_injection,
        "post_injection_recovery_rate": round(_safe_div(recovered_after_injection, recovery_candidates), 6),
        "regression_events_after_injection": regress_after_injection,
        "regression_after_injection_rate": round(_safe_div(regress_after_injection, total_injections), 6),
        "trajectories_with_injection": trajectories_with_injection,
        "trajectories_with_repeated_action_drop": trajectories_with_drop,
        "repeated_action_drop_rate": round(_safe_div(trajectories_with_drop, trajectories_with_injection), 6),
        "repeated_action_drop_mean": round(float(mean(drop_magnitudes)) if drop_magnitudes else 0.0, 6),
    }


def _patch_stats(patch_text: str) -> tuple[int, int, int]:
    if not patch_text:
        return (0, 0, 0)
    files_changed = len(re.findall(r"^diff --git ", patch_text, flags=re.MULTILINE))
    added = 0
    deleted = 0
    for line in patch_text.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return (added, deleted, files_changed)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    return None


def _safe_div(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return float(num / den)


def _collect_event_files(workspace_root: Path, event_log_glob: str) -> list[Path]:
    if not event_log_glob:
        return []
    files = sorted(workspace_root.glob(event_log_glob))
    return [f for f in files if f.is_file()]


def _parse_event_logs(paths: list[Path]) -> dict[str, Any]:
    counters = Counter()
    trigger_counter = Counter()
    retrieval_before: list[float] = []
    retrieval_after: list[float] = []
    retrieval_tasks: list[float] = []
    selected_subgraphs: list[float] = []
    injected_events_total = 0
    injected_traceable_events = 0
    injected_trace_missing_events = 0
    injected_with_memory_ids = 0
    injected_effective_traceable = 0
    family_counter = Counter()
    repeated_family_injections = 0

    for path in paths:
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            tool = str(row.get("tool", ""))
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            counters[f"tool::{tool}"] += 1
            event = str(payload.get("event", ""))
            if event:
                counters[f"event::{event}"] += 1
            if event == "memory_injected":
                counters["memory_injected_hints_total"] += int(payload.get("hint_count", 0) or 0)
                injected_events_total += 1
                family_ids = payload.get("selected_family_ids") or []
                if isinstance(family_ids, list):
                    for raw_family in family_ids:
                        family = str(raw_family or "").strip()
                        if not family:
                            continue
                        if family_counter[family] > 0:
                            repeated_family_injections += 1
                        family_counter[family] += 1
                trace_missing = bool(payload.get("trace_id_missing", False))
                trace_ids = payload.get("selected_trace_ids") or []
                has_trace = (not trace_missing) and isinstance(trace_ids, list) and any(str(t).strip() for t in trace_ids)
                if has_trace:
                    injected_traceable_events += 1
                else:
                    injected_trace_missing_events += 1
                memory_ids = payload.get("selected_memory_ids") or []
                if isinstance(memory_ids, list) and any(str(mid).strip() for mid in memory_ids):
                    injected_with_memory_ids += 1
                    if has_trace:
                        injected_effective_traceable += 1
                for trig in payload.get("triggers", []) or []:
                    if isinstance(trig, str):
                        trigger_counter[trig.split(":", 1)[0]] += 1
            if event == "memory_hint_buffered":
                counters["memory_hint_buffered_total"] += int(payload.get("buffered_count", 0) or 0)
            if event == "external_tool_response":
                rd = payload.get("retrieval_debug")
                if isinstance(rd, dict):
                    retrieval_before.append(float(rd.get("candidate_count_before_filter", 0) or 0))
                    retrieval_after.append(float(rd.get("candidate_count_after_filter", 0) or 0))
                    retrieval_tasks.append(float(rd.get("candidate_task_count", 0) or 0))
                    selected_subgraphs.append(float(rd.get("selected_subgraph_count", 0) or 0))

    return {
        "event_counts": dict(counters),
        "trigger_counts": dict(trigger_counter),
        "injection_traceability": {
            "injected_events_total": injected_events_total,
            "injected_traceable_events": injected_traceable_events,
            "injected_trace_missing_events": injected_trace_missing_events,
            "injected_with_memory_ids": injected_with_memory_ids,
            "effective_interventions_traceable": injected_effective_traceable,
            "effective_intervention_traceable_rate": round(
                _safe_div(injected_effective_traceable, injected_traceable_events), 6
            ),
        },
        "retrieval_summary": {
            "samples": len(retrieval_before),
            "candidate_count_before_filter": _dist(retrieval_before),
            "candidate_count_after_filter": _dist(retrieval_after),
            "candidate_task_count": _dist(retrieval_tasks),
            "selected_subgraph_count": _dist(selected_subgraphs),
        },
        "family_injection_summary": {
            "unique_families_injected": len(family_counter),
            "family_injection_counts": dict(family_counter),
            "total_family_injections": int(sum(family_counter.values())),
            "repeated_family_injections": repeated_family_injections,
            "repeated_family_injection_rate": round(
                _safe_div(repeated_family_injections, sum(family_counter.values())),
                6,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect standardized SWE-agent metrics.")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--subset-label", required=True)
    parser.add_argument("--mode", required=True, choices=["with-mem", "no-mem"])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cache-file", default="")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--stop-index", type=int, default=0)
    parser.add_argument("--event-log-glob", default="")
    parser.add_argument("--require-event-logs", action="store_true")
    parser.add_argument("--manifest-path", default="")
    parser.add_argument("--metrics-out", required=True)
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    cache_file = Path(args.cache_file).resolve() if args.cache_file else None
    metrics_out = Path(args.metrics_out).resolve()
    manifest_path = Path(args.manifest_path).resolve() if args.manifest_path else None

    cache_ids = _read_cache_ids(cache_file) if cache_file else []
    if cache_ids and args.stop_index > 0:
        planned_ids = cache_ids[args.start_index : args.stop_index]
    elif cache_ids:
        planned_ids = cache_ids[args.start_index :]
    else:
        planned_ids = []

    traj_paths = sorted(output_dir.glob("*/*.traj"))
    traj_by_id = {p.stem: p for p in traj_paths}
    if not planned_ids:
        planned_ids = sorted(traj_by_id.keys())

    total_instances = len(planned_ids)
    done_instances = 0
    successful_instances = 0
    submitted_instances = 0
    exit_status_breakdown = Counter()
    unsolved_reason_breakdown = Counter()
    failed_by_repo = Counter()
    success_by_repo = Counter()
    infra_failure_by_reason = Counter()
    infra_failure_instances = set()

    step_counts: list[float] = []
    api_calls: list[float] = []
    instance_costs: list[float] = []
    action_family_counts = Counter()
    process_error_counts = Counter()
    tool_failure_counts = Counter()
    instances_with_tool_failures = set()

    instances_with_edit_action = 0
    instances_with_submission_but_no_edit = 0
    patch_added_total = 0
    patch_deleted_total = 0
    patch_files_total = 0
    loaded_payloads: list[dict[str, Any]] = []

    for iid in planned_ids:
        traj_path = traj_by_id.get(iid)
        if traj_path is None:
            continue
        payload = _load_json(traj_path)
        if payload is None:
            continue
        loaded_payloads.append(payload)

        done_instances += 1
        info = payload.get("info", {}) if isinstance(payload.get("info"), dict) else {}
        traj = payload.get("trajectory", []) if isinstance(payload.get("trajectory"), list) else []
        exit_status = str(info.get("exit_status", "unknown"))
        exit_status_breakdown[exit_status] += 1
        submitted = bool(info.get("submission")) or exit_status == "submitted"
        if submitted:
            submitted_instances += 1
            successful_instances += 1
        else:
            unsolved_reason_breakdown[exit_status] += 1

        repo = iid.split("__", 1)[0] if "__" in iid else "unknown"
        if submitted:
            success_by_repo[repo] += 1
        else:
            failed_by_repo[repo] += 1

        step_counts.append(float(len(traj)))

        model_stats = info.get("model_stats") if isinstance(info.get("model_stats"), dict) else {}
        api_calls.append(float(model_stats.get("api_calls", len(traj)) or len(traj)))
        cost = model_stats.get("instance_cost", 0.0)
        try:
            instance_costs.append(float(cost))
        except Exception:
            instance_costs.append(0.0)

        has_edit_action = False
        instance_has_tool_failure = False
        for step in traj:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action", ""))
            observation = str(step.get("observation", ""))
            response = str(step.get("response", ""))
            action_family = _action_family(action)
            action_family_counts[action_family] += 1
            if action_family.startswith("str_replace_editor."):
                has_edit_action = True

            failure_cat = _classify_tool_failure(action_family, observation)
            if failure_cat:
                tool_failure_counts[failure_cat] += 1
                instance_has_tool_failure = True

            process_cat = _classify_process_error(f"{observation}\n{response}")
            if process_cat:
                process_error_counts[process_cat] += 1

        if has_edit_action:
            instances_with_edit_action += 1
        if submitted and not has_edit_action:
            instances_with_submission_but_no_edit += 1
        if instance_has_tool_failure:
            instances_with_tool_failures.add(iid)

        patch_text = str(info.get("submission", "") or "")
        add_c, del_c, files_c = _patch_stats(patch_text)
        patch_added_total += add_c
        patch_deleted_total += del_c
        patch_files_total += files_c

        if not submitted:
            infra_reason = _classify_infra_failure(info, traj)
            if infra_reason:
                infra_failure_instances.add(iid)
                infra_failure_by_reason[infra_reason] += 1

    tool_action_total = int(sum(action_family_counts.values()))
    tool_failed_actions = int(sum(tool_failure_counts.values()))
    tool_success_actions = max(0, tool_action_total - tool_failed_actions)
    memory_eligible_done_instances = max(0, done_instances - len(infra_failure_instances))

    cost_dist = _dist(instance_costs)
    cost_dist["total"] = float(sum(instance_costs))

    event_files = _collect_event_files(workspace_root, args.event_log_glob)
    event_log_files_missing = bool(args.event_log_glob) and len(event_files) == 0
    if args.require_event_logs and event_log_files_missing:
        print(
            f"ERROR: no event logs matched glob={args.event_log_glob}",
            flush=True,
        )
        return 1
    event_metrics = _parse_event_logs(event_files)
    intervention_quality = _compute_intervention_quality(loaded_payloads)
    manifest = _load_json(manifest_path) if manifest_path else None

    metrics = {
        "schema_version": "v2",
        "experiment_id": args.experiment_id,
        "subset": args.subset_label,
        "mode": args.mode,
        "output_dir": str(output_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instance_metrics": {
            "total_instances": total_instances,
            "done_instances": done_instances,
            "successful_instances": successful_instances,
            "failed_instances": max(0, done_instances - successful_instances),
            "success_rate": round(_safe_div(successful_instances, total_instances), 6),
            "success_rate_done_only": round(_safe_div(successful_instances, done_instances), 6),
            "infra_failure_instances": len(infra_failure_instances),
            "memory_eligible_done_instances": memory_eligible_done_instances,
            "infra_failure_rate_done_only": round(_safe_div(len(infra_failure_instances), done_instances), 6),
            "success_rate_infra_excluded_done_only": round(
                _safe_div(successful_instances, memory_eligible_done_instances),
                6,
            ),
            "memory_eligible_success_rate": round(
                _safe_div(successful_instances, memory_eligible_done_instances),
                6,
            ),
            "submitted_instances": submitted_instances,
            "exit_status_breakdown": dict(exit_status_breakdown),
            "unsolved_reason_breakdown": dict(unsolved_reason_breakdown),
        },
        "trajectory_diagnostics": {
            "step_count_distribution": _dist(step_counts),
            "api_calls_distribution": _dist(api_calls),
            "instance_cost_distribution": cost_dist,
            "action_family_counts": dict(action_family_counts),
            "tool_action_total": tool_action_total,
            "tool_failed_actions": tool_failed_actions,
            "tool_success_actions": tool_success_actions,
            "tool_call_success_rate": round(_safe_div(tool_success_actions, tool_action_total), 6),
            "tool_failure_category_counts": dict(tool_failure_counts),
            "instances_with_tool_failures": len(instances_with_tool_failures),
        },
        "editing_and_patch_signals": {
            "instances_with_edit_action": instances_with_edit_action,
            "instances_no_edit_signal": max(0, done_instances - instances_with_edit_action),
            "instances_with_submission_but_no_edit_action": instances_with_submission_but_no_edit,
            "patch_total_added_lines": patch_added_total,
            "patch_total_deleted_lines": patch_deleted_total,
            "patch_total_files_changed": patch_files_total,
            "patch_avg_changed_lines_per_submitted_instance": round(
                _safe_div(patch_added_total + patch_deleted_total, max(1, submitted_instances)),
                2,
            ),
        },
        "failure_concentration": {
            "failed_instances_by_repo": dict(failed_by_repo),
            "successful_instances_by_repo": dict(success_by_repo),
        },
        "workflow_error_signals": {
            "trajectory_error_category_counts": dict(process_error_counts),
            "infra_failure_instances_by_reason": dict(infra_failure_by_reason),
            "infra_failure_instance_ids": sorted(infra_failure_instances),
        },
        "memory_and_retrieval_diagnostics": event_metrics,
        "intervention_effectiveness": intervention_quality,
        "data_sources": {
            "traj_glob": str(output_dir / "*/*.traj"),
            "cache_file": str(cache_file) if cache_file else "",
            "event_log_glob": args.event_log_glob,
            "event_log_files": [str(p) for p in event_files],
            "event_log_files_missing": event_log_files_missing,
            "manifest_path": str(manifest_path) if manifest_path else "",
            "manifest_found": bool(manifest),
            "index_filter": {
                "start_index": args.start_index,
                "stop_index": args.stop_index,
            },
        },
    }

    metrics_out.parent.mkdir(parents=True, exist_ok=True)
    metrics_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(metrics_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
