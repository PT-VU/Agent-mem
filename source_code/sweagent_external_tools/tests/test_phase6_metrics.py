from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
COLLECT_PATH = ROOT / "PDDL_work_mem" / "06_artificial_intelligence" / "experiments" / "common" / "collect_run_metrics.py"
GATES_PATH = ROOT / "PDDL_work_mem" / "source_code" / "sweagent_external_tools" / "tools" / "evaluate_memory_gates.py"
BEHAVIOR_PATH = ROOT / "PDDL_work_mem" / "06_artificial_intelligence" / "experiments" / "common" / "analyze_memory_behavior.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_collect_run_metrics_detects_infra_failure():
    mod = _load_module(COLLECT_PATH, "collect_run_metrics_mod")
    info = {"exit_status": "exit_environment_error"}
    traj = [
        {
            "action": "docker pull docker.io/swebench/example:latest",
            "observation": "DockerPullError after daemon unavailable",
            "response": "",
        }
    ]
    assert mod._classify_infra_failure(info, traj) == "docker_pull_error"


def test_collect_run_metrics_parses_family_injection_summary(tmp_path):
    mod = _load_module(COLLECT_PATH, "collect_run_metrics_mod_2")
    log_path = tmp_path / "events.jsonl"
    rows = [
        {
            "tool": "HOOK",
            "payload": {
                "event": "memory_injected",
                "hint_count": 2,
                "selected_family_ids": ["fam_a", "fam_b"],
            },
        },
        {
            "tool": "HOOK",
            "payload": {
                "event": "memory_injected",
                "hint_count": 1,
                "selected_family_ids": ["fam_a"],
            },
        },
    ]
    log_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    parsed = mod._parse_event_logs([log_path])
    summary = parsed["family_injection_summary"]
    assert summary["unique_families_injected"] == 2
    assert summary["total_family_injections"] == 3
    assert summary["repeated_family_injections"] == 1


def test_evaluate_memory_gates_reports_repeated_family_rate(tmp_path):
    mod = _load_module(GATES_PATH, "evaluate_memory_gates_mod")
    log_path = tmp_path / "events.jsonl"
    rows = [
        {"tool": "HOOK", "payload": {"event": "plan_generated"}},
        {"tool": "HOOK", "payload": {"event": "external_tool_response"}},
        {"tool": "HOOK", "payload": {"event": "memory_hint_buffered", "buffered_count": 2}},
        {"tool": "HOOK", "payload": {"event": "memory_injected", "hint_count": 2, "selected_family_ids": ["fam_x", "fam_y"]}},
        {"tool": "HOOK", "payload": {"event": "memory_injected", "hint_count": 1, "selected_family_ids": ["fam_x"]}},
    ]
    log_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    report = mod._evaluate(mod._aggregate(mod._load_jsonl(log_path)), min_external_ratio=0.1, min_buffer_ratio=0.1, min_action_error_coverage=0.0)
    assert report["metrics"]["repeated_family_injections"] == 1
    assert report["ratios"]["repeated_family_injection_rate"] == 0.333333


def test_analyze_memory_behavior_outputs_assessment(tmp_path):
    mod = _load_module(BEHAVIOR_PATH, "analyze_memory_behavior_mod")
    exp_dir = tmp_path / "exp"
    graph_dir = exp_dir / "persistence" / "graph_store"
    graph_dir.mkdir(parents=True)

    metrics = {
        "instance_metrics": {
            "successful_instances": 2,
            "infra_failure_instances": 1,
            "memory_eligible_done_instances": 3,
        },
        "memory_and_retrieval_diagnostics": {
            "family_injection_summary": {
                "unique_families_injected": 2,
                "total_family_injections": 3,
                "repeated_family_injections": 0,
                "repeated_family_injection_rate": 0.0,
            },
            "retrieval_summary": {},
        },
    }
    (tmp_path / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (graph_dir / "abstract_experiences.json").write_text(
        json.dumps(
            {
                "exp_1": {
                    "experience_id": "exp_1",
                    "family_id": "planning_loop__planning_transition_failure__force_progression_transition",
                    "normalized_pattern_type": "planning_loop",
                    "support_count": 2,
                },
                "exp_2": {
                    "experience_id": "exp_2",
                    "family_id": "validation_gap__missing_validation__add_local_validation",
                    "normalized_pattern_type": "validation_guard",
                    "support_count": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    (graph_dir / "failure_cards_v2.json").write_text(
        json.dumps({"card_1": {"card_id": "card_1", "failure_class": "infra_failure_card"}}),
        encoding="utf-8",
    )
    (graph_dir / "repair_patterns_v2.json").write_text(
        json.dumps({"pat_1": {"pattern_id": "pat_1", "metadata": {"source": "action_error_micro_extraction"}}}),
        encoding="utf-8",
    )
    (graph_dir / "preventive_rules_v2.json").write_text(
        json.dumps({"rule_1": {"rule_id": "rule_1", "metadata": {"source": "action_error_validation_guard"}}}),
        encoding="utf-8",
    )

    out_json = tmp_path / "behavior.json"
    out_md = tmp_path / "behavior.md"
    # Call via subprocess so we validate the CLI contract as well.
    import subprocess, sys

    completed = subprocess.run(
        [
            sys.executable,
            str(BEHAVIOR_PATH),
            "--exp-dir",
            str(exp_dir),
            "--metrics-json",
            str(tmp_path / "metrics.json"),
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
            "--scope",
            "test-scope",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["assessment"]["aggregation_improved"] is True
    assert data["assessment"]["micro_repair_present"] is True
    assert data["assessment"]["validation_memory_present"] is True
