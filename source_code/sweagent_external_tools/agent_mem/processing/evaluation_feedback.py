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

from ..types import CompilerCardType
from ..storage.graph_store import GraphStore
from ..storage.episode_ledger_store import EpisodeLedgerStore
from .v21_shared import stable_patch_digest


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_") or "unknown"


class EvaluationFeedbackProcessor:
    """Maps official eval outcomes back into existing memory objects."""

    def __init__(
        self,
        graph_store: GraphStore,
        *,
        governance_policy: Any = None,
        episode_ledger_store: Optional[EpisodeLedgerStore] = None,
    ):
        self.graph_store = graph_store
        self.governance_policy = governance_policy
        self.episode_ledger_store = episode_ledger_store

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
            "written_card_ids": [],
            "failure_card_id": None,
            "patch_summary": {},
            "promoted_card_ids": [],
            "suppressed_card_ids": [],
            "subtask_eval_updates": {"subtasks": 0, "subtask_edges": 0},
        }

        if outcome_norm == "resolved":
            summary = self._build_patch_summary(
                patch_text=patch_text,
                changed_files=changed_files or [],
                validation_summary=validation_summary or {},
                supplied_summary=patch_summary or {},
            )
            report["patch_summary"] = summary
            for exp_id in related_ids:
                if self.graph_store.mark_experience_promoted(exp_id, eval_ref=eval_ref):
                    report["promoted_ids"].append(exp_id)
            success_card_id = self._write_success_path_card(
                instance_id=instance_id,
                eval_ref=eval_ref,
                patch_text=patch_text,
                summary=summary,
                validation_summary=validation_summary or {},
                task_summary=task_summary,
                run_id=run_id,
                attempt_id=attempt_id,
                trace_id=trace_id,
            )
            if success_card_id:
                report["written_card_ids"].append(success_card_id)
            bug_invariant_card_id = self._write_bug_invariant_card(
                instance_id=instance_id,
                eval_ref=eval_ref,
                patch_text=patch_text,
                summary=summary,
                validation_summary=validation_summary or {},
                task_summary=task_summary,
                run_id=run_id,
                attempt_id=attempt_id,
                trace_id=trace_id,
            )
            if bug_invariant_card_id:
                report["written_card_ids"].append(bug_invariant_card_id)
            self._apply_v21_feedback(
                report=report,
                instance_id=instance_id,
                run_id=run_id,
                attempt_id=attempt_id,
                outcome=outcome_norm,
                eval_ref=eval_ref,
            )
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
            self._apply_v21_feedback(
                report=report,
                instance_id=instance_id,
                run_id=run_id,
                attempt_id=attempt_id,
                outcome=outcome_norm,
                eval_ref=eval_ref,
            )
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

        if outcome_norm == "incomplete":
            timeout_card_id = self._write_timeout_governance_card(
                instance_id=instance_id,
                eval_ref=eval_ref,
                summary=summary,
                task_summary=task_summary,
                run_id=run_id,
                attempt_id=attempt_id,
                trace_id=trace_id,
            )
            if timeout_card_id:
                report["written_card_ids"].append(timeout_card_id)

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

        self._apply_v21_feedback(
            report=report,
            instance_id=instance_id,
            run_id=run_id,
            attempt_id=attempt_id,
            outcome=outcome_norm,
            eval_ref=eval_ref,
        )

        return report

    def _apply_v21_feedback(
        self,
        *,
        report: Dict[str, Any],
        instance_id: str,
        run_id: str,
        attempt_id: str,
        outcome: str,
        eval_ref: str,
    ) -> None:
        if self.governance_policy is not None:
            cards = self.graph_store.list_candidate_compiler_cards(
                instance_id=instance_id,
                run_id=run_id,
                attempt_id=attempt_id,
                max_results=200,
            )
            if cards:
                card_update = self.governance_policy.apply_official_feedback(
                    compiler_cards=cards,
                    outcome=outcome,
                    eval_ref=eval_ref,
                )
                for row in card_update.get("cards", []):
                    card_id = str(row.get("card_id") or "").strip()
                    if not card_id:
                        continue
                    self.graph_store.update_compiler_card_state(
                        card_id,
                        promotion_state=str(row.get("promotion_state") or ""),
                        eval_ref=eval_ref,
                        reason=f"official_eval_{outcome}",
                    )
                report["promoted_card_ids"] = list(card_update.get("promoted_ids", []) or [])
                report["suppressed_card_ids"] = list(card_update.get("suppressed_ids", []) or [])

        if self.episode_ledger_store is None or self.governance_policy is None:
            return
        filters: Dict[str, Any] = {"instance_id": instance_id}
        if attempt_id:
            filters["attempt_id"] = attempt_id
        if run_id:
            filters["run_id"] = run_id
        subtasks = self.episode_ledger_store.load_latest_records(
            stream="subtask_instances",
            key_field="subtask_instance_id",
            filters=filters,
        )
        edges = self.episode_ledger_store.load_latest_records(
            stream="subtask_edges",
            key_field="edge_id",
            filters=filters,
        )
        if not subtasks and not edges:
            return
        attachment = self.governance_policy.attach_eval_context(
            subtasks=subtasks,
            subtask_edges=edges,
            outcome=outcome,
            eval_ref=eval_ref,
        )
        subtask_report = self.episode_ledger_store.append_batch(
            [
                {
                    **row,
                    "record_id": stable_patch_digest(
                        {
                            "stream": "subtask_instances",
                            "logical_id": str(row.get("subtask_instance_id") or ""),
                            "eval_ref": eval_ref,
                            "outcome": outcome,
                            "payload": row,
                        }
                    ),
                }
                for row in attachment.get("subtasks", [])
            ],
            stream="subtask_instances",
        )
        edge_report = self.episode_ledger_store.append_batch(
            [
                {
                    **row,
                    "record_id": stable_patch_digest(
                        {
                            "stream": "subtask_edges",
                            "logical_id": str(row.get("edge_id") or ""),
                            "eval_ref": eval_ref,
                            "outcome": outcome,
                            "payload": row,
                        }
                    ),
                }
                for row in attachment.get("subtask_edges", [])
            ],
            stream="subtask_edges",
        )
        report["subtask_eval_updates"] = {
            "subtasks": int(subtask_report.get("written", 0) or 0),
            "subtask_edges": int(edge_report.get("written", 0) or 0),
        }

    def _write_success_path_card(
        self,
        *,
        instance_id: str,
        eval_ref: str,
        patch_text: str,
        summary: Dict[str, Any],
        validation_summary: Dict[str, Any],
        task_summary: str,
        run_id: str,
        attempt_id: str,
        trace_id: str,
    ) -> Optional[str]:
        changed_files = [str(x).strip() for x in (summary.get("changed_files") or []) if str(x).strip()]
        validation_commands = [str(x).strip() for x in (summary.get("validation_commands") or []) if str(x).strip()]
        if not patch_text.strip() and not changed_files:
            return None
        patch_digest = stable_patch_digest(
            {
                "instance_id": instance_id,
                "patch_text": patch_text,
                "changed_files": changed_files,
            }
        )
        patch_family = f"{instance_id}::{patch_digest[:12]}"
        repro_path, target_validation = self._split_validation_paths(validation_commands)
        submit_preconditions = ["target_validation_passed"]
        if changed_files:
            submit_preconditions.append("same_patch_family_revalidated")
        hint = self._build_success_path_hint(changed_files=changed_files, target_validation=target_validation)
        family_id = stable_patch_digest(
            {
                "card_type": CompilerCardType.SUCCESS_PATH.value,
                "instance_id": instance_id,
                "patch_family": patch_family,
            }
        )
        summary_id = self._find_attempt_summary_id(instance_id=instance_id, run_id=run_id, attempt_id=attempt_id)
        return self._upsert_compiler_card_with_support(
            {
                "card_id": stable_patch_digest(
                    {
                        "compiler_card": CompilerCardType.SUCCESS_PATH.value,
                        "family_id": family_id,
                    }
                ),
                "card_type": CompilerCardType.SUCCESS_PATH.value,
                "family_id": family_id,
                "instance_id": instance_id,
                "run_id": run_id or None,
                "attempt_id": attempt_id or None,
                "trace_id": trace_id or None,
                "hint": hint,
                "recommendation": hint,
                "confidence": 0.9,
                "support_count": 1,
                "instance_scope": "same-case",
                "patch_family": patch_family,
                "repro_path": repro_path[:2],
                "target_validation": target_validation[:2],
                "submit_preconditions": submit_preconditions[:3],
                "prefer_actions": [
                    "reuse_confirmed_repro_path",
                    "run_target_validation_before_submission",
                    "promote_minimal_fix_candidate_earlier",
                ],
                "avoid_actions": [],
                "subproblem_type": "form_minimal_patch",
                "strategy_label": "minimal_patch_then_target_validation",
                "governance_hardness": "strong",
                "changed_file_pattern": [
                    f".{path.rsplit('.', 1)[-1].lower()}"
                    for path in changed_files
                    if "." in path
                ][:4],
                "evidence_level": "official",
                "promotion_state": "promoted",
                "source_object_ids": [summary_id] if summary_id else [],
                "evidence_refs": [eval_ref] if eval_ref else [],
                "metadata": {
                    "evidence_stage": "official_eval",
                    "official_eval_refs": [eval_ref] if eval_ref else [],
                    "validation_summary": dict(validation_summary or {}),
                    "patch_summary": dict(summary),
                    "task_summary": task_summary[:280],
                    "governance_hardness": "strong",
                    "subproblem_type": "form_minimal_patch",
                    "strategy_label": "minimal_patch_then_target_validation",
                },
            },
            support_key=self._support_key(run_id=run_id, attempt_id=attempt_id, eval_ref=eval_ref),
        )

    def _write_timeout_governance_card(
        self,
        *,
        instance_id: str,
        eval_ref: str,
        summary: Dict[str, Any],
        task_summary: str,
        run_id: str,
        attempt_id: str,
        trace_id: str,
    ) -> Optional[str]:
        changed_files = [str(x).strip() for x in (summary.get("changed_files") or []) if str(x).strip()]
        validation_commands = [str(x).strip() for x in (summary.get("validation_commands") or []) if str(x).strip()]
        if changed_files and validation_commands:
            return None
        budget_hints = {
            "max_new_repro_scripts_after_repro_confirmed": 0,
            "max_broad_tests_before_patch": 0,
            "max_target_validation_retries_without_patch_upgrade": 1,
        }
        family_id = stable_patch_digest(
            {
                "card_type": CompilerCardType.TIMEOUT_GOVERNANCE.value,
                "instance_id": instance_id,
                "failure_family": "ad_hoc_repro_script_loop",
            }
        )
        summary_id = self._find_attempt_summary_id(instance_id=instance_id, run_id=run_id, attempt_id=attempt_id)
        hint = (
            "Timeout governance: once reproduction is confirmed, do not create new repro scripts or run broad "
            "regression before a real patch candidate exists. Reuse the confirmed repro path and either submit the "
            "minimal fix candidate after target validation or stop early."
        )
        return self._upsert_compiler_card_with_support(
            {
                "card_id": stable_patch_digest(
                    {
                        "compiler_card": CompilerCardType.TIMEOUT_GOVERNANCE.value,
                        "family_id": family_id,
                    }
                ),
                "card_type": CompilerCardType.TIMEOUT_GOVERNANCE.value,
                "family_id": family_id,
                "instance_id": instance_id,
                "run_id": run_id or None,
                "attempt_id": attempt_id or None,
                "trace_id": trace_id or None,
                "hint": hint,
                "recommendation": hint,
                "confidence": 0.86,
                "support_count": 1,
                "failure_family": "ad_hoc_repro_script_loop",
                "trigger_scope": "same-case",
                "prefer_actions": [
                    "reuse_confirmed_repro_path",
                    "promote_minimal_fix_candidate_earlier",
                    "run_target_validation_before_submission",
                ],
                "avoid_actions": [
                    "create_new_repro_script_after_repro_confirmed",
                    "run_broad_regression_before_patch_candidate_exists",
                ],
                "budget_hints": budget_hints,
                "normalized_pattern_type": "negative_strategy",
                "subproblem_type": "reproduce_issue",
                "strategy_label": "ad_hoc_repro_script_loop",
                "governance_hardness": "guardrail",
                "evidence_level": "official",
                "promotion_state": "promoted",
                "source_object_ids": [summary_id] if summary_id else [],
                "evidence_refs": [eval_ref] if eval_ref else [],
                "metadata": {
                    "evidence_stage": "official_eval",
                    "official_eval_refs": [eval_ref] if eval_ref else [],
                    "task_summary": task_summary[:280],
                    "budget_hints": budget_hints,
                    "governance_hardness": "guardrail",
                    "subproblem_type": "reproduce_issue",
                    "strategy_label": "ad_hoc_repro_script_loop",
                    "runtime_guard": {
                        "blocked_action_patterns": [
                            "create_new_repro_script_after_repro_confirmed",
                            "run_broad_regression_before_patch_candidate_exists",
                        ]
                    },
                },
            },
            support_key=self._support_key(run_id=run_id, attempt_id=attempt_id, eval_ref=eval_ref),
        )

    def _write_bug_invariant_card(
        self,
        *,
        instance_id: str,
        eval_ref: str,
        patch_text: str,
        summary: Dict[str, Any],
        validation_summary: Dict[str, Any],
        task_summary: str,
        run_id: str,
        attempt_id: str,
        trace_id: str,
    ) -> Optional[str]:
        changed_files = [str(x).strip() for x in (summary.get("changed_files") or []) if str(x).strip()]
        if not patch_text.strip() and not changed_files:
            return None
        change_type = self._infer_change_type(patch_text)
        key_lines = self._extract_key_added_lines(patch_text)
        target_function = self._extract_target_function(patch_text)
        validation_invariant = self._extract_validation_invariant(validation_summary)
        bug_semantic = self._build_bug_semantic(
            target_function=target_function,
            change_type=change_type,
            changed_files=changed_files,
        )
        key_line_hint = key_lines[0] if key_lines else "see diff"
        hint = (
            f"[BugInvariant] Fix: {bug_semantic}. "
            f"Key change: {key_line_hint[:80]}. "
            f"Validate: {validation_invariant}."
        )[:300]
        family_id = stable_patch_digest(
            {
                "card_type": CompilerCardType.BUG_INVARIANT.value,
                "instance_id": instance_id,
                "changed_files": changed_files[:2],
            }
        )
        return self._upsert_compiler_card_with_support(
            {
                "card_id": stable_patch_digest(
                    {
                        "compiler_card": CompilerCardType.BUG_INVARIANT.value,
                        "family_id": family_id,
                    }
                ),
                "card_type": CompilerCardType.BUG_INVARIANT.value,
                "family_id": family_id,
                "instance_id": instance_id,
                "run_id": run_id or None,
                "attempt_id": attempt_id or None,
                "trace_id": trace_id or None,
                "hint": hint,
                "recommendation": hint,
                "confidence": 0.95,
                "support_count": 1,
                "instance_scope": "same-case",
                "bug_semantic": bug_semantic,
                "minimal_patch_signature": {
                    "files_touched": changed_files[:3],
                    "change_type": change_type,
                    "key_lines": key_lines[:3],
                },
                "validation_invariant": validation_invariant,
                "prefer_actions": [
                    "apply_same_patch_family",
                    "run_target_validation_before_submission",
                ],
                "avoid_actions": [],
                "governance_hardness": "strong",
                "evidence_level": "official",
                "promotion_state": "promoted",
                "source_object_ids": [],
                "evidence_refs": [eval_ref] if eval_ref else [],
                "metadata": {
                    "evidence_stage": "official_eval",
                    "official_eval_refs": [eval_ref] if eval_ref else [],
                    "bug_semantic": bug_semantic,
                    "minimal_patch_signature": {
                        "files_touched": changed_files[:3],
                        "change_type": change_type,
                        "key_lines": key_lines[:3],
                    },
                    "validation_invariant": validation_invariant,
                    "task_summary": task_summary[:280],
                    "governance_hardness": "strong",
                },
            },
            support_key=self._support_key(run_id=run_id, attempt_id=attempt_id, eval_ref=eval_ref),
        )

    @staticmethod
    def _infer_change_type(patch_text: str) -> str:
        if not patch_text:
            return "unknown"
        added = "\n".join(
            line[1:] for line in patch_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        if re.search(r"\bif\b[^:]*:", added):
            return "condition_fix"
        if re.search(r"\braise\b|\bassert\b", added):
            return "missing_check"
        if re.search(r"\breturn\b", added):
            return "wrong_return"
        if re.search(r"\bdef\b|\bclass\b", added):
            return "new_function_or_class"
        return "code_change"

    @staticmethod
    def _extract_key_added_lines(patch_text: str) -> List[str]:
        lines = [
            line[1:].strip()
            for line in patch_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
            and line[1:].strip()
            and not line[1:].strip().startswith("#")
        ]
        return [line for line in lines if len(line) > 5][:3]

    @staticmethod
    def _extract_target_function(patch_text: str) -> str:
        # Try @@ header context first (function or class name)
        for m in re.finditer(r"@@ [^@]+ @@ (.*)", patch_text):
            context = m.group(1).strip()
            if not context:
                continue
            fn = re.search(r"def\s+(\w+)", context)
            if fn:
                return fn.group(1)
            cls = re.search(r"class\s+(\w+)", context)
            if cls:
                return cls.group(1)
        # Fall back to added lines
        for line in patch_text.splitlines():
            if line.startswith("+") and "def " in line:
                fn = re.search(r"def\s+(\w+)", line)
                if fn:
                    return fn.group(1)
        return "target_function"

    @staticmethod
    def _extract_validation_invariant(validation_summary: Dict[str, Any]) -> str:
        commands = (
            validation_summary.get("commands")
            or validation_summary.get("verification_commands")
            or []
        )
        if commands:
            return str(commands[0])[:80]
        return "run targeted test"

    @staticmethod
    def _build_bug_semantic(*, target_function: str, change_type: str, changed_files: List[str]) -> str:
        file_hint = changed_files[0].split("/")[-1] if changed_files else "target file"
        return f"{change_type} in {target_function}() at {file_hint}"

    def _upsert_compiler_card_with_support(
        self,
        payload: Dict[str, Any],
        *,
        support_key: str,
    ) -> str:
        row = dict(payload)
        card_id = str(row.get("card_id") or "").strip()
        existing = dict(self.graph_store.compiler_cards_v21.get(card_id, {})) if card_id else {}
        metadata = dict(existing.get("metadata") or {})
        metadata.update(dict(row.get("metadata") or {}))

        support_keys = [str(x).strip() for x in (metadata.get("support_keys") or []) if str(x).strip()]
        support_count = int(existing.get("support_count", 0) or 0)
        if not support_key:
            support_key = stable_patch_digest({"card_id": card_id, "payload": row})
        if support_key not in support_keys:
            support_keys.append(support_key)
            support_count += max(1, int(row.get("support_count", 1) or 1))

        row["support_count"] = max(1, support_count)
        row["confidence"] = max(float(existing.get("confidence", 0.0) or 0.0), float(row.get("confidence", 0.0) or 0.0))
        metadata["support_keys"] = support_keys[-20:]
        row["metadata"] = metadata
        return self.graph_store.upsert_compiler_card_v21(row)

    @staticmethod
    def _split_validation_paths(validation_commands: List[str]) -> tuple[List[str], List[str]]:
        repro_path: List[str] = []
        target_validation: List[str] = []
        for command in validation_commands:
            lowered = str(command).lower()
            if any(token in lowered for token in ("reproduce", "test_", "quiet", "plot")):
                repro_path.append(command)
            if "pytest" in lowered or "python -m pytest" in lowered:
                target_validation.append(command)
        if not repro_path and validation_commands:
            repro_path = validation_commands[:1]
        if not target_validation and validation_commands:
            target_validation = validation_commands[:1]
        return repro_path[:2], target_validation[:2]

    @staticmethod
    def _build_success_path_hint(*, changed_files: List[str], target_validation: List[str]) -> str:
        file_hint = changed_files[0] if changed_files else "the localized file"
        validation_hint = target_validation[0] if target_validation else "the focused target validation"
        return (
            f"Reuse the last resolved path: keep the patch family centered on {file_hint}, rerun "
            f"{validation_hint}, and submit once the focused target validation passes."
        )[:280]

    def _find_attempt_summary_id(self, *, instance_id: str, run_id: str, attempt_id: str) -> str:
        best_id = ""
        best_score = -1
        for summary_id, row in self.graph_store.attempt_summaries_v1.items():
            if str(row.get("instance_id") or "").strip() != str(instance_id or "").strip():
                continue
            if attempt_id and str(row.get("attempt_id") or "").strip() != str(attempt_id or "").strip():
                continue
            score = 0
            if attempt_id and str(row.get("attempt_id") or "").strip() == str(attempt_id or "").strip():
                score += 5
            if run_id and str(row.get("run_id") or "").strip() == str(run_id or "").strip():
                score += 2
            if score > best_score:
                best_id = str(summary_id)
                best_score = score
        return best_id

    @staticmethod
    def _support_key(*, run_id: str, attempt_id: str, eval_ref: str) -> str:
        parts = [str(x).strip() for x in (run_id, attempt_id, eval_ref) if str(x).strip()]
        return "::".join(parts)

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
