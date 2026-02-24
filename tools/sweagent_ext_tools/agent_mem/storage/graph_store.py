"""
Graph Store: Storage implementation for observation KG and belief graph.

MVP使用networkx作为内存存储，后续可扩展为neo4j或其他图数据库。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
import networkx as nx

from ..core.observation_kg import ObservationKG, TaskSubgraph, KGEdge, EdgeType
from ..core.belief_graph import BeliefGraph, AtomicBelief, AttemptBelief
from ..core.problem_file import ProblemFile


class GraphStore:
    """
    Unified graph store for both observation KG and belief graph.

    Provides persistence, query, and update operations.
    """

    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize graph store.

        Args:
            storage_dir: Directory for persistent storage. If None, uses in-memory only.
        """
        self.storage_dir = Path(storage_dir) if storage_dir else None
        self.observation_kg = ObservationKG()
        self.belief_graph = BeliefGraph()

        # NetworkX graphs for efficient graph operations
        self.kg_nx = nx.DiGraph()  # For observation KG
        self.belief_nx = nx.Graph()  # For belief graph (undirected for now)

        # Load existing data if storage directory exists
        if self.storage_dir and self.storage_dir.exists():
            self._load_from_storage()

    def _load_from_storage(self) -> None:
        """Load graphs from storage directory."""
        try:
            # Load observation KG
            kg_file = self.storage_dir / "observation_kg.json"
            if kg_file.exists():
                self.observation_kg = ObservationKG.load_from_file(str(kg_file))
                self._build_kg_nx()

            # Load belief graph
            belief_file = self.storage_dir / "belief_graph.json"
            if belief_file.exists():
                self.belief_graph = BeliefGraph.load_from_file(str(belief_file))
                self._build_belief_nx()

        except Exception as e:
            print(f"Warning: Failed to load from storage: {e}")

    def _build_kg_nx(self) -> None:
        """Build NetworkX graph from observation KG."""
        self.kg_nx.clear()

        # Add nodes
        for task_id, subgraph in self.observation_kg.task_subgraphs.items():
            for action_id, problem_file in subgraph.action_nodes.items():
                self.kg_nx.add_node(
                    action_id,
                    task_id=task_id,
                    action_type=problem_file.action_type.value,
                    outcome=problem_file.outcome.value,
                    intent_text=problem_file.intent_text,
                    **problem_file.metadata
                )

        # Add edges
        for task_id, subgraph in self.observation_kg.task_subgraphs.items():
            for edge in subgraph.edges:
                self.kg_nx.add_edge(
                    edge.source_id,
                    edge.target_id,
                    edge_type=edge.edge_type.value,
                    timestamp=edge.timestamp,
                    **edge.metadata
                )

    def _build_belief_nx(self) -> None:
        """Build NetworkX graph from belief graph."""
        self.belief_nx.clear()

        # Add atomic belief nodes
        for belief_id, belief in self.belief_graph.atomic_beliefs.items():
            self.belief_nx.add_node(
                belief_id,
                belief_type=belief.belief_type.value,
                status=belief.status.value,
                confidence=belief.confidence,
                **belief.metadata
            )

        # Add edges for conflicting beliefs
        for belief_id, conflicts in self.belief_graph.conflicting_beliefs.items():
            for conflict_id in conflicts:
                if conflict_id in self.belief_nx:
                    self.belief_nx.add_edge(belief_id, conflict_id, relation="conflicts")

    def save(self) -> None:
        """Save graphs to storage directory."""
        if not self.storage_dir:
            return

        # Ensure storage directory exists
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Save observation KG
            kg_file = self.storage_dir / "observation_kg.json"
            self.observation_kg.save_to_file(str(kg_file))

            # Save belief graph
            belief_file = self.storage_dir / "belief_graph.json"
            self.belief_graph.save_to_file(str(belief_file))

            # Save metadata
            metadata = {
                "last_saved": datetime.now(timezone.utc).isoformat(),
                "total_actions": sum(len(sg.action_nodes) for sg in self.observation_kg.task_subgraphs.values()),
                "total_beliefs": len(self.belief_graph.atomic_beliefs),
                "storage_version": "1.0",
            }
            metadata_file = self.storage_dir / "metadata.json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

        except Exception as e:
            print(f"Warning: Failed to save to storage: {e}")

    # Observation KG operations
    def add_action(self, problem_file: ProblemFile) -> str:
        """
        Add an action to the observation KG.

        Returns:
            action_id of the added action
        """
        # Create or get task subgraph
        task_id = problem_file.task_id
        subgraph = self.observation_kg.get_task_subgraph(task_id)
        if not subgraph:
            subgraph = TaskSubgraph(task_id=task_id)
            self.observation_kg.add_task_subgraph(subgraph)

        # Add action to subgraph
        subgraph.add_action(problem_file)
        # Keep reverse index in sync for all newly added actions.
        self.observation_kg.action_to_task[problem_file.action_id] = task_id

        # Update NetworkX graph
        self.kg_nx.add_node(
            problem_file.action_id,
            task_id=task_id,
            action_type=problem_file.action_type.value,
            outcome=problem_file.outcome.value,
            intent_text=problem_file.intent_text,
            **problem_file.metadata
        )

        return problem_file.action_id

    def add_edge(self, source_id: str, target_id: str, edge_type: EdgeType, metadata: Optional[Dict] = None) -> None:
        """
        Add an edge between two actions in the observation KG.
        """
        # Find task subgraph (both actions should be in the same task)
        source_info = self.observation_kg.get_action(source_id)
        target_info = self.observation_kg.get_action(target_id)

        if not source_info or not target_info:
            raise ValueError("Source or target action not found")

        source_action, source_task_id = source_info
        target_action, target_task_id = target_info

        if source_task_id != target_task_id:
            raise ValueError("Actions must be in the same task")

        # Create edge
        edge = KGEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            metadata=metadata or {}
        )

        # Add to subgraph
        subgraph = self.observation_kg.get_task_subgraph(source_task_id)
        if subgraph:
            subgraph.add_edge(edge)

        # Update NetworkX graph
        self.kg_nx.add_edge(
            source_id,
            target_id,
            edge_type=edge_type.value,
            timestamp=edge.timestamp,
            **edge.metadata
        )

    def get_action_successors(self, action_id: str, edge_type: Optional[EdgeType] = None) -> List[str]:
        """Get successor actions for a given action."""
        if action_id not in self.kg_nx:
            return []

        successors = list(self.kg_nx.successors(action_id))
        if edge_type:
            successors = [
                succ for succ in successors
                if self.kg_nx.edges[action_id, succ].get('edge_type') == edge_type.value
            ]

        return successors

    def get_action_predecessors(self, action_id: str, edge_type: Optional[EdgeType] = None) -> List[str]:
        """Get predecessor actions for a given action."""
        if action_id not in self.kg_nx:
            return []

        predecessors = list(self.kg_nx.predecessors(action_id))
        if edge_type:
            predecessors = [
                pred for pred in predecessors
                if self.kg_nx.edges[pred, action_id].get('edge_type') == edge_type.value
            ]

        return predecessors

    def find_similar_actions(self,
                            problem_file: ProblemFile,
                            max_results: int = 10,
                            embedding_view: str = "emb_task_sem") -> List[Tuple[str, ProblemFile, float]]:
        """
        Find similar actions using graph structure and node attributes.

        This is a simplified implementation for MVP.
        """
        # 1) Primary path: embedding similarity on observation KG.
        embedding_views = [
            embedding_view,
            "emb_task_sem",
            "emb_intent",
            "emb_error_sig",
            "emb_file_scope",
        ]
        embedding_candidates: Dict[str, Tuple[ProblemFile, float]] = {}
        for view in embedding_views:
            view_results = self.observation_kg.find_similar_actions(
                problem_file,
                embedding_view=view,
                threshold=0.25,
            )
            for action_id, action, score in view_results:
                prev = embedding_candidates.get(action_id)
                if prev is None or score > prev[1]:
                    embedding_candidates[action_id] = (action, score)

        if embedding_candidates:
            ranked = sorted(
                [(action_id, pair[0], pair[1]) for action_id, pair in embedding_candidates.items()],
                key=lambda x: x[2],
                reverse=True,
            )
            return ranked[:max_results]

        # 2) Fallback path: lexical similarity for cold-start.
        def _tokenize(text: str) -> Set[str]:
            return {tok for tok in text.lower().replace("\n", " ").split(" ") if tok}

        q_tokens = _tokenize(problem_file.intent_text or "")
        similar: List[Tuple[str, ProblemFile, float]] = []

        for task_id, subgraph in self.observation_kg.task_subgraphs.items():
            for action_id, action in subgraph.action_nodes.items():
                if action_id == problem_file.action_id:
                    continue

                a_tokens = _tokenize(action.intent_text or "")
                if not q_tokens and not a_tokens:
                    continue

                inter = len(q_tokens & a_tokens)
                union = max(1, len(q_tokens | a_tokens))
                similarity = inter / union

                if problem_file.action_type == action.action_type:
                    similarity += 0.2

                if similarity > 0.0:
                    similar.append((action_id, action, min(1.0, similarity)))

        similar.sort(key=lambda x: x[2], reverse=True)
        return similar[:max_results]

    # Belief graph operations
    def add_atomic_belief(self, belief: AtomicBelief) -> str:
        """Add an atomic belief to the belief graph."""
        belief_id = self.belief_graph.add_atomic_belief(belief)

        # Update NetworkX graph
        self.belief_nx.add_node(
            belief_id,
            belief_type=belief.belief_type.value,
            status=belief.status.value,
            confidence=belief.confidence,
            **belief.metadata
        )

        # Add conflict edges if any
        if belief_id in self.belief_graph.conflicting_beliefs:
            for conflict_id in self.belief_graph.conflicting_beliefs[belief_id]:
                if conflict_id in self.belief_nx:
                    self.belief_nx.add_edge(belief_id, conflict_id, relation="conflicts")

        return belief_id

    def add_attempt_belief(self, belief: AttemptBelief) -> None:
        """Add an attempt belief to the belief graph."""
        self.belief_graph.add_attempt_belief(belief)

    def get_relevant_beliefs(self,
                            env_cluster: Optional[str] = None,
                            repo_toolchain: Optional[str] = None,
                            action_type: Optional[str] = None,
                            max_results: int = 5) -> List[AtomicBelief]:
        """Get beliefs relevant to the given context."""
        beliefs = self.belief_graph.get_beliefs_for_context(
            env_cluster=env_cluster,
            repo_toolchain=repo_toolchain,
            action_type=action_type
        )
        return beliefs[:max_results]

    def update_belief_stats(self,
                           belief_id: str,
                           success_with: bool,
                           success_without: Optional[bool] = None) -> None:
        """Update statistics for a belief."""
        self.belief_graph.update_belief_stats(belief_id, success_with, success_without)

        # Update NetworkX node attributes
        if belief_id in self.belief_nx:
            belief = self.belief_graph.atomic_beliefs[belief_id]
            self.belief_nx.nodes[belief_id]["confidence"] = belief.confidence
            self.belief_nx.nodes[belief_id]["status"] = belief.status.value

    # Query operations
    def query_actions_by_outcome(self, outcome: str) -> List[ProblemFile]:
        """Query actions by outcome."""
        results = []

        for task_id, subgraph in self.observation_kg.task_subgraphs.items():
            for action_id, action in subgraph.action_nodes.items():
                if action.outcome.value == outcome:
                    results.append(action)

        return results

    def query_actions_by_type(self, action_type: str) -> List[ProblemFile]:
        """Query actions by action type."""
        results = []

        for task_id, subgraph in self.observation_kg.task_subgraphs.items():
            for action_id, action in subgraph.action_nodes.items():
                if action.action_type.value == action_type:
                    results.append(action)

        return results

    def get_last_action_id(self, task_id: str) -> Optional[str]:
        """Get the most recent action_id for a task, if any."""
        subgraph = self.observation_kg.get_task_subgraph(task_id)
        if not subgraph or not subgraph.action_nodes:
            return None

        def _parse_ts(action: ProblemFile) -> datetime:
            raw = action.timestamp
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(raw)
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        latest = max(subgraph.action_nodes.values(), key=_parse_ts)
        return latest.action_id

    def get_task_actions(self, task_id: str) -> List[ProblemFile]:
        """Return all actions for a task, sorted by timestamp."""
        subgraph = self.observation_kg.get_task_subgraph(task_id)
        if not subgraph:
            return []

        def _parse_ts(action: ProblemFile) -> datetime:
            raw = action.timestamp
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(raw)
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        return sorted(subgraph.action_nodes.values(), key=_parse_ts)

    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the graph store."""
        kg_stats = self.observation_kg.get_statistics()
        belief_stats = self.belief_graph.get_statistics()

        # NetworkX statistics
        nx_stats = {
            "kg_nodes": self.kg_nx.number_of_nodes(),
            "kg_edges": self.kg_nx.number_of_edges(),
            "belief_nodes": self.belief_nx.number_of_nodes(),
            "belief_edges": self.belief_nx.number_of_edges(),
            "kg_is_connected": nx.is_weakly_connected(self.kg_nx) if self.kg_nx.number_of_nodes() > 0 else False,
        }

        return {
            "observation_kg": kg_stats,
            "belief_graph": belief_stats,
            "networkx": nx_stats,
            "storage_dir": str(self.storage_dir) if self.storage_dir else None,
        }
