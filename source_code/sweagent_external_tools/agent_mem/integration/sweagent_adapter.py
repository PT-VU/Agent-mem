"""
SWEAgentAdapter: Adapter for integrating Agent-mem with SWE-agent.

This adapter connects the existing sweagent_ext_tools framework with the new
Agent-mem system, replacing the simple Tool A/Tool B with full memory capabilities.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pathlib import Path

from ..core.problem_file import ProblemFile, ActionType, Outcome
from ..processing.action_logger import ActionLogger
from ..processing.abstract_experience import AbstractExperienceBuilder
from ..processing.evaluation_feedback import EvaluationFeedbackProcessor
from ..processing.extraction_orchestrator import ExtractionOrchestrator
from ..processing.failure_card_builder import FailureCardBuilder
from ..processing.kg_writer import KGWriter, EmbeddingGenerator
from ..processing.rca_agent import RCAAgent
from ..storage.graph_store import GraphStore
from ..retrieval.memory_agent import MemoryAgent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class SWEAgentAdapter:
    """
    Adapter that integrates Agent-mem with SWE-agent's external tool framework.

    Replaces the existing Tool A (plan_generated) and Tool B (action_error)
    with full memory-enhanced versions.
    """

    def __init__(self,
                 storage_dir: Optional[str] = None,
                 evidence_dir: Optional[str] = None,
                 *,
                 embedding_model: str = "sentence-transformers",
                 embedding_model_name: str = "all-MiniLM-L6-v2",
                 embedding_dimension: int = 384):
        """
        Initialize SWEAgentAdapter.

        Args:
            storage_dir: Directory for graph storage
            evidence_dir: Directory for evidence storage
        """
        # Initialize core components
        self.graph_store = GraphStore(storage_dir)
        self.action_logger = ActionLogger(self.graph_store, evidence_dir)
        self.kg_writer = KGWriter(
            self.graph_store,
            embedding_generator=EmbeddingGenerator(
                embedding_dim=embedding_dimension,
                model=embedding_model,
                model_name=embedding_model_name,
            ),
        )
        self.memory_agent = MemoryAgent(self.graph_store)
        self.abstract_experience_builder = AbstractExperienceBuilder()
        self.extraction_orchestrator = ExtractionOrchestrator.from_env()
        self.evaluation_feedback = EvaluationFeedbackProcessor(self.graph_store)
        self.failure_card_builder = FailureCardBuilder()
        self.rca_agent = RCAAgent(self.graph_store.observation_kg)
        self.enable_online_embeddings = _env_bool("AGENT_MEM_ENABLE_ONLINE_EMBEDDINGS", True)

        # State tracking
        self.current_task_id: Optional[str] = None
        self.task_context: Dict[str, Any] = {}
        self._state_file: Optional[Path] = None
        self._rw_map_file: Optional[Path] = None
        if storage_dir:
            storage_path = Path(storage_dir)
            storage_path.mkdir(parents=True, exist_ok=True)
            self._state_file = storage_path / "active_tasks.json"
            self._rw_map_file = storage_path / "experience_rw_map.jsonl"

    def _maybe_generate_embeddings(self, problem_file: ProblemFile) -> None:
        if not self.enable_online_embeddings:
            return
        self.kg_writer.write_action_with_embeddings(problem_file)

    def _embedding_provider(self) -> str:
        if not self.enable_online_embeddings:
            return "disabled"
        return self.kg_writer.embedding_generator.provider

    def _sanitize_key(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
        return cleaned[:120] or "unknown"

    @staticmethod
    def _is_infra_error_type(error_type: str) -> bool:
        normalized = (error_type or "").strip().lower()
        return normalized in {"environment_error", "tool_timeout", "permission_error", "timeout"}

    def _load_active_tasks(self) -> Dict[str, str]:
        if not self._state_file or not self._state_file.exists():
            return {}
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            tasks = data.get("active_tasks", {})
            if isinstance(tasks, dict):
                return {str(k): str(v) for k, v in tasks.items()}
        except Exception:
            return {}
        return {}

    def _save_active_tasks(self, active_tasks: Dict[str, str]) -> None:
        if not self._state_file:
            return
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "active_tasks": active_tasks,
        }
        self._state_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_task_key(self, event_data: Dict[str, Any]) -> str:
        instance_id = event_data.get("instance_id") or event_data.get("agent") or "unknown-agent"
        run_id = event_data.get("run_id") or event_data.get("batch_run_id")
        attempt_id = event_data.get("attempt_id")
        if run_id and attempt_id:
            return (
                f"{self._sanitize_key(str(run_id))}:"
                f"{self._sanitize_key(str(attempt_id))}:"
                f"{self._sanitize_key(str(instance_id))}"
            )
        if run_id:
            return f"{self._sanitize_key(str(run_id))}:{self._sanitize_key(str(instance_id))}"
        return self._sanitize_key(str(instance_id))

    def _event_source_fields(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "source_event_id": event_data.get("trace_id"),
            "source_instance_id": event_data.get("instance_id"),
            "source_run_id": event_data.get("run_id") or event_data.get("batch_run_id"),
            "source_attempt_id": event_data.get("attempt_id"),
        }

    @staticmethod
    def _extract_read_ids(retrieval_result: Dict[str, Any]) -> List[str]:
        ids: List[str] = []
        for item in retrieval_result.get("recommendations", []) or []:
            if not isinstance(item, dict):
                continue
            for key in (
                "summary_id",
                "experience_id",
                "card_id",
                "belief_id",
                "pattern_id",
                "rule_id",
                "action_id",
                "task_id",
                "source_task_id",
            ):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    ids.append(val.strip())
                    break
        return list(dict.fromkeys(ids))

    def _append_rw_map(
        self,
        *,
        event_name: str,
        task_id: Optional[str],
        event_data: Dict[str, Any],
        read_ids: Optional[List[str]] = None,
        write_ids: Optional[List[str]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._rw_map_file:
            return
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_name,
            "task_id": task_id,
            "instance_id": event_data.get("instance_id"),
            "run_id": event_data.get("run_id") or event_data.get("batch_run_id"),
            "attempt_id": event_data.get("attempt_id"),
            "trace_id": event_data.get("trace_id"),
            "read_ids": list(dict.fromkeys(read_ids or [])),
            "write_ids": list(dict.fromkeys(write_ids or [])),
            "version": "v2",
        }
        if extra:
            payload["extra"] = extra
        try:
            self._rw_map_file.parent.mkdir(parents=True, exist_ok=True)
            with self._rw_map_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            # Keep runtime path robust: rw-map logging is best-effort.
            return

    @staticmethod
    def _merge_unique_strings(
        first: List[str],
        second: List[str],
        *,
        limit: int,
    ) -> List[str]:
        out: List[str] = []
        seen = set()
        for src in (first, second):
            for item in src:
                text = str(item).strip()
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(text)
                if len(out) >= limit:
                    return out
        return out

    def _build_run_done_context(
        self,
        *,
        event_data: Dict[str, Any],
        actions: List[ProblemFile],
        submission_success: bool,
        exit_status: str,
    ) -> Dict[str, Any]:
        changed_files: List[str] = []
        ad_hoc_scripts: List[str] = []
        for action in actions:
            changed_files = self._merge_unique_strings(changed_files, list(action.touched_files or []), limit=20)
            for text in (action.action_text, action.intent_text):
                if not isinstance(text, str):
                    continue
                for match in re.finditer(r"\b((?:test|reproduce)_[\w.\-]+\.py)\b", text, flags=re.IGNORECASE):
                    ad_hoc_scripts = self._merge_unique_strings(ad_hoc_scripts, [match.group(1)], limit=12)
        validation_commands: List[str] = []
        if any(action.action_type == ActionType.RUN_TEST for action in actions):
            validation_commands = self._merge_unique_strings(validation_commands, ["pytest -q"], limit=6)
        return {
            "task_problem_excerpt": str(self.task_context.get("instruction", "") or self.task_context.get("summary", ""))[:400],
            "changed_files": changed_files,
            "step_count": len(actions),
            "ad_hoc_script_count": len(ad_hoc_scripts),
            "ad_hoc_script_names": ad_hoc_scripts[:8],
            "patch_summary": {
                "changed_file_count": len(changed_files),
                "has_submission": submission_success,
                "exit_status": exit_status,
            },
            "validation_summary": {"commands": validation_commands[:6]},
            "submission_status": "submitted" if submission_success else exit_status,
            "submission_success": submission_success,
            "official_eval_status": "unknown",
        }

    def _build_fallback_attempt_summary(
        self,
        *,
        task_id: str,
        event_data: Dict[str, Any],
        actions: List[ProblemFile],
        run_done_context: Dict[str, Any],
        final_outcome: str,
    ) -> Dict[str, Any]:
        actual_execution_outline: List[str] = []
        for action in actions:
            block = self.memory_agent._infer_subproblem_type_for_planning(
                current_action=f"{action.intent_text} {action.action_text}",
                current_problem_file=action,
            )
            if block not in actual_execution_outline:
                actual_execution_outline.append(block)
            if len(actual_execution_outline) >= 6:
                break

        source_action_ids = [
            str(action.action_id).strip()
            for action in actions
            if str(action.action_id).strip()
        ][:20]
        changed_files = list(run_done_context.get("changed_files") or [])[:6]
        next_best_actions: List[str] = []
        if changed_files:
            next_best_actions.append("validate_current_changed_files_before_broadening_scope")
        if final_outcome == "submitted":
            next_best_actions.append("wait_for_official_eval_before_promoting_this_path")
        elif final_outcome in {"unresolved", "incomplete", "failed", "timeout"}:
            next_best_actions.append("narrow_the_failure_to_one_subproblem_before_retry")

        return {
            "schema_version": "1.0",
            "summary_id": "",
            "instance_id": str(event_data.get("instance_id") or ""),
            "run_id": str(event_data.get("run_id") or event_data.get("batch_run_id") or ""),
            "attempt_id": str(event_data.get("attempt_id") or ""),
            "trace_id": str(event_data.get("trace_id") or ""),
            "task_id": task_id,
            "problem_goal": str(run_done_context.get("task_problem_excerpt") or "")[:280],
            "initial_plan_outline": [],
            "actual_execution_outline": actual_execution_outline,
            "plan_success": bool(actions),
            "final_outcome": final_outcome,
            "confirmed_signals": [],
            "failed_strategies": [],
            "best_partial_progress": [],
            "unverified_hypotheses": [],
            "next_best_actions": next_best_actions[:6],
            "source_action_ids": source_action_ids,
            "subblock_analysis": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_action_error_micro_pattern(
        self,
        *,
        task_id: str,
        event_data: Dict[str, Any],
        query_type: str,
        error_type: str,
        error_message: str,
        current_action: str,
        action_id: str,
        repair_suggestions: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if self._is_infra_error_type(error_type):
            return None

        recommendations = repair_suggestions.get("recommendations", []) or []
        next_step_fix = str(repair_suggestions.get("next_step_fix", "")).strip()
        if not next_step_fix:
            for row in recommendations:
                if not isinstance(row, dict):
                    continue
                next_step_fix = str(
                    row.get("repair_action")
                    or row.get("recommendation")
                    or row.get("summary")
                    or ""
                ).strip()
                if next_step_fix:
                    break
        if not next_step_fix:
            return None

        verification_commands: List[str] = []
        for row in recommendations:
            if not isinstance(row, dict):
                continue
            verification_commands = self._merge_unique_strings(
                verification_commands,
                [str(x) for x in (row.get("verification_commands") or []) if str(x).strip()],
                limit=6,
            )
        if query_type == "test_failure_fix":
            verification_commands = self._merge_unique_strings(
                verification_commands,
                ["pytest -q"],
                limit=6,
            )

        confidence = max(0.2, min(0.7, float(repair_suggestions.get("confidence", 0.0) or 0.0) * 0.8))
        return {
            "trigger_signature": {
                "error_type": error_type or "unknown",
                "query_type": query_type or "error_recovery",
                "action_type": "action_error",
            },
            "fix_action_template": next_step_fix[:280],
            "expected_verification": verification_commands[:4],
            "evidence_refs": [action_id] + list(repair_suggestions.get("evidence_refs", [])[:8]),
            "support": 1,
            "confidence": confidence,
            "trace_id": event_data.get("trace_id"),
            "metadata": {
                "source": "action_error_micro_extraction",
                "task_id": task_id,
                "query_type": query_type,
                "provisional": True,
                "error_message_excerpt": str(error_message or "")[:240],
                "current_action_excerpt": str(current_action or "")[:240],
                **self._event_source_fields(event_data),
            },
        }

    def _build_action_error_validation_rule(
        self,
        *,
        task_id: str,
        event_data: Dict[str, Any],
        query_type: str,
        error_type: str,
        repair_suggestions: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if self._is_infra_error_type(error_type):
            return None

        verification_commands: List[str] = []
        for row in repair_suggestions.get("recommendations", []) or []:
            if not isinstance(row, dict):
                continue
            verification_commands = self._merge_unique_strings(
                verification_commands,
                [str(x) for x in (row.get("verification_commands") or []) if str(x).strip()],
                limit=6,
            )
        if query_type == "test_failure_fix":
            verification_commands = self._merge_unique_strings(verification_commands, ["pytest -q"], limit=6)
        if not verification_commands:
            return None

        return {
            "when": f"before retry after {error_type or 'error'}",
            "should_check": verification_commands[0],
            "support": 1,
            "confidence": max(0.2, min(0.6, float(repair_suggestions.get("confidence", 0.0) or 0.0) * 0.7)),
            "trace_id": event_data.get("trace_id"),
            "evidence_refs": list(repair_suggestions.get("evidence_refs", [])[:8]),
            "metadata": {
                "source": "action_error_validation_guard",
                "task_id": task_id,
                "query_type": query_type,
                "verification_commands": verification_commands[:4],
                **self._event_source_fields(event_data),
            },
        }

    def _apply_failure_card_patch(
        self,
        *,
        card_id: str,
        patch: Dict[str, Any],
    ) -> None:
        row = dict(self.graph_store.failure_cards_v2.get(card_id, {}))
        if not row:
            return
        if isinstance(patch.get("error_signature"), dict):
            sig = dict(row.get("error_signature", {}))
            sig.update(patch["error_signature"])
            row["error_signature"] = sig
        for key, limit in (
            ("candidate_fix_actions", 12),
            ("verification_commands", 8),
            ("evidence_refs", 50),
            ("root_cause_nodes", 20),
            ("propagation_chain", 20),
        ):
            row[key] = self._merge_unique_strings(
                list(row.get(key, []) or []),
                list(patch.get(key, []) or []),
                limit=limit,
            )
        if patch.get("error_module"):
            row["error_module"] = patch["error_module"]
        if patch.get("confidence") is not None:
            row["confidence"] = max(float(row.get("confidence", 0.0)), float(patch.get("confidence", 0.0)))
        metadata = dict(row.get("metadata", {}))
        patch_meta = patch.get("metadata") if isinstance(patch.get("metadata"), dict) else {}
        if patch_meta:
            # Keep nested links/source fields from original payload while appending new fields.
            for k, v in patch_meta.items():
                if k in {"source_event_ids", "source_run_ids", "source_attempt_ids"}:
                    metadata[k] = self._merge_unique_strings(
                        list(metadata.get(k, []) or []),
                        list(v if isinstance(v, list) else []),
                        limit=50,
                    )
                elif k == "links":
                    links = dict(metadata.get("links", {}))
                    if isinstance(v, dict):
                        for lk, lv in v.items():
                            if isinstance(lv, list):
                                links[lk] = self._merge_unique_strings(
                                    list(links.get(lk, []) or []),
                                    list(lv),
                                    limit=50,
                                )
                            else:
                                links[lk] = lv
                    metadata["links"] = links
                else:
                    metadata[k] = v
        row["metadata"] = metadata
        self.graph_store.failure_cards_v2[card_id] = row

    def _ensure_task_context(self, event_data: Dict[str, Any], event_name: str) -> str:
        active_tasks = self._load_active_tasks()
        task_key = self._build_task_key(event_data)
        task_id = active_tasks.get(task_key)
        is_new = False
        agent_name = event_data.get("agent", "unknown")

        if not task_id:
            task_id = f"task_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{self._sanitize_key(agent_name)}"
            active_tasks[task_key] = task_id
            self._save_active_tasks(active_tasks)
            is_new = True

        self.current_task_id = task_id
        self.action_logger.start_task(
            task_id,
            {
                "agent": agent_name,
                "event": event_name,
                "task_key": task_key,
                "resumed": not is_new,
                "instance_id": event_data.get("instance_id"),
                "run_id": event_data.get("run_id") or event_data.get("batch_run_id"),
                "attempt_id": event_data.get("attempt_id"),
                "trace_id": event_data.get("trace_id"),
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            resume_from_existing=True,
        )
        return task_id

    def handle_plan_generated(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle plan_generated event (Tool A replacement).

        This corresponds to 范式 A: Planning-time 经验注入 from architecture doc.

        Args:
            event_data: Event data from SWE-agent

        Returns:
            Response with planning tips and evidence
        """
        # Extract event data
        agent_name = event_data.get("agent", "unknown")
        thought = event_data.get("thought", "")
        action = event_data.get("action", "")
        self.task_context = {
            "instruction": thought or action,
            "summary": action,
            "env_signature": {
                "run_id": event_data.get("run_id") or event_data.get("batch_run_id"),
                "attempt_id": event_data.get("attempt_id"),
                "instance_id": event_data.get("instance_id"),
            },
        }

        task_id = self._ensure_task_context(event_data, "plan_generated")

        # Log the planning action
        problem_file = self.action_logger.log_action(
            action_type=ActionType.TOOL_CALL,
            intent_text="Generate plan for task",
            action_text=action,
            action_family="planning",
            instance_id=event_data.get("instance_id"),
            run_id=event_data.get("run_id") or event_data.get("batch_run_id"),
            agent_name=agent_name,
            source_event="plan_generated",
            step_index=event_data.get("step_index"),
            trace_id=event_data.get("trace_id"),
            inputs={"thought": thought, "action": action},
            tool_calls=[{"type": "plan_generation", "content": action}],
            outcome=Outcome.SUCCESS,
            metadata={
                "event": "plan_generated",
                "agent": agent_name,
                **self._event_source_fields(event_data),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        # Generate embeddings (optional in low-latency online mode)
        self._maybe_generate_embeddings(problem_file)

        # Retrieve relevant experience for planning
        planning_tips = self.memory_agent.retrieve_for_query_type(
            query_type="planning",
            task_context=self.task_context,
            current_action=action,
            agent_name=agent_name,
            current_problem_file=problem_file,
            embedding_view="emb_task_sem",
            runtime_guard=event_data.get("runtime_guard"),
        )

        # Prepare response
        response = {
            "version": "v1",
            "event_handled": "plan_generated",
            "task_id": task_id,
            "action_id": problem_file.action_id,
            "trace_id": problem_file.trace_id,
            "query_type": planning_tips.get("retrieval_debug", {}).get("query_type"),
            "planning_tips": planning_tips.get("recommendations", []),
            "evidence_refs": planning_tips.get("evidence_refs", []),
            "confidence": planning_tips.get("confidence", 0.0),
            "retrieval_debug": planning_tips.get("retrieval_debug", {}),
            "embedding_provider": self._embedding_provider(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._append_rw_map(
            event_name="plan_generated",
            task_id=task_id,
            event_data=event_data,
            read_ids=self._extract_read_ids(planning_tips),
            write_ids=[],
            extra={
                "query_type": response.get("query_type"),
                "selected_subgraph_count": response.get("retrieval_debug", {}).get("selected_subgraph_count", 0),
            },
        )

        self.graph_store.save()
        return response

    def handle_action_error(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle action_error event (Tool B replacement).

        This corresponds to 范式 B: Execution-time 出错回忆 from architecture doc.

        Args:
            event_data: Event data from SWE-agent

        Returns:
            Response with repair suggestions and evidence
        """
        # Extract event data
        agent_name = event_data.get("agent", "unknown")
        error_type = event_data.get("error_type", "unknown")
        error_message = event_data.get("error_message", "")
        thought = event_data.get("thought", "")
        action = event_data.get("action", "")
        self.task_context = {
            "instruction": thought or action,
            "summary": error_message[:240],
            "env_signature": {
                "run_id": event_data.get("run_id") or event_data.get("batch_run_id"),
                "attempt_id": event_data.get("attempt_id"),
                "instance_id": event_data.get("instance_id"),
            },
        }

        task_id = self._ensure_task_context(event_data, "action_error")

        # Log the failed action
        problem_file = self.action_logger.log_action(
            action_type=ActionType.TOOL_CALL,
            intent_text=thought,
            action_text=action,
            action_family="error_recovery",
            instance_id=event_data.get("instance_id"),
            run_id=event_data.get("run_id") or event_data.get("batch_run_id"),
            agent_name=agent_name,
            source_event="action_error",
            step_index=event_data.get("step_index"),
            trace_id=event_data.get("trace_id"),
            inputs={"action": action, "error_type": error_type},
            tool_calls=[{"type": "action_execution", "content": action}],
            stderr=error_message,
            outcome=Outcome.FAIL,
            metadata={
                "event": "action_error",
                "agent": agent_name,
                "error_type": error_type,
                **self._event_source_fields(event_data),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        # Generate embeddings (optional in low-latency online mode)
        self._maybe_generate_embeddings(problem_file)

        # Retrieve repair suggestions
        repair_query_type = "test_failure_fix" if "test" in error_type.lower() else "error_recovery"
        repair_suggestions = self.memory_agent.retrieve_for_query_type(
            query_type=repair_query_type,
            current_action=action,
            current_problem_file=problem_file,
            error_type=error_type,
            error_message=error_message,
            embedding_view="emb_error_sig",
        )

        micro_write_ids: List[str] = []
        micro_pattern_payload = self._build_action_error_micro_pattern(
            task_id=task_id,
            event_data=event_data,
            query_type=repair_query_type,
            error_type=error_type,
            error_message=error_message,
            current_action=action,
            action_id=problem_file.action_id,
            repair_suggestions=repair_suggestions,
        )
        if micro_pattern_payload:
            micro_write_ids.append(self.graph_store.upsert_repair_pattern_v2(micro_pattern_payload))

        validation_rule_payload = self._build_action_error_validation_rule(
            task_id=task_id,
            event_data=event_data,
            query_type=repair_query_type,
            error_type=error_type,
            repair_suggestions=repair_suggestions,
        )
        if validation_rule_payload:
            micro_write_ids.append(self.graph_store.upsert_preventive_rule_v2(validation_rule_payload))

        # Prepare response
        response = {
            "version": "v1",
            "event_handled": "action_error",
            "task_id": task_id,
            "action_id": problem_file.action_id,
            "trace_id": problem_file.trace_id,
            "query_type": repair_suggestions.get("retrieval_debug", {}).get("query_type"),
            "repair_suggestions": repair_suggestions.get("recommendations", []),
            "evidence_refs": repair_suggestions.get("evidence_refs", []),
            "confidence": repair_suggestions.get("confidence", 0.0),
            "retrieval_debug": repair_suggestions.get("retrieval_debug", {}),
            "next_step_fix": repair_suggestions.get("next_step_fix", ""),
            "expected_outcome": repair_suggestions.get("expected_outcome", ""),
            "micro_extraction": {
                "triggered": bool(micro_write_ids),
                "write_ids": list(micro_write_ids),
            },
            "embedding_provider": self._embedding_provider(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._append_rw_map(
            event_name="action_error",
            task_id=task_id,
            event_data=event_data,
            read_ids=self._extract_read_ids(repair_suggestions),
            write_ids=micro_write_ids,
            extra={
                "query_type": response.get("query_type"),
                "error_type": error_type,
                "selected_subgraph_count": response.get("retrieval_debug", {}).get("selected_subgraph_count", 0),
                "micro_extraction_triggered": bool(micro_write_ids),
            },
        )

        self.graph_store.save()
        return response

    def handle_run_done(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle run completion and clear active task mapping."""
        active_tasks = self._load_active_tasks()
        task_key = self._build_task_key(event_data)
        task_id = active_tasks.pop(task_key, None)
        self._save_active_tasks(active_tasks)
        self.graph_store.save()
        synthesized_task = False
        if not task_id:
            # Fallback path: keep run_done extraction observable even when active task index is missing.
            synthesized_task = True
            task_id = (
                f"task_run_done_fallback_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_"
                f"{self._sanitize_key(str(event_data.get('instance_id') or event_data.get('agent') or 'unknown'))}"
            )

        exit_status = str(event_data.get("exit_status", "unknown"))
        has_submission = bool(event_data.get("has_submission", False))
        submission_success = bool(has_submission or exit_status == "submitted")
        resolved_like_success = exit_status in {"done", "success"} and not submission_success
        task_closed_cleanly = submission_success or resolved_like_success
        self.action_logger.start_task(
            task_id,
            {
                "agent": event_data.get("agent", "unknown"),
                "event": "run_done",
                "task_key": task_key,
                "instance_id": event_data.get("instance_id"),
                "run_id": event_data.get("run_id") or event_data.get("batch_run_id"),
                "attempt_id": event_data.get("attempt_id"),
                "trace_id": event_data.get("trace_id"),
                "synthesized_task": synthesized_task,
            },
            resume_from_existing=True,
        )
        summary = (
            f"run_done exit_status={exit_status} has_submission={has_submission} "
            f"submission_success={submission_success} evaluation_success=unknown"
        )
        task_summary = self.action_logger.end_task(task_closed_cleanly, summary=summary)
        subgraph = self.graph_store.observation_kg.get_task_subgraph(task_id)
        task_actions = self.graph_store.get_task_actions(task_id)
        belief_update = {
            "task_id": task_id,
            "beliefs_updated": 0,
            "new_beliefs_created": 0,
        }
        if subgraph and not submission_success:
            evidence_refs = []
            for action in subgraph.action_nodes.values():
                evidence_refs.append(action.action_id)
                evidence_refs.extend([ptr.location for ptr in action.evidence_index[:2]])
            belief_update = self.memory_agent.update_beliefs(
                task_id=task_id,
                outcome="success" if resolved_like_success else "fail",
                evidence_refs=list(dict.fromkeys(evidence_refs))[:100],
            )
            self.graph_store.save()
        elif submission_success:
            belief_update["skipped_reason"] = "submission_pending_official_eval"

        abstract_updates = {
            "generated": 0,
            "upserted": 0,
            "experience_ids": [],
        }
        rca_report: Dict[str, Any] = {}
        failure_card_info: Dict[str, Any] = {
            "generated": False,
            "card_id": None,
            "reason": None,
        }
        repair_pattern_ids: List[str] = []
        extraction_pipeline: Dict[str, Any] = {
            "enabled": bool(self.extraction_orchestrator.enabled),
            "triggered": False,
            "reason": "not_executed",
            "assessment_count": 0,
            "critical_signal": {},
            "abstract_added": 0,
            "repair_patterns_added": 0,
            "llm_used": False,
            "quality_gate": {},
        }
        attempt_summary_info: Dict[str, Any] = {
            "generated": False,
            "summary_id": None,
        }
        run_done_context = self._build_run_done_context(
            event_data=event_data,
            actions=task_actions,
            submission_success=submission_success,
            exit_status=exit_status,
        )
        if task_actions:
            abstractions = self.abstract_experience_builder.build_from_task(
                task_id=task_id,
                actions=task_actions,
                success=task_closed_cleanly,
                task_summary=summary,
                source_instance_id=str(event_data.get("instance_id") or ""),
                source_run_id=str(event_data.get("run_id") or event_data.get("batch_run_id") or ""),
                source_attempt_id=str(event_data.get("attempt_id") or ""),
            )
            abstractions = self._trim_submission_candidate_experiences(
                abstractions=abstractions,
                submission_success=submission_success,
            )
            abstract_updates["generated"] = len(abstractions)
            for exp in abstractions:
                exp_payload = exp.to_dict()
                exp_meta = exp_payload.get("metadata") if isinstance(exp_payload.get("metadata"), dict) else {}
                exp_meta.update(
                    {
                        "experience_polarity": "neutral" if submission_success else ("positive" if resolved_like_success else "neutral"),
                        "promotion_state": "candidate",
                        "evidence_stage": "submission" if submission_success else "trial_local",
                        "official_eval_status": "unknown",
                        "source_instance_id": str(event_data.get("instance_id") or ""),
                        "source_run_id": str(event_data.get("run_id") or event_data.get("batch_run_id") or ""),
                        "source_attempt_id": str(event_data.get("attempt_id") or ""),
                        "source_event_id": str(event_data.get("trace_id") or ""),
                    }
                )
                exp_payload["metadata"] = exp_meta
                exp_id = self.graph_store.upsert_abstract_experience(exp_payload)
                abstract_updates["upserted"] += 1
                abstract_updates["experience_ids"].append(exp_id)
            self.graph_store.save()

            if not task_closed_cleanly:
                rca_report = self.rca_agent.analyze_task_failure(task_id)
                failure_card = self.failure_card_builder.build_from_unresolved(
                    task_id=task_id,
                    actions=task_actions,
                    task_summary=summary,
                    rca_report=rca_report if isinstance(rca_report, dict) else None,
                )
                card_id = self.graph_store.upsert_failure_card_v2(failure_card.to_dict())
                failure_card_info = {
                    "generated": True,
                    "card_id": card_id,
                    "confidence": failure_card.confidence,
                    "has_rca": bool(failure_card.root_cause_nodes),
                }

                corrective_actions = rca_report.get("corrective_actions", []) if isinstance(rca_report, dict) else []
                if isinstance(corrective_actions, list):
                    for idx, action_text in enumerate(corrective_actions, start=1):
                        if not isinstance(action_text, str) or not action_text.strip():
                            continue
                        pattern_payload = {
                            "trigger_signature": {
                                "error_type": failure_card.error_signature.get("error_type", "unknown"),
                                "error_stage": failure_card.error_signature.get("error_stage", "execution"),
                                "error_module": failure_card.error_module,
                            },
                            "fix_action_template": action_text.strip()[:280],
                            "expected_verification": list(failure_card.verification_commands[:3]),
                            "evidence_refs": list(failure_card.evidence_refs[:10]),
                            "support": 1,
                            "confidence": max(0.2, min(0.95, float(failure_card.confidence))),
                            "trace_id": event_data.get("trace_id"),
                            "metadata": {
                                "source": "rca_corrective_action",
                                "task_id": task_id,
                                "card_id": card_id,
                                "index": idx,
                                **self._event_source_fields(event_data),
                            },
                        }
                        pattern_id = self.graph_store.upsert_repair_pattern_v2(pattern_payload)
                        repair_pattern_ids.append(pattern_id)
                if repair_pattern_ids:
                    card_row = dict(self.graph_store.failure_cards_v2.get(card_id, {}))
                    card_meta = dict(card_row.get("metadata", {}))
                    card_links = dict(card_meta.get("links", {}))
                    card_links["repair_pattern_ids"] = list(dict.fromkeys(repair_pattern_ids))
                    card_meta["links"] = card_links
                    card_row["metadata"] = card_meta
                    self.graph_store.failure_cards_v2[card_id] = card_row
                    failure_card_info["repair_pattern_ids"] = list(dict.fromkeys(repair_pattern_ids))
                self.graph_store.save()
            elif submission_success:
                failure_card_info["reason"] = "submission_pending_official_eval"
            else:
                failure_card_info["reason"] = "task_success"

            extraction_report = self.extraction_orchestrator.process_attempt(
                task_id=task_id,
                actions=task_actions,
                success=task_closed_cleanly,
                task_summary=summary,
                exit_status=exit_status,
                source_instance_id=str(event_data.get("instance_id") or ""),
                source_run_id=str(event_data.get("run_id") or event_data.get("batch_run_id") or ""),
                source_attempt_id=str(event_data.get("attempt_id") or ""),
                trace_id=event_data.get("trace_id"),
                extra_context=run_done_context,
            )
            extraction_pipeline.update(
                {
                    "enabled": bool(extraction_report.get("enabled", False)),
                    "triggered": bool(extraction_report.get("triggered", False)),
                    "reason": extraction_report.get("reason", ""),
                    "assessment_count": len(extraction_report.get("assessments", []) or []),
                    "critical_signal": extraction_report.get("critical_signal", {}) or {},
                    "llm_used": bool(extraction_report.get("llm_used", False)),
                    "quality_gate": extraction_report.get("quality_gate", {}) or {},
                }
            )
            attempt_summary_payload = extraction_report.get("attempt_summary_v1")
            if isinstance(attempt_summary_payload, dict) and attempt_summary_payload:
                summary_id = self.graph_store.upsert_attempt_summary_v1(attempt_summary_payload)
                attempt_summary_info = {
                    "generated": True,
                    "summary_id": summary_id,
                }
            if extraction_report.get("triggered"):
                extra_abstracts = extraction_report.get("abstract_experiences", []) or []
                for payload in extra_abstracts:
                    exp_id = self.graph_store.upsert_abstract_experience(payload)
                    abstract_updates["generated"] += 1
                    abstract_updates["upserted"] += 1
                    abstract_updates["experience_ids"].append(exp_id)
                extraction_pipeline["abstract_added"] = len(extra_abstracts)

                failure_patch = extraction_report.get("failure_card_patch", {}) or {}
                if failure_patch and not task_closed_cleanly:
                    card_id = failure_card_info.get("card_id")
                    if card_id:
                        self._apply_failure_card_patch(card_id=str(card_id), patch=failure_patch)
                        failure_card_info["patched_by_extractor"] = True
                    else:
                        patch_payload = {
                            "task_id": task_id,
                            "instance_id": event_data.get("instance_id"),
                            "run_id": event_data.get("run_id") or event_data.get("batch_run_id"),
                            "trace_id": event_data.get("trace_id"),
                            "source_event": "run_done",
                            "step_index": event_data.get("step_index"),
                            "error_signature": failure_patch.get("error_signature", {}),
                            "candidate_fix_actions": failure_patch.get("candidate_fix_actions", []),
                            "verification_commands": failure_patch.get("verification_commands", []),
                            "evidence_refs": failure_patch.get("evidence_refs", []),
                            "root_cause_nodes": failure_patch.get("root_cause_nodes", []),
                            "propagation_chain": failure_patch.get("propagation_chain", []),
                            "error_module": failure_patch.get("error_module", "unknown"),
                            "confidence": float(failure_patch.get("confidence", 0.2)),
                            "status": "unresolved",
                            "metadata": failure_patch.get("metadata", {}),
                        }
                        new_card_id = self.graph_store.upsert_failure_card_v2(patch_payload)
                        failure_card_info = {
                            "generated": True,
                            "card_id": new_card_id,
                            "confidence": patch_payload["confidence"],
                            "has_rca": False,
                            "reason": "created_from_extraction_patch",
                        }

                extra_patterns = extraction_report.get("repair_patterns", []) or []
                for payload in extra_patterns:
                    pattern_id = self.graph_store.upsert_repair_pattern_v2(payload)
                    repair_pattern_ids.append(pattern_id)
                extraction_pipeline["repair_patterns_added"] = len(extra_patterns)

                if failure_card_info.get("card_id"):
                    card_id = str(failure_card_info["card_id"])
                    card_row = dict(self.graph_store.failure_cards_v2.get(card_id, {}))
                    card_meta = dict(card_row.get("metadata", {}))
                    card_links = dict(card_meta.get("links", {}))
                    card_links["repair_pattern_ids"] = self._merge_unique_strings(
                        list(card_links.get("repair_pattern_ids", []) or []),
                        [str(pid) for pid in repair_pattern_ids],
                        limit=100,
                    )
                    card_meta["links"] = card_links
                    card_row["metadata"] = card_meta
                    self.graph_store.failure_cards_v2[card_id] = card_row
                    failure_card_info["repair_pattern_ids"] = list(card_links["repair_pattern_ids"])

                self.graph_store.save()
            if not attempt_summary_info.get("generated"):
                fallback_summary = self._build_fallback_attempt_summary(
                    task_id=task_id,
                    event_data=event_data,
                    actions=task_actions,
                    run_done_context=run_done_context,
                    final_outcome="submitted" if submission_success else ("resolved" if resolved_like_success else exit_status),
                )
                summary_id = self.graph_store.upsert_attempt_summary_v1(fallback_summary)
                attempt_summary_info = {
                    "generated": True,
                    "summary_id": summary_id,
                }
        elif not task_closed_cleanly:
            # Ensure unresolved run still yields a learnable failure asset.
            fallback_card = self.failure_card_builder.build_from_unresolved(
                task_id=task_id,
                actions=[],
                task_summary=summary,
                rca_report=None,
            )
            fallback_card.trace_id = event_data.get("trace_id")
            fallback_card.instance_id = event_data.get("instance_id")
            fallback_card.run_id = event_data.get("run_id") or event_data.get("batch_run_id")
            fallback_card.source_event = "run_done"
            fallback_card.step_index = event_data.get("step_index")
            fallback_card.metadata.update(self._event_source_fields(event_data))
            fallback_card_id = self.graph_store.upsert_failure_card_v2(fallback_card.to_dict())
            failure_card_info = {
                "generated": True,
                "card_id": fallback_card_id,
                "confidence": fallback_card.confidence,
                "has_rca": False,
                "reason": "fallback_from_no_task_actions",
            }
            self.graph_store.save()
            extraction_pipeline.update(
                {
                    "enabled": bool(self.extraction_orchestrator.enabled),
                    "triggered": False,
                    "reason": "fallback_from_no_task_actions",
                }
            )
        if not attempt_summary_info.get("generated"):
            fallback_summary = self._build_fallback_attempt_summary(
                task_id=task_id,
                event_data=event_data,
                actions=task_actions,
                run_done_context=run_done_context,
                final_outcome="submitted" if submission_success else ("resolved" if resolved_like_success else exit_status),
            )
            summary_id = self.graph_store.upsert_attempt_summary_v1(fallback_summary)
            attempt_summary_info = {
                "generated": True,
                "summary_id": summary_id,
            }

        write_ids = list(dict.fromkeys(abstract_updates.get("experience_ids", [])))
        if attempt_summary_info.get("summary_id"):
            write_ids.append(str(attempt_summary_info["summary_id"]))
        if failure_card_info.get("card_id"):
            write_ids.append(str(failure_card_info["card_id"]))
        write_ids.extend([str(pid) for pid in repair_pattern_ids])
        write_ids = list(dict.fromkeys(write_ids))
        self._append_rw_map(
            event_name="run_done",
            task_id=task_id,
            event_data=event_data,
            read_ids=[],
            write_ids=write_ids,
            extra={
                "task_closed_cleanly": task_closed_cleanly,
                "submission_success": submission_success,
                "resolved_like_success": resolved_like_success,
                "synthesized_task": synthesized_task,
                "belief_update": belief_update,
                "extraction_pipeline": {
                    "triggered": extraction_pipeline.get("triggered", False),
                    "reason": extraction_pipeline.get("reason", ""),
                    "assessment_count": extraction_pipeline.get("assessment_count", 0),
                    "abstract_added": extraction_pipeline.get("abstract_added", 0),
                    "repair_patterns_added": extraction_pipeline.get("repair_patterns_added", 0),
                },
            },
        )

        return {
            "version": "v1",
            "event_handled": "run_done",
            "task_id": task_id,
            "trace_id": event_data.get("trace_id"),
            "cleared": True,
            "synthesized_task": synthesized_task,
            "task_summary": task_summary,
            "belief_update": belief_update,
            "submission_success": submission_success,
            "resolved_like_success": resolved_like_success,
            "abstract_experience_updates": abstract_updates,
            "rca_report": rca_report if not task_closed_cleanly else {},
            "failure_card_v2": failure_card_info,
            "attempt_summary_v1": attempt_summary_info,
            "extraction_pipeline": extraction_pipeline,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def apply_evaluation_feedback(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        instance_id = str(event_data.get("instance_id") or "").strip()
        if not instance_id:
            return {
                "version": "v1",
                "event_handled": "official_eval_feedback",
                "error": "missing_instance_id",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        patch_text = str(event_data.get("patch_text") or "")
        patch_path = str(event_data.get("patch_path") or "").strip()
        if not patch_text and patch_path:
            try:
                patch_text = Path(patch_path).read_text(encoding="utf-8")
            except Exception:
                patch_text = ""

        report = self.evaluation_feedback.apply_feedback(
            instance_id=instance_id,
            outcome=str(event_data.get("official_eval_status") or event_data.get("outcome") or "unresolved"),
            eval_ref=str(event_data.get("eval_ref") or event_data.get("report_path") or ""),
            patch_text=patch_text,
            patch_summary=event_data.get("patch_summary") if isinstance(event_data.get("patch_summary"), dict) else None,
            changed_files=event_data.get("changed_files") if isinstance(event_data.get("changed_files"), list) else None,
            validation_summary=(
                event_data.get("validation_summary")
                if isinstance(event_data.get("validation_summary"), dict)
                else None
            ),
            task_summary=str(event_data.get("task_summary") or "")[:300],
            run_id=str(event_data.get("run_id") or event_data.get("batch_run_id") or ""),
            attempt_id=str(event_data.get("attempt_id") or ""),
            trace_id=str(event_data.get("trace_id") or ""),
        )
        summary_id = self.graph_store.update_attempt_summary_outcome(
            instance_id=instance_id,
            run_id=str(event_data.get("run_id") or event_data.get("batch_run_id") or ""),
            attempt_id=str(event_data.get("attempt_id") or ""),
            outcome=str(report.get("outcome") or ""),
            eval_ref=str(event_data.get("eval_ref") or event_data.get("report_path") or ""),
        )
        if summary_id:
            report["attempt_summary_id"] = summary_id
        self.graph_store.save()
        self._append_rw_map(
            event_name="official_eval_feedback",
            task_id=None,
            event_data=event_data,
            read_ids=list(report.get("related_candidate_ids", [])),
            write_ids=list(report.get("written_ids", []))
            + list(report.get("promoted_ids", []))
            + list(report.get("suppressed_ids", []))
            + ([str(summary_id)] if summary_id else [])
            + ([str(report["failure_card_id"])] if report.get("failure_card_id") else []),
            extra={
                "official_eval_status": report.get("outcome"),
                "related_candidate_count": report.get("related_candidate_count", 0),
            },
        )
        return {
            "version": "v1",
            "event_handled": "official_eval_feedback",
            "instance_id": instance_id,
            "feedback_report": report,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def handle_action_success(self,
                             action: str,
                             thought: str,
                             agent_name: str,
                             output: Optional[str] = None) -> Dict[str, Any]:
        """
        Handle successful action execution.

        Args:
            action: The action that was executed
            thought: The thought behind the action
            agent_name: Name of the agent
            output: Output from the action (if any)

        Returns:
            Response with logging confirmation
        """
        if not self.current_task_id:
            self.current_task_id = f"task_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{agent_name}"
            self.action_logger.start_task(self.current_task_id, {
                "agent": agent_name,
                "event": "action_success",
                "started_at": datetime.now(timezone.utc).isoformat()
            })

        # Log the successful action
        problem_file = self.action_logger.log_action(
            action_type=ActionType.TOOL_CALL,
            intent_text=thought,
            action_text=action,
            action_family="action_success",
            instance_id=agent_name,
            run_id=None,
            agent_name=agent_name,
            source_event="action_success",
            trace_id=None,
            inputs={"action": action},
            tool_calls=[{"type": "action_execution", "content": action}],
            stdout=output,
            outcome=Outcome.SUCCESS,
            metadata={
                "event": "action_success",
                "agent": agent_name,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        # Generate embeddings (optional in low-latency online mode)
        self._maybe_generate_embeddings(problem_file)

        self.graph_store.save()
        return {
            "version": "v1",
            "event_handled": "action_success",
            "task_id": self.current_task_id,
            "action_id": problem_file.action_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def end_task(self, success: bool, summary: Optional[str] = None) -> Dict[str, Any]:
        """
        End the current task.

        Args:
            success: Whether the task was successful
            summary: Task summary

        Returns:
            Task completion report
        """
        if not self.current_task_id:
            return {"error": "No active task"}

        # Get task summary from action logger
        task_summary = self.action_logger.end_task(success, summary)

        # Save graph store
        self.graph_store.save()

        # Generate task statistics
        stats = self.graph_store.get_statistics()

        response = {
            "version": "v1",
            "event_handled": "task_completed",
            "task_id": self.current_task_id,
            "success": success,
            "task_summary": task_summary,
            "statistics": stats,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Reset state
        self.current_task_id = None
        self.task_context = {}

        return response

    def _trim_submission_candidate_experiences(self, *, abstractions: List[Any], submission_success: bool) -> List[Any]:
        if not submission_success or not abstractions:
            return abstractions
        rows = list(abstractions)
        prioritized = []
        fallback = []
        for exp in rows:
            pattern_type = str(getattr(exp, "pattern_type", "")).strip().lower()
            if pattern_type and "planning" not in pattern_type and "workflow" not in pattern_type:
                prioritized.append(exp)
            else:
                fallback.append(exp)
        trimmed = prioritized[:1] if prioritized else []
        if not trimmed and fallback:
            trimmed = fallback[:1]
        return trimmed

    def get_task_statistics(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics for a task or all tasks.

        Args:
            task_id: Specific task ID, or None for all tasks

        Returns:
            Statistics
        """
        stats = self.graph_store.get_statistics()

        if task_id:
            # Filter for specific task
            subgraph = self.graph_store.observation_kg.get_task_subgraph(task_id)
            if subgraph:
                task_stats = {
                    "task_id": task_id,
                    "total_actions": len(subgraph.action_nodes),
                    "total_edges": len(subgraph.edges),
                    "success_chain": subgraph.get_success_chain(),
                    "failure_retry_chains": subgraph.get_failure_retry_chains(),
                }
                stats["task_details"] = task_stats
            else:
                stats["task_details"] = {"error": f"Task {task_id} not found"}

        return stats

    def search_experience(self,
                         query: str,
                         max_results: int = 5,
                         embedding_view: str = "emb_task_sem") -> Dict[str, Any]:
        """
        Search for relevant experience.

        Args:
            query: Search query
            max_results: Maximum number of results
            embedding_view: Which embedding view to use

        Returns:
            Search results
        """
        if not query.strip():
            return {
                "query": query,
                "embedding_view": embedding_view,
                "results": [],
                "recommendations": [],
                "belief_hints": [],
                "total_found": 0,
                "embedding_provider": self._embedding_provider(),
                "assumptions": ["empty query"],
                "failure_mode_if_wrong": "No useful retrieval when query is empty.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Build a transient query action and generate embeddings through the same writer.
        query_pf = ProblemFile(
            task_id="__query__",
            action_type=ActionType.TOOL_CALL,
            intent_text=query,
            inputs={"query": query},
            tool_calls=[],
            outcome=Outcome.UNKNOWN,
            metadata={"source": "search_experience"},
        )
        self._maybe_generate_embeddings(query_pf)
        similar_actions = self.graph_store.find_similar_actions(
            query_pf,
            max_results=max(1, max_results * 2),
            embedding_view=embedding_view,
        )

        results = []
        for action_id, action, score in similar_actions[:max_results]:
            evidence_refs = [ptr.location for ptr in action.evidence_index[:3] if ptr.location]
            task_info = self.graph_store.observation_kg.get_action(action_id)
            task_id = task_info[1] if task_info else "unknown"
            results.append(
                {
                    "task_id": task_id,
                    "action_id": action_id,
                    "similarity": round(float(score), 4),
                    "action_type": action.action_type.value,
                    "outcome": action.outcome.value,
                    "intent_text": action.intent_text[:200],
                    "failure_signature": (
                        action.failure_signature.error_type
                        if action.failure_signature
                        else None
                    ),
                    "evidence_refs": evidence_refs,
                }
            )

        planning = self.memory_agent.retrieve_for_planning(
            task_context={"instruction": query, "summary": query},
            current_action=query,
            agent_name="search_experience",
            current_problem_file=query_pf,
            embedding_view=embedding_view,
        )

        belief_hints = []
        for belief in self.graph_store.get_relevant_beliefs(max_results=max_results):
            belief_hints.append(
                {
                    "belief_id": belief.belief_id,
                    "belief_type": belief.belief_type.value,
                    "confidence": belief.confidence,
                    "recommend": belief.rule.recommend,
                    "avoid": belief.rule.avoid,
                    "evidence_refs": belief.evidence_refs[:3],
                }
            )

        abstract_patterns = self.graph_store.query_abstract_experiences(
            query_text=query,
            max_results=max_results,
        )

        return {
            "query": query,
            "embedding_view": embedding_view,
            "results": results,
            "recommendations": planning.get("recommendations", [])[:max_results],
            "retrieval_debug": planning.get("retrieval_debug", {}),
            "belief_hints": belief_hints,
            "abstract_patterns": abstract_patterns,
            "total_found": len(results),
            "embedding_provider": self._embedding_provider(),
            "assumptions": [
                "Similarity is computed on available embedding views and falls back to lexical overlap.",
                "Belief hints are ranked by current confidence.",
            ],
            "failure_mode_if_wrong": (
                "If retrieved examples are from mismatched environments, suggestions may be weak; "
                "use evidence_refs for manual verification."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def export_data(self, output_dir: str) -> Dict[str, Any]:
        """
        Export all data for analysis or backup.

        Args:
            output_dir: Output directory

        Returns:
            Export report
        """
        import shutil
        from pathlib import Path

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save current state
        self.graph_store.save()

        # Copy evidence directory if it exists
        evidence_src = Path(self.action_logger.evidence_collector.evidence_dir)
        if evidence_src.exists():
            evidence_dst = output_path / "evidence"
            if evidence_dst.exists():
                shutil.rmtree(evidence_dst)
            shutil.copytree(evidence_src, evidence_dst)

        # Export embeddings for analysis
        embeddings_file = output_path / "embeddings_export.json"
        export_stats = self.kg_writer.export_embeddings_for_analysis(
            str(embeddings_file),
            "emb_task_sem"
        )

        return {
            "export_dir": str(output_path),
            "embeddings_export": export_stats,
            "total_tasks": len(self.graph_store.observation_kg.task_subgraphs),
            "total_actions": sum(len(sg.action_nodes) for sg in self.graph_store.observation_kg.task_subgraphs.values()),
            "total_beliefs": len(self.graph_store.belief_graph.atomic_beliefs),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
