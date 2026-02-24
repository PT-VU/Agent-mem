"""
SWEAgentAdapter: Adapter for integrating Agent-mem with SWE-agent.

This adapter connects the existing sweagent_ext_tools framework with the new
Agent-mem system, replacing the simple Tool A/Tool B with full memory capabilities.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from pathlib import Path

from ..core.problem_file import ProblemFile, ActionType, Outcome
from ..processing.action_logger import ActionLogger
from ..processing.kg_writer import KGWriter, EmbeddingGenerator
from ..storage.graph_store import GraphStore
from ..retrieval.memory_agent import MemoryAgent


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
                 embedding_model: str = "random",
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

        # State tracking
        self.current_task_id: Optional[str] = None
        self.task_context: Dict[str, Any] = {}
        self._state_file: Optional[Path] = None
        if storage_dir:
            storage_path = Path(storage_dir)
            storage_path.mkdir(parents=True, exist_ok=True)
            self._state_file = storage_path / "active_tasks.json"

    def _sanitize_key(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
        return cleaned[:120] or "unknown"

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
        if run_id:
            return f"{self._sanitize_key(str(run_id))}:{self._sanitize_key(str(instance_id))}"
        return self._sanitize_key(str(instance_id))

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

        task_id = self._ensure_task_context(event_data, "plan_generated")

        # Log the planning action
        problem_file = self.action_logger.log_action(
            action_type=ActionType.TOOL_CALL,
            intent_text="Generate plan for task",
            inputs={"thought": thought, "action": action},
            tool_calls=[{"type": "plan_generation", "content": action}],
            outcome=Outcome.SUCCESS,
            metadata={
                "event": "plan_generated",
                "agent": agent_name,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        # Generate embeddings
        self.kg_writer.write_action_with_embeddings(problem_file)

        # Retrieve relevant experience for planning
        planning_tips = self.memory_agent.retrieve_for_planning(
            task_context=self.task_context,
            current_action=action,
            agent_name=agent_name
        )

        # Prepare response
        response = {
            "version": "v1",
            "event_handled": "plan_generated",
            "task_id": task_id,
            "action_id": problem_file.action_id,
            "planning_tips": planning_tips.get("recommendations", []),
            "evidence_refs": planning_tips.get("evidence_refs", []),
            "confidence": planning_tips.get("confidence", 0.0),
            "embedding_provider": self.kg_writer.embedding_generator.provider,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

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

        task_id = self._ensure_task_context(event_data, "action_error")

        # Log the failed action
        problem_file = self.action_logger.log_action(
            action_type=ActionType.TOOL_CALL,
            intent_text=thought,
            inputs={"action": action, "error_type": error_type},
            tool_calls=[{"type": "action_execution", "content": action}],
            stderr=error_message,
            outcome=Outcome.FAIL,
            metadata={
                "event": "action_error",
                "agent": agent_name,
                "error_type": error_type,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        # Generate embeddings
        self.kg_writer.write_action_with_embeddings(problem_file)

        # Retrieve repair suggestions
        repair_suggestions = self.memory_agent.retrieve_for_repair(
            error_type=error_type,
            error_message=error_message,
            current_action=action,
            problem_file=problem_file
        )

        # Prepare response
        response = {
            "version": "v1",
            "event_handled": "action_error",
            "task_id": task_id,
            "action_id": problem_file.action_id,
            "repair_suggestions": repair_suggestions.get("recommendations", []),
            "evidence_refs": repair_suggestions.get("evidence_refs", []),
            "confidence": repair_suggestions.get("confidence", 0.0),
            "next_step_fix": repair_suggestions.get("next_step_fix", ""),
            "expected_outcome": repair_suggestions.get("expected_outcome", ""),
            "embedding_provider": self.kg_writer.embedding_generator.provider,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self.graph_store.save()
        return response

    def handle_run_done(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle run completion and clear active task mapping."""
        active_tasks = self._load_active_tasks()
        task_key = self._build_task_key(event_data)
        task_id = active_tasks.pop(task_key, None)
        self._save_active_tasks(active_tasks)
        self.graph_store.save()

        if not task_id:
            return {
                "version": "v1",
                "event_handled": "run_done",
                "task_id": None,
                "cleared": False,
                "reason": "no_active_task",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        exit_status = str(event_data.get("exit_status", "unknown"))
        has_submission = bool(event_data.get("has_submission", False))
        success = has_submission or exit_status in {"submitted", "done", "success"}
        self.action_logger.start_task(
            task_id,
            {
                "agent": event_data.get("agent", "unknown"),
                "event": "run_done",
                "task_key": task_key,
            },
            resume_from_existing=True,
        )
        summary = f"run_done exit_status={exit_status} has_submission={has_submission}"
        task_summary = self.action_logger.end_task(success, summary=summary)
        subgraph = self.graph_store.observation_kg.get_task_subgraph(task_id)
        belief_update = {
            "task_id": task_id,
            "beliefs_updated": 0,
            "new_beliefs_created": 0,
        }
        if subgraph:
            evidence_refs = []
            for action in subgraph.action_nodes.values():
                evidence_refs.append(action.action_id)
                evidence_refs.extend([ptr.location for ptr in action.evidence_index[:2]])
            belief_update = self.memory_agent.update_beliefs(
                task_id=task_id,
                outcome="success" if success else "fail",
                evidence_refs=list(dict.fromkeys(evidence_refs))[:100],
            )
            self.graph_store.save()

        return {
            "version": "v1",
            "event_handled": "run_done",
            "task_id": task_id,
            "cleared": True,
            "task_summary": task_summary,
            "belief_update": belief_update,
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

        # Generate embeddings
        self.kg_writer.write_action_with_embeddings(problem_file)

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
                "embedding_provider": self.kg_writer.embedding_generator.provider,
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
        self.kg_writer.write_action_with_embeddings(query_pf)
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

        return {
            "query": query,
            "embedding_view": embedding_view,
            "results": results,
            "recommendations": planning.get("recommendations", [])[:max_results],
            "belief_hints": belief_hints,
            "total_found": len(results),
            "embedding_provider": self.kg_writer.embedding_generator.provider,
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
