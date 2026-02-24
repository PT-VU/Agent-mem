"""
Memory Agent: A service that provides query rewriting, subgraph selection,
experience distillation, evidence referencing, and belief updates.

参考架构文档6.1节：Memory Agent的职责（必须可测）
1) Query Rewriting: 将自然语言任务描述改写成结构化可检索 query
2) Subgraph Selection: 从 KG 中选择最有用的经验子图（而非简单 top-k 节点）
3) Experience Distillation: 压缩为可执行建议/流程tips/约束候选
4) Evidence Referencing: 返回证据坐标，支持回放与追责
5) Belief Update: 异步更新信念统计与状态（promote/deprecate）
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
import uuid

from ..core.problem_file import ProblemFile
from ..core.belief_graph import (
    AtomicBelief,
    AttemptBelief,
    BeliefType,
    ConditionSignature,
    BeliefRule,
)
from ..core.observation_kg import EdgeType
from ..storage.graph_store import GraphStore


class QueryRewriter:
    """Rewrites natural language queries into structured retrieval queries."""

    def rewrite_for_planning(self,
                            user_instruction: str,
                            context_summary: str,
                            env_signature: Dict[str, Any]) -> Dict[str, Any]:
        """Rewrite query for planning-time retrieval."""
        # TODO: Use LLM or rule-based rewriting
        # For MVP, return structured query based on simple extraction
        return {
            "query_type": "planning",
            "task_semantic": user_instruction,
            "context": context_summary,
            "env_cluster": env_signature.get("env_cluster"),
            "file_scope": self._extract_file_scope(user_instruction),
            "intent_patterns": self._extract_intent_patterns(user_instruction),
        }

    def rewrite_for_repair(self,
                          error_type: str,
                          error_message: str,
                          current_action: str,
                          env_signature: Dict[str, Any]) -> Dict[str, Any]:
        """Rewrite query for execution-time repair retrieval."""
        return {
            "query_type": "repair",
            "error_type": error_type,
            "error_signature": self._extract_error_signature(error_message),
            "current_action": current_action,
            "env_cluster": env_signature.get("env_cluster"),
            "action_type": self._infer_action_type(current_action),
        }

    def _extract_file_scope(self, text: str) -> List[str]:
        """Extract file scope patterns from text."""
        # Simplified extraction - look for file extensions
        import re
        patterns = [
            r'(\S+\.py)', r'(\S+\.js)', r'(\S+\.ts)', r'(\S+\.java)',
            r'(\S+\.cpp)', r'(\S+\.h)', r'(\S+\.md)', r'(\S+\.txt)'
        ]
        files = []
        for pattern in patterns:
            files.extend(re.findall(pattern, text))
        return files[:5]  # Limit to 5 files

    def _extract_intent_patterns(self, text: str) -> List[str]:
        """Extract intent patterns from text."""
        # Common intent keywords
        intents = []
        keywords = [
            "fix", "repair", "debug", "implement", "add", "remove",
            "update", "modify", "test", "run", "check", "verify"
        ]
        text_lower = text.lower()
        for keyword in keywords:
            if keyword in text_lower:
                intents.append(keyword)
        return intents

    def _extract_error_signature(self, error_message: str) -> Dict[str, Any]:
        """Extract error signature from error message."""
        # Simplified error signature extraction
        lines = error_message.strip().split('\n')
        first_line = lines[0] if lines else ""

        return {
            "first_line": first_line[:100],  # First 100 chars
            "contains_error": "error" in first_line.lower(),
            "contains_exception": "exception" in first_line.lower(),
            "contains_fail": "fail" in first_line.lower(),
            "line_count": len(lines),
        }

    def _infer_action_type(self, action: str) -> Optional[str]:
        """Infer action type from action string."""
        action_lower = action.lower()
        if "test" in action_lower:
            return "run_test"
        elif "edit" in action_lower or "modify" in action_lower:
            return "code_edit"
        elif "run" in action_lower or "execute" in action_lower:
            return "command_exec"
        elif "search" in action_lower or "find" in action_lower:
            return "tool_call"
        else:
            return None


class SubgraphSelector:
    """Selects useful experience subgraphs from KG (not just top-k nodes)."""

    def __init__(self, graph_store: GraphStore):
        self.graph_store = graph_store

    def select_for_planning(self,
                           query: Dict[str, Any],
                           max_subgraphs: int = 3) -> List[Dict[str, Any]]:
        """Select subgraphs for planning-time experience injection."""
        selected = []

        # For each task subgraph, compute relevance score
        for task_id, subgraph in self.graph_store.observation_kg.task_subgraphs.items():
            relevance = self._compute_planning_relevance(subgraph, query)
            if relevance > 0:
                selected.append({
                    "task_id": task_id,
                    "subgraph": subgraph,
                    "relevance": relevance,
                    "success_chain": subgraph.get_success_chain(),
                    "total_actions": len(subgraph.action_nodes),
                })

        # Sort by relevance and limit
        selected.sort(key=lambda x: x["relevance"], reverse=True)
        return selected[:max_subgraphs]

    def select_for_repair(self,
                         query: Dict[str, Any],
                         max_subgraphs: int = 5) -> List[Dict[str, Any]]:
        """Select subgraphs for execution-time repair."""
        selected = []

        for task_id, subgraph in self.graph_store.observation_kg.task_subgraphs.items():
            relevance = self._compute_repair_relevance(subgraph, query)
            if relevance > 0:
                # Extract failure-retry chains
                failure_chains = subgraph.get_failure_retry_chains()

                selected.append({
                    "task_id": task_id,
                    "subgraph": subgraph,
                    "relevance": relevance,
                    "failure_chains": failure_chains,
                    "total_actions": len(subgraph.action_nodes),
                })

        selected.sort(key=lambda x: x["relevance"], reverse=True)
        return selected[:max_subgraphs]

    def _compute_planning_relevance(self,
                                   subgraph: Any,  # TaskSubgraph
                                   query: Dict[str, Any]) -> float:
        """Compute relevance score for planning."""
        score = 0.0

        # Check if subgraph has successful completion
        success_chain = subgraph.get_success_chain()
        if not success_chain:
            return 0.0

        # Basic score for having a success chain
        score += 0.3

        # Check file scope match
        query_files = query.get("file_scope", [])
        if query_files:
            # Check if any action in subgraph touches similar files
            file_match = False
            for action in subgraph.action_nodes.values():
                for touched_file in action.touched_files:
                    for query_file in query_files:
                        if query_file in touched_file or touched_file in query_file:
                            file_match = True
                            break
                if file_match:
                    break
            if file_match:
                score += 0.3

        # Check intent pattern match
        query_intents = query.get("intent_patterns", [])
        if query_intents:
            intent_match = False
            for action in subgraph.action_nodes.values():
                intent_lower = action.intent_text.lower()
                for intent in query_intents:
                    if intent in intent_lower:
                        intent_match = True
                        break
                if intent_match:
                    break
            if intent_match:
                score += 0.2

        # Normalize to 0-1 range
        return min(score, 1.0)

    def _compute_repair_relevance(self,
                                 subgraph: Any,  # TaskSubgraph
                                 query: Dict[str, Any]) -> float:
        """Compute relevance score for repair."""
        score = 0.0

        # Check if subgraph has failure-retry chains
        failure_chains = subgraph.get_failure_retry_chains()
        if not failure_chains:
            return 0.0

        # Basic score for having failure chains
        score += 0.2

        # Check error type match
        query_error_type = query.get("error_type", "")
        if query_error_type:
            # Look for similar error types in failure actions
            error_match = False
            for action in subgraph.action_nodes.values():
                if action.failure_signature:
                    if (query_error_type.lower() in action.failure_signature.error_type.lower() or
                        action.failure_signature.error_type.lower() in query_error_type.lower()):
                        error_match = True
                        break
            if error_match:
                score += 0.3

        # Check action type match
        query_action_type = query.get("action_type")
        if query_action_type:
            action_match = False
            for action in subgraph.action_nodes.values():
                if action.action_type.value == query_action_type:
                    action_match = True
                    break
            if action_match:
                score += 0.3

        # Normalize to 0-1 range
        return min(score, 1.0)


class ExperienceDistiller:
    """Distills experience into executable suggestions/flow tips/constraint candidates."""

    def distill_planning_experience(self,
                                   selected_subgraphs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Distill planning experience from selected subgraphs."""
        recommendations = []
        evidence_refs = []

        for subgraph_info in selected_subgraphs:
            subgraph = subgraph_info["subgraph"]
            task_id = subgraph_info["task_id"]

            # Extract success chain as workflow template
            success_chain = subgraph.get_success_chain()
            if success_chain:
                workflow_tips = self._extract_workflow_tips(subgraph, success_chain)
                recommendations.extend(workflow_tips)

                # Add evidence references
                for action_id in success_chain[:3]:  # First 3 actions
                    evidence_refs.append({
                        "task_id": task_id,
                        "action_id": action_id,
                        "type": "success_chain",
                    })

            # Extract preventive checks from beliefs
            # TODO: Integrate with belief graph

        # Deduplicate and rank recommendations
        unique_recommendations = self._deduplicate_recommendations(recommendations)

        return {
            "recommendations": unique_recommendations[:5],  # Top 5
            "evidence_refs": evidence_refs[:10],  # Limit evidence
            "confidence": self._compute_confidence(selected_subgraphs),
            "total_subgraphs": len(selected_subgraphs),
        }

    def distill_repair_experience(self,
                                 selected_subgraphs: List[Dict[str, Any]],
                                 current_problem: ProblemFile) -> Dict[str, Any]:
        """Distill repair experience from selected subgraphs."""
        repair_suggestions = []
        evidence_refs = []

        for subgraph_info in selected_subgraphs:
            subgraph = subgraph_info["subgraph"]
            task_id = subgraph_info["task_id"]
            failure_chains = subgraph_info.get("failure_chains", {})

            for fail_action_id, retry_chain in failure_chains.items():
                if len(retry_chain) >= 2:  # At least failure and repair
                    # Extract repair pattern
                    repair_pattern = self._extract_repair_pattern(
                        subgraph, fail_action_id, retry_chain
                    )
                    if repair_pattern:
                        repair_suggestions.append(repair_pattern)

                        # Add evidence references
                        evidence_refs.append({
                            "task_id": task_id,
                            "fail_action_id": fail_action_id,
                            "repair_action_id": retry_chain[1] if len(retry_chain) > 1 else None,
                            "type": "failure_repair",
                        })

        # Find most relevant repair suggestion
        next_step_fix = ""
        if repair_suggestions:
            # For MVP, use the first suggestion
            first_suggestion = repair_suggestions[0]
            next_step_fix = first_suggestion.get("repair_action", "")

        return {
            "recommendations": repair_suggestions[:3],  # Top 3
            "evidence_refs": evidence_refs[:5],  # Limit evidence
            "confidence": self._compute_confidence(selected_subgraphs),
            "next_step_fix": next_step_fix,
            "expected_outcome": "Error should be resolved or reduced",
            "total_subgraphs": len(selected_subgraphs),
        }

    def _extract_workflow_tips(self, subgraph: Any, success_chain: List[str]) -> List[Dict[str, Any]]:
        """Extract workflow tips from success chain."""
        tips = []

        for i, action_id in enumerate(success_chain):
            action = subgraph.action_nodes.get(action_id)
            if not action:
                continue

            # Create tip for key actions
            if i == 0 or i == len(success_chain) - 1 or i % 3 == 0:  # Sample points
                tip = {
                    "type": "workflow_step",
                    "step_number": i + 1,
                    "intent": action.intent_text[:100],  # First 100 chars
                    "action_type": action.action_type.value,
                    "recommendation": f"Consider: {action.intent_text[:50]}...",
                }
                tips.append(tip)

        return tips

    def _extract_repair_pattern(self,
                               subgraph: Any,
                               fail_action_id: str,
                               retry_chain: List[str]) -> Optional[Dict[str, Any]]:
        """Extract repair pattern from failure-retry chain."""
        if len(retry_chain) < 2:
            return None

        fail_action = subgraph.action_nodes.get(fail_action_id)
        repair_action = subgraph.action_nodes.get(retry_chain[1])  # First repair attempt

        if not fail_action or not repair_action:
            return None

        return {
            "fail_action_type": fail_action.action_type.value,
            "fail_intent": fail_action.intent_text[:100],
            "repair_action_type": repair_action.action_type.value,
            "repair_intent": repair_action.intent_text[:100],
            "repair_action": self._suggest_repair_action(fail_action, repair_action),
            "pattern": "failure_followed_by_repair",
        }

    def _suggest_repair_action(self, fail_action: ProblemFile, repair_action: ProblemFile) -> str:
        """Generate repair action suggestion."""
        # Simplified suggestion generation
        if fail_action.action_type.value == repair_action.action_type.value:
            return f"Retry similar action with adjustments: {repair_action.intent_text[:50]}..."
        else:
            return f"Try different approach: {repair_action.intent_text[:50]}..."

    def _deduplicate_recommendations(self, recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate similar recommendations."""
        seen = set()
        unique = []

        for rec in recommendations:
            # Create signature for deduplication
            if "intent" in rec:
                sig = f"{rec.get('type', '')}:{rec.get('intent', '')[:50]}"
            elif "repair_action" in rec:
                sig = f"{rec.get('pattern', '')}:{rec.get('repair_action', '')[:50]}"
            else:
                sig = str(rec)

            if sig not in seen:
                seen.add(sig)
                unique.append(rec)

        return unique

    def _compute_confidence(self, selected_subgraphs: List[Dict[str, Any]]) -> float:
        """Compute confidence score based on selected subgraphs."""
        if not selected_subgraphs:
            return 0.0

        # Average relevance score
        total_relevance = sum(sg.get("relevance", 0.0) for sg in selected_subgraphs)
        avg_relevance = total_relevance / len(selected_subgraphs)

        # Boost for multiple supporting subgraphs
        support_boost = min(len(selected_subgraphs) / 5.0, 0.3)  # Max 0.3 boost for 5+ subgraphs

        return min(avg_relevance + support_boost, 1.0)


class MemoryAgent:
    """
    Memory Agent: Main service coordinating query rewriting, subgraph selection,
    experience distillation, and evidence referencing.
    """

    def __init__(self, graph_store: GraphStore):
        self.graph_store = graph_store
        self.query_rewriter = QueryRewriter()
        self.subgraph_selector = SubgraphSelector(graph_store)
        self.experience_distiller = ExperienceDistiller()

    # Backward-compatible wrappers used by legacy test scripts.
    def query_rewriting(self, query: str) -> Dict[str, Any]:
        return self.query_rewriter.rewrite_for_planning(
            user_instruction=query,
            context_summary="",
            env_signature={},
        )

    def experience_distillation(self, experiences: List[Dict[str, Any]]) -> Dict[str, Any]:
        recommendations = []
        for exp in experiences:
            recommendations.append(
                {
                    "type": "legacy_experience",
                    "recommendation": exp.get("solution") or exp.get("description", ""),
                    "source_task_id": exp.get("task_id", "unknown"),
                }
            )
        return {
            "recommendations": recommendations,
            "evidence_refs": [],
            "confidence": 0.5 if recommendations else 0.0,
        }

    def retrieve_for_planning(self,
                            task_context: Dict[str, Any],
                            current_action: str,
                            agent_name: str) -> Dict[str, Any]:
        """
        Retrieve experience for planning-time injection.

        范式 A: Planning-time 经验注入
        """
        # Rewrite query
        query = self.query_rewriter.rewrite_for_planning(
            user_instruction=task_context.get("instruction", ""),
            context_summary=task_context.get("summary", ""),
            env_signature=task_context.get("env_signature", {})
        )

        # Select relevant subgraphs
        selected_subgraphs = self.subgraph_selector.select_for_planning(query)

        # Distill experience
        result = self.experience_distiller.distill_planning_experience(selected_subgraphs)

        # Inject top active beliefs as structured hints.
        beliefs = self.graph_store.get_relevant_beliefs(max_results=3)
        if beliefs:
            belief_tips = []
            belief_refs = []
            for belief in beliefs:
                belief_tips.append(
                    {
                        "type": "belief_tip",
                        "belief_id": belief.belief_id,
                        "belief_type": belief.belief_type.value,
                        "recommendation": belief.rule.recommend or belief.rule.trigger,
                        "confidence": belief.confidence,
                    }
                )
                belief_refs.extend(belief.evidence_refs[:2])
            result["recommendations"] = belief_tips + result.get("recommendations", [])
            result["evidence_refs"] = belief_refs + result.get("evidence_refs", [])

        # Add query context
        result["query"] = query
        result["selected_subgraph_count"] = len(selected_subgraphs)
        result["agent"] = agent_name
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        return result

    def retrieve_for_repair(self,
                           error_type: str,
                           error_message: str,
                           current_action: str,
                           problem_file: ProblemFile) -> Dict[str, Any]:
        """
        Retrieve experience for execution-time repair.

        范式 B: Execution-time 出错回忆
        """
        # Create env signature from problem file
        env_signature = {}
        if problem_file.env_signature:
            env_signature = {
                "toolchain": problem_file.env_signature.toolchain_version,
                "path_hash": problem_file.env_signature.path_hash,
                "working_dir": problem_file.env_signature.working_dir,
            }

        # Rewrite query
        query = self.query_rewriter.rewrite_for_repair(
            error_type=error_type,
            error_message=error_message,
            current_action=current_action,
            env_signature=env_signature
        )

        # Select relevant subgraphs
        selected_subgraphs = self.subgraph_selector.select_for_repair(query)

        # Distill experience
        result = self.experience_distiller.distill_repair_experience(
            selected_subgraphs, problem_file
        )

        # Inject pitfall beliefs that match current error signature/action type.
        beliefs = self.graph_store.get_relevant_beliefs(
            action_type=query.get("action_type"),
            max_results=5,
        )
        if beliefs:
            filtered_beliefs = []
            for belief in beliefs:
                sig = (belief.condition_signature.error_signature or "").lower()
                if not sig or sig in error_type.lower() or sig in error_message.lower():
                    filtered_beliefs.append(belief)
            if filtered_beliefs:
                belief_suggestions = []
                belief_refs = []
                for belief in filtered_beliefs[:3]:
                    belief_suggestions.append(
                        {
                            "pattern": "belief_repair_hint",
                            "belief_id": belief.belief_id,
                            "repair_action": belief.rule.recommend or belief.rule.trigger,
                            "avoid_action": belief.rule.avoid,
                            "confidence": belief.confidence,
                        }
                    )
                    belief_refs.extend(belief.evidence_refs[:2])
                result["recommendations"] = belief_suggestions + result.get("recommendations", [])
                result["evidence_refs"] = belief_refs + result.get("evidence_refs", [])

        # Add query context
        result["query"] = query
        result["selected_subgraph_count"] = len(selected_subgraphs)
        result["error_type"] = error_type
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        return result

    def update_beliefs(self,
                      task_id: str,
                      outcome: str,
                      evidence_refs: List[str]) -> Dict[str, Any]:
        """
        Update beliefs based on task outcome.

        Args:
            task_id: Task ID
            outcome: "success" or "fail"
            evidence_refs: Evidence references from the task

        Returns:
            Update report
        """
        subgraph = self.graph_store.observation_kg.get_task_subgraph(task_id)
        if not subgraph:
            return {
                "task_id": task_id,
                "outcome": outcome,
                "beliefs_updated": 0,
                "new_beliefs_created": 0,
                "error": "task_not_found",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        actions = self.graph_store.get_task_actions(task_id)
        if not actions:
            return {
                "task_id": task_id,
                "outcome": outcome,
                "beliefs_updated": 0,
                "new_beliefs_created": 0,
                "error": "task_has_no_actions",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        success = str(outcome).lower() == "success"
        success_count = sum(1 for a in actions if a.outcome.value == "success")
        fail_count = sum(1 for a in actions if a.outcome.value == "fail")
        attempt_evidence = list(dict.fromkeys(evidence_refs + [a.action_id for a in actions[:3]]))
        attempt_belief = AttemptBelief(
            task_id=task_id,
            summary=f"Task {task_id}: total={len(actions)}, success={success_count}, fail={fail_count}",
            failure_causal_chain=[a.action_id for a in actions if a.outcome.value == "fail"][:5],
            key_turning_points=[actions[0].action_id, actions[-1].action_id] if len(actions) > 1 else [actions[0].action_id],
            reusable_workflow_points=[a.intent_text[:120] for a in actions if a.outcome.value == "success"][:3],
            evidence_refs=attempt_evidence[:20],
            metadata={"source": "memory_agent.update_beliefs"},
        )
        self.graph_store.add_attempt_belief(attempt_belief)

        last_action = actions[-1]
        failed_actions = [a for a in actions if a.outcome.value == "fail"]
        latest_fail = failed_actions[-1] if failed_actions else None

        env_cluster = None
        repo_toolchain = None
        if last_action.env_signature:
            env_cluster = last_action.env_signature.path_hash
            repo_toolchain = last_action.env_signature.toolchain_version

        belief_type = BeliefType.WORKFLOW if success else BeliefType.PITFALL
        error_signature = None
        if latest_fail and latest_fail.failure_signature:
            error_signature = latest_fail.failure_signature.error_type

        recommend = None
        avoid = None
        if success:
            success_chain = subgraph.get_success_chain()
            if success_chain:
                chain_intents = [
                    subgraph.action_nodes[action_id].intent_text
                    for action_id in success_chain
                    if action_id in subgraph.action_nodes
                ]
                recommend = " -> ".join([i[:60] for i in chain_intents[:3]]) or last_action.intent_text[:120]
            else:
                recommend = last_action.intent_text[:120]
        else:
            avoid = latest_fail.intent_text[:120] if latest_fail else last_action.intent_text[:120]
            retry_chains = subgraph.get_failure_retry_chains()
            if latest_fail and latest_fail.action_id in retry_chains:
                chain = retry_chains[latest_fail.action_id]
                if len(chain) > 1 and chain[1] in subgraph.action_nodes:
                    recommend = subgraph.action_nodes[chain[1]].intent_text[:120]
            if not recommend:
                recommend = f"Repair after {error_signature or 'failure'} by narrowing context and re-validating"

        condition = ConditionSignature(
            env_cluster=env_cluster,
            repo_toolchain=repo_toolchain,
            action_type_pattern=last_action.action_type.value,
            intent_pattern=last_action.intent_text[:80],
            error_signature=error_signature,
        )
        rule = BeliefRule(
            trigger=f"When action_type={last_action.action_type.value}",
            recommend=recommend,
            avoid=avoid,
        )

        def _same_signature(belief: AtomicBelief) -> bool:
            cs = belief.condition_signature
            return (
                belief.belief_type == belief_type
                and cs.action_type_pattern == condition.action_type_pattern
                and cs.error_signature == condition.error_signature
                and cs.env_cluster == condition.env_cluster
            )

        existing = None
        for belief in self.graph_store.belief_graph.atomic_beliefs.values():
            if _same_signature(belief):
                existing = belief
                break

        new_created = 0
        updated = 0
        belief_ids = []
        belief_evidence = list(dict.fromkeys(evidence_refs + [a.action_id for a in actions[-5:]]))

        if existing:
            # Keep most recent actionable wording.
            existing.rule = rule
            existing.evidence_refs = list(dict.fromkeys(existing.evidence_refs + belief_evidence))[:50]
            self.graph_store.update_belief_stats(
                existing.belief_id,
                success_with=success,
                success_without=not success,
            )
            belief_ids.append(existing.belief_id)
            updated += 1
        else:
            new_belief = AtomicBelief(
                belief_type=belief_type,
                condition_signature=condition,
                rule=rule,
                confidence=0.0,
                evidence_refs=belief_evidence[:50],
                metadata={"source": "memory_agent.update_beliefs", "task_id": task_id},
            )
            belief_id = self.graph_store.add_atomic_belief(new_belief)
            self.graph_store.update_belief_stats(
                belief_id,
                success_with=success,
                success_without=not success,
            )
            belief_ids.append(belief_id)
            new_created += 1

        return {
            "task_id": task_id,
            "outcome": outcome,
            "attempt_belief_id": attempt_belief.attempt_id,
            "belief_ids": belief_ids,
            "beliefs_updated": updated,
            "new_beliefs_created": new_created,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_memory_statistics(self) -> Dict[str, Any]:
        """Get memory statistics."""
        kg_stats = self.graph_store.observation_kg.get_statistics()
        belief_stats = self.graph_store.belief_graph.get_statistics()

        return {
            "observation_kg": kg_stats,
            "belief_graph": belief_stats,
            "total_experience_units": kg_stats.get("total_actions", 0),
            "total_beliefs": belief_stats.get("total_atomic_beliefs", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
