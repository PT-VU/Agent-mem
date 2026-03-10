from __future__ import annotations

import tempfile

from ..integration.sweagent_adapter import SWEAgentAdapter


def test_action_error_micro_pattern_and_validation_rule_generated(monkeypatch):
    monkeypatch.setenv("AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS", "0")
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = SWEAgentAdapter(storage_dir=tmpdir, evidence_dir=tmpdir)
        repair_suggestions = {
            "confidence": 0.72,
            "next_step_fix": "Run the focused failing test before editing more code.",
            "evidence_refs": ["act_1"],
            "recommendations": [
                {
                    "type": "failure_card_v2",
                    "recommendation": "Run the focused failing test before editing more code.",
                    "verification_commands": ["pytest tests/test_target.py -q"],
                }
            ],
        }
        event_data = {
            "trace_id": "trace:1",
            "instance_id": "inst-1",
            "run_id": "run-1",
            "attempt_id": "attempt-1",
        }
        pattern = adapter._build_action_error_micro_pattern(
            task_id="task-1",
            event_data=event_data,
            query_type="test_failure_fix",
            error_type="test_failure",
            error_message="AssertionError: expected x got y",
            current_action="pytest -q",
            action_id="action-1",
            repair_suggestions=repair_suggestions,
        )
        rule = adapter._build_action_error_validation_rule(
            task_id="task-1",
            event_data=event_data,
            query_type="test_failure_fix",
            error_type="test_failure",
            repair_suggestions=repair_suggestions,
        )
        assert pattern is not None
        assert pattern["fix_action_template"].startswith("Run the focused failing test")
        assert "pytest -q" in pattern["expected_verification"]
        assert pattern["metadata"]["source"] == "action_error_micro_extraction"
        assert rule is not None
        assert rule["metadata"]["source"] == "action_error_validation_guard"
        assert rule["should_check"] == "pytest tests/test_target.py -q"


def test_action_error_micro_pattern_skips_infra_failures(monkeypatch):
    monkeypatch.setenv("AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS", "0")
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = SWEAgentAdapter(storage_dir=tmpdir, evidence_dir=tmpdir)
        repair_suggestions = {
            "confidence": 0.9,
            "next_step_fix": "Retry after Docker recovers.",
            "recommendations": [{"verification_commands": ["docker info"]}],
        }
        event_data = {"trace_id": "trace:infra"}
        assert (
            adapter._build_action_error_micro_pattern(
                task_id="task-infra",
                event_data=event_data,
                query_type="error_recovery",
                error_type="environment_error",
                error_message="DockerPullError",
                current_action="docker pull image",
                action_id="action-infra",
                repair_suggestions=repair_suggestions,
            )
            is None
        )
        assert (
            adapter._build_action_error_validation_rule(
                task_id="task-infra",
                event_data=event_data,
                query_type="error_recovery",
                error_type="environment_error",
                repair_suggestions=repair_suggestions,
            )
            is None
        )


def test_run_done_submission_writes_candidate_experience(monkeypatch):
    monkeypatch.setenv("AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS", "0")
    monkeypatch.setenv("AGENT_MEM_ENABLE_LLM_EXTRACTION", "0")
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = SWEAgentAdapter(storage_dir=tmpdir, evidence_dir=tmpdir)
        adapter.handle_plan_generated(
            {
                "agent": "main",
                "thought": "Inspect the failure and prepare a fix.",
                "action": "1. read files\n2. patch\n3. run tests",
                "instance_id": "inst-submitted",
                "run_id": "run-submitted",
                "attempt_id": "attempt-1",
                "trace_id": "trace-plan",
            }
        )
        result = adapter.handle_run_done(
            {
                "agent": "main",
                "instance_id": "inst-submitted",
                "run_id": "run-submitted",
                "attempt_id": "attempt-1",
                "trace_id": "trace-done",
                "exit_status": "submitted",
                "has_submission": True,
            }
        )
        assert result["submission_success"] is True
        assert result["resolved_like_success"] is False
        assert result["failure_card_v2"]["reason"] == "submission_pending_official_eval"
        exp_rows = adapter.graph_store.list_abstract_experiences(max_results=5)
        assert exp_rows
        assert exp_rows[0]["metadata"]["promotion_state"] == "candidate"
        assert exp_rows[0]["metadata"]["evidence_stage"] == "submission"
        assert exp_rows[0]["source_instance_id"] == "inst-submitted"
        assert "run-submitted" in (exp_rows[0].get("source_run_ids") or [])
        assert "attempt-1" in (exp_rows[0].get("source_attempt_ids") or [])
        summary = adapter.graph_store.get_latest_attempt_summary(instance_id="inst-submitted")
        assert summary is not None
        assert summary["instance_id"] == "inst-submitted"
        assert summary["attempt_id"] == "attempt-1"


def test_official_eval_feedback_updates_attempt_summary(monkeypatch):
    monkeypatch.setenv("AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS", "0")
    monkeypatch.setenv("AGENT_MEM_ENABLE_LLM_EXTRACTION", "0")
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = SWEAgentAdapter(storage_dir=tmpdir, evidence_dir=tmpdir)
        adapter.handle_plan_generated(
            {
                "agent": "main",
                "thought": "Inspect target function and validate the minimal fix.",
                "action": "1. inspect\n2. patch\n3. test",
                "instance_id": "inst-feedback",
                "run_id": "run-feedback",
                "attempt_id": "attempt-01",
                "trace_id": "trace-plan",
            }
        )
        adapter.handle_run_done(
            {
                "agent": "main",
                "instance_id": "inst-feedback",
                "run_id": "run-feedback",
                "attempt_id": "attempt-01",
                "trace_id": "trace-done",
                "exit_status": "submitted",
                "has_submission": True,
            }
        )
        feedback = adapter.apply_evaluation_feedback(
            {
                "instance_id": "inst-feedback",
                "run_id": "run-feedback",
                "attempt_id": "attempt-01",
                "trace_id": "trace-done",
                "official_eval_status": "unresolved",
                "eval_ref": "eval://test",
            }
        )
        summary = adapter.graph_store.get_latest_attempt_summary(instance_id="inst-feedback")
        assert summary is not None
        assert summary["final_outcome"] == "unresolved"
        assert "eval://test" in (summary.get("official_eval_refs") or [])
        assert feedback["feedback_report"]["attempt_summary_id"] == summary["summary_id"]


def test_extract_read_ids_supports_action_and_task_level_references(monkeypatch):
    monkeypatch.setenv("AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS", "0")
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = SWEAgentAdapter(storage_dir=tmpdir, evidence_dir=tmpdir)
        read_ids = adapter._extract_read_ids(
            {
                "recommendations": [
                    {"type": "workflow_step", "action_id": "action-1"},
                    {"type": "legacy_experience", "task_id": "task-2"},
                    {"type": "abstract_pattern", "experience_id": "exp-3"},
                    {"type": "attempt_summary_v1", "summary_id": "sum-4"},
                ]
            }
        )
        assert read_ids == ["action-1", "task-2", "exp-3", "sum-4"]
