"""
Official evaluation feedback loop for AgentMem.

This module keeps the post-eval path explicit and lightweight:
- promote candidate memories on resolved
- suppress candidate memories on unresolved
- write small negative/validation memories from real external feedback
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..storage.graph_store import GraphStore


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_") or "unknown"


class EvaluationFeedbackProcessor:
    """Maps official eval outcomes back into existing memory objects."""

    def __init__(self, graph_store: GraphStore):
        self.graph_store = graph_store

    def apply_feedback(
        self,
        *,
        instance_id: str,
        outcome: str,
        eval_ref: str = "",
        patch_text: str = "",
        patch_summary: Optional[Dict[str, Any]] = None,
        changed_files: Optional[List[str]] = None,
        validation_summary: Optional[Dict[str, Any]] = None,
        task_summary: str = "",
        run_id: str = "",
        attempt_id: str = "",
        trace_id: str = "",
    ) -> Dict[str, Any]:
        outcome_norm = self._normalize_outcome(outcome)
        related = self.graph_store.list_candidate_abstract_experiences(
            instance_id=instance_id,
            run_id=run_id,
            attempt_id=attempt_id,
            trace_id=trace_id,
            max_results=200,
        )
        related_ids = [str(row.get("experience_id")) for row in related if str(row.get("experience_id", "")).strip()]

        report: Dict[str, Any] = {
            "instance_id": instance_id,
            "outcome": outcome_norm,
            "eval_ref": eval_ref,
            "related_candidate_count": len(related_ids),
            "related_candidate_ids": list(related_ids),
            "promoted_ids": [],
            "suppressed_ids": [],
            "written_ids": [],
            "failure_card_id": None,
            "patch_summary": {},
        }

        if outcome_norm == "resolved":
            for exp_id in related_ids:
                if self.graph_store.mark_experience_promoted(exp_id, eval_ref=eval_ref):
                    report["promoted_ids"].append(exp_id)
            return report

        if outcome_norm == "infra_failure":
            card_id = self.graph_store.upsert_failure_card_v2(
                {
                    "task_id": f"official_eval::{instance_id}",
                    "instance_id": instance_id,
                    "run_id": run_id or None,
                    "trace_id": trace_id or None,
                    "source_event": "official_eval_feedback",
                    "error_signature": {"error_type": "environment_error"},
                    "candidate_fix_actions": ["stabilize_runtime_environment_before_retrying"],
                    "verification_commands": ["docker info"],
                    "failure_class": "infra_failure_card",
                    "status": "incomplete",
                    "confidence": 0.9,
                    "metadata": {
                        "experience_polarity": "neutral",
                        "evaluation_outcome": outcome_norm,
                        "official_eval_refs": [eval_ref] if eval_ref else [],
                        "task_summary": task_summary[:280],
                    },
                }
            )
            report["failure_card_id"] = card_id
            return report

        for exp_id in related_ids:
            if self.graph_store.mark_experience_suppressed(
                exp_id,
                eval_ref=eval_ref,
                reason=f"official_eval_{outcome_norm}",
            ):
                report["suppressed_ids"].append(exp_id)

        summary = self._build_patch_summary(
            patch_text=patch_text,
            changed_files=changed_files or [],
            validation_summary=validation_summary or {},
            supplied_summary=patch_summary or {},
        )
        report["patch_summary"] = summary

        for payload in self._build_negative_experiences(
            instance_id=instance_id,
            outcome=outcome_norm,
            eval_ref=eval_ref,
            summary=summary,
            task_summary=task_summary,
            run_id=run_id,
            attempt_id=attempt_id,
            trace_id=trace_id,
        ):
            exp_id = self.graph_store.upsert_abstract_experience(payload)
            self.graph_store.mark_experience_promoted(exp_id, eval_ref=eval_ref)
            report["written_ids"].append(exp_id)

        if outcome_norm == "unresolved":
            card_id = self.graph_store.upsert_failure_card_v2(
                {
                    "task_id": f"official_eval::{instance_id}",
                    "instance_id": instance_id,
                    "run_id": run_id or None,
                    "trace_id": trace_id or None,
                    "source_event": "official_eval_feedback",
                    "error_signature": {"error_type": "evaluation_unresolved"},
                    "candidate_fix_actions": self._candidate_fix_actions(summary),
                    "verification_commands": self._verification_commands(summary),
                    "confidence": 0.76,
                    "status": "unresolved",
                    "metadata": {
                        "evaluation_outcome": outcome_norm,
                        "official_eval_refs": [eval_ref] if eval_ref else [],
                        "task_summary": task_summary[:280],
                        "patch_summary": summary,
                    },
                }
            )
            report["failure_card_id"] = card_id

        return report

    @staticmethod
    def _normalize_outcome(outcome: str) -> str:
        raw = str(outcome or "").strip().lower()
        if raw in {"resolved", "success", "pass", "passed"}:
            return "resolved"
        if raw in {"infra_failure", "environment_error"}:
            return "infra_failure"
        if raw in {"incomplete", "timeout", "error"}:
            return "incomplete"
        return "unresolved"

    def _build_patch_summary(
        self,
        *,
        patch_text: str,
        changed_files: List[str],
        validation_summary: Dict[str, Any],
        supplied_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        summary = dict(supplied_summary)
        patch = patch_text or ""
        risk_flags: List[str] = [str(x).strip() for x in (summary.get("risk_flags") or []) if str(x).strip()]
        added_lines = [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
        heuristics = {
            "broad_exception": r"(?m)^\+.*except\s+(?:Exception|BaseException)\b",
            "bare_exception": r"(?m)^\+.*except:\s*$",
            "quiet_flag": r"(?m)^\+.*quiet\s*=\s*True",
            "warning_suppression": r"(?m)^\+.*warnings\.filterwarnings",
            "silent_pass": r"(?m)^\+.*\bpass\b",
            "suppress_context": r"(?m)^\+.*contextlib\.suppress",
            "interface_expansion": r"(?m)^\+.*def\s+\w+\s*\(.*=.*\)",
            "behavior_change_default": r"(?m)^\+.*def\s+\w+\s*\(.*(?:quiet|strict|force|fallback)\s*=\s*(?:True|False|None)\b.*\)",
        }
        for name, pattern in heuristics.items():
            if re.search(pattern, patch):
                risk_flags.append(name)
        if len(added_lines) >= 40:
            risk_flags.append("large_patch")
        if len(set(changed_files)) >= 4:
            risk_flags.append("broad_surface_patch")
        validation_commands = [
            str(x).strip()
            for x in (validation_summary.get("commands") or validation_summary.get("verification_commands") or [])
            if str(x).strip()
        ]
        if not validation_commands:
            risk_flags.append("missing_target_validation")
        summary["risk_flags"] = list(dict.fromkeys(risk_flags))
        summary["changed_files"] = list(dict.fromkeys([str(x).strip() for x in changed_files if str(x).strip()]))
        summary["validation_commands"] = validation_commands[:6]
        summary["changed_file_count"] = len(summary["changed_files"])
        return summary

    def _build_negative_experiences(
        self,
        *,
        instance_id: str,
        outcome: str,
        eval_ref: str,
        summary: Dict[str, Any],
        task_summary: str,
        run_id: str,
        attempt_id: str,
        trace_id: str,
    ) -> List[Dict[str, Any]]:
        risk_flags = [str(x).strip() for x in (summary.get("risk_flags") or []) if str(x).strip()]
        changed_files = [str(x).strip() for x in (summary.get("changed_files") or []) if str(x).strip()]
        validation_commands = [str(x).strip() for x in (summary.get("validation_commands") or []) if str(x).strip()]

        payloads: List[Dict[str, Any]] = []
        if any(flag in risk_flags for flag in {"broad_exception", "bare_exception", "quiet_flag", "warning_suppression", "silent_pass", "suppress_context"}):
            payloads.append(
                self._negative_experience_payload(
                    instance_id=instance_id,
                    pattern_type="negative_strategy_suppressive_fix",
                    abstracted_intent="Avoid suppressive fixes that silence failures before target validation confirms the real bug is fixed.",
                    success_conditions=["require_target_validation_before_submission"],
                    failure_avoidance=["do_not_repeat_suppressive_fix_as_primary_strategy"],
                    eval_ref=eval_ref,
                    task_summary=task_summary,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    trace_id=trace_id,
                    changed_files=changed_files,
                )
            )
        if any(flag in risk_flags for flag in {"large_patch", "interface_expansion", "behavior_change_default"}):
            payloads.append(
                self._negative_experience_payload(
                    instance_id=instance_id,
                    pattern_type="patch_risk_overdesigned_fix",
                    abstracted_intent="Avoid broad or interface-expanding patches before proving that a minimal fix cannot solve the failing path.",
                    success_conditions=["prefer_minimal_patch_then_targeted_validation"],
                    failure_avoidance=["do_not_expand_public_behavior_before_minimal_fix_is_tested"],
                    eval_ref=eval_ref,
                    task_summary=task_summary,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    trace_id=trace_id,
                    changed_files=changed_files,
                )
            )
        if "missing_target_validation" in risk_flags:
            payloads.append(
                self._negative_experience_payload(
                    instance_id=instance_id,
                    pattern_type="validation_gap_missing_target_validation",
                    abstracted_intent="Submitted patches without target validation should be treated as risky until the failing path is verified directly.",
                    success_conditions=["run_targeted_validation_before_submission"],
                    failure_avoidance=["avoid_submission_without_target_validation"],
                    eval_ref=eval_ref,
                    task_summary=task_summary,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    trace_id=trace_id,
                    changed_files=changed_files,
                )
            )
        if outcome == "incomplete" and (validation_commands or not changed_files):
            payloads.append(
                self._negative_experience_payload(
                    instance_id=instance_id,
                    pattern_type="negative_strategy_timeout_after_overexploration",
                    abstracted_intent="If repeated reproduction or ad-hoc validation does not produce a patch before timeout, stop expanding scope and either persist the minimal fix candidate or terminate early.",
                    success_conditions=[
                        "limit_ad_hoc_validation_scripts",
                        "promote_minimal_fix_candidate_earlier",
                    ],
                    failure_avoidance=[
                        "avoid_repeated_reproduction_after_key_signal",
                        "avoid_timeout_without_patch",
                    ],
                    eval_ref=eval_ref,
                    task_summary=task_summary,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    trace_id=trace_id,
                    changed_files=changed_files,
                )
            )
        if outcome == "unresolved" and (risk_flags or not payloads):
            payloads.append(
                self._negative_experience_payload(
                    instance_id=instance_id,
                    pattern_type="patch_risk_submission_unresolved",
                    abstracted_intent="A submitted patch that remains unresolved in official evaluation should be treated as a patch-risk warning, not a success pattern.",
                    success_conditions=validation_commands[:3] or ["run_targeted_validation_before_submission"],
                    failure_avoidance=["do_not_promote_submitted_patch_without_official_resolution"],
                    eval_ref=eval_ref,
                    task_summary=task_summary,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    trace_id=trace_id,
                    changed_files=changed_files,
                )
            )
        return payloads

    def _negative_experience_payload(
        self,
        *,
        instance_id: str,
        pattern_type: str,
        abstracted_intent: str,
        success_conditions: List[str],
        failure_avoidance: List[str],
        eval_ref: str,
        task_summary: str,
        run_id: str,
        attempt_id: str,
        trace_id: str,
        changed_files: List[str],
    ) -> Dict[str, Any]:
        norm_pattern = "negative_strategy" if pattern_type.startswith("negative_strategy") else (
            "patch_risk" if pattern_type.startswith("patch_risk") else "validation_gap"
        )
        trigger = "official_eval_unresolved"
        if norm_pattern == "validation_gap":
            trigger = "missing_validation"
        subproblem_type = "target_validation"
        strategy_label = "unknown_strategy"
        prefer_actions: List[str] = []
        avoid_actions: List[str] = []
        if pattern_type == "negative_strategy_timeout_after_overexploration":
            subproblem_type = "reproduce_issue"
            strategy_label = "ad_hoc_repro_script_loop"
            prefer_actions = ["reuse_confirmed_repro_path", "promote_minimal_fix_candidate_earlier"]
            avoid_actions = ["create_new_repro_script_after_repro_confirmed"]
        elif pattern_type.startswith("patch_risk"):
            subproblem_type = "form_minimal_patch"
            strategy_label = "api_alternative_probe_without_fix"
            prefer_actions = ["edit_target_function_before_new_module_search", "run_target_validation_before_submission"]
            avoid_actions = ["expand_patch_scope_before_minimal_fix_is_tested"]
        elif pattern_type.startswith("validation_gap"):
            subproblem_type = "target_validation"
            strategy_label = "broad_test_without_patch"
            prefer_actions = ["run_target_validation_before_submission"]
            avoid_actions = ["submit_without_target_validation"]
        return {
            "schema_version": "2.1",
            "pattern_type": pattern_type,
            "abstracted_intent": abstracted_intent,
            "variant_texts": [abstracted_intent],
            "success_conditions": success_conditions[:5],
            "failure_avoidance": failure_avoidance[:5],
            "subproblem_type": subproblem_type,
            "strategy_label": strategy_label,
            "prefer_actions": prefer_actions,
            "avoid_actions": avoid_actions,
            "applicability_scope": {
                "subproblem_type": subproblem_type,
                "strategy_label": strategy_label,
                "official_eval_status": "unresolved",
            },
            "source_instance_id": instance_id,
            "source_run_ids": [run_id] if run_id else [],
            "source_attempt_ids": [attempt_id] if attempt_id else [],
            "source_event_ids": [trace_id] if trace_id else [],
            "support_count": 1,
            "confidence": 0.82,
            "normalized_pattern_type": norm_pattern,
            "normalized_trigger_family": trigger,
            "normalized_advice_family": "avoid_repeat_failed_strategy",
            "family_id": f"{norm_pattern}__{trigger}__avoid_repeat_failed_strategy",
            "metadata": {
                "experience_polarity": "negative",
                "promotion_state": "promoted",
                "evidence_stage": "official_eval",
                "official_eval_refs": [eval_ref] if eval_ref else [],
                "official_eval_status": "unresolved",
                "task_summary": task_summary[:280],
                "changed_file_pattern": [
                    f".{path.rsplit('.', 1)[-1].lower()}"
                    for path in changed_files
                    if "." in path
                ][:4],
                "subproblem_type": subproblem_type,
                "strategy_label": strategy_label,
                "prefer_actions": prefer_actions,
                "avoid_actions": avoid_actions,
                "applicability_scope": {
                    "subproblem_type": subproblem_type,
                    "strategy_label": strategy_label,
                    "official_eval_status": "unresolved",
                },
            },
        }

    @staticmethod
    def _candidate_fix_actions(summary: Dict[str, Any]) -> List[str]:
        actions = ["reproduce_the_failing_path_with_target_validation_before_next_patch"]
        risk_flags = [str(x).strip() for x in (summary.get("risk_flags") or []) if str(x).strip()]
        if any(flag in risk_flags for flag in {"broad_exception", "bare_exception", "silent_pass"}):
            actions.append("remove_suppressive_fix_pattern_and_patch_target_logic_instead")
        if "missing_target_validation" in risk_flags:
            actions.append("run_targeted_validation_before_submission")
        return list(dict.fromkeys(actions))

    @staticmethod
    def _verification_commands(summary: Dict[str, Any]) -> List[str]:
        commands = [str(x).strip() for x in (summary.get("validation_commands") or []) if str(x).strip()]
        if not commands:
            commands = ["pytest -q"]
        return commands[:4]
