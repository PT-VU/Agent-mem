"""
事实图Observation KG实现

基于Agent-mem架构文档第3.2节：
- 节点：每个action的problem file
- 每次任务执行：图上的一棵树/有向结构（含主链与重试分支）
- 跨任务：多个不连通子图（任务孤岛）共存于同一图数据库空间
"""

import json
import os
from typing import Dict, List, Optional, Set, Tuple, Any
from pathlib import Path
from datetime import datetime
import networkx as nx
from dataclasses import asdict

from .problem_file import ProblemFile, KGGraphEdge, EdgeType, ActionType, Outcome


class ObservationKG:
    """
    事实图Observation KG：以Action为节点、任务为树/子图
    """

    def __init__(self, storage_path: Optional[str] = None):
        """
        初始化Observation KG

        Args:
            storage_path: 本地存储路径，如果为None则使用内存存储
        """
        self.storage_path = storage_path
        self.graph = nx.DiGraph()  # 有向图
        self.task_subgraphs: Dict[str, Set[str]] = {}  # 任务ID -> 节点ID集合

        if storage_path:
            os.makedirs(storage_path, exist_ok=True)
            self._load_from_storage()

    def add_problem_file(self, problem_file: ProblemFile, task_id: str) -> None:
        """
        添加ProblemFile到KG

        Args:
            problem_file: ProblemFile实例
            task_id: 任务标识符
        """
        # 添加节点
        self.graph.add_node(
            problem_file.action_id,
            type="problem_file",
            data=asdict(problem_file),
            task_id=task_id,
            timestamp=problem_file.timestamp
        )

        # 更新任务子图
        if task_id not in self.task_subgraphs:
            self.task_subgraphs[task_id] = set()
        self.task_subgraphs[task_id].add(problem_file.action_id)

        # 保存到存储
        if self.storage_path:
            self._save_node(problem_file)

    def add_edge(self, source_id: str, target_id: str, edge_type: EdgeType, metadata: Dict[str, Any] = None) -> None:
        """
        添加边到KG

        Args:
            source_id: 源节点ID
            target_id: 目标节点ID
            edge_type: 边类型
            metadata: 边元数据
        """
        if source_id not in self.graph or target_id not in self.graph:
            raise ValueError(f"节点不存在: {source_id} -> {target_id}")

        edge_data = {
            "edge_type": edge_type.value,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat()
        }

        self.graph.add_edge(source_id, target_id, **edge_data)

        # 保存到存储
        if self.storage_path:
            self._save_edge(source_id, target_id, edge_data)

    def get_success_next_chain(self, task_id: str) -> List[ProblemFile]:
        """
        获取任务的成功链（主链）

        Args:
            task_id: 任务ID

        Returns:
            ProblemFile列表，按执行顺序排列
        """
        if task_id not in self.task_subgraphs:
            return []

        # 找出所有success_next边
        task_nodes = self.task_subgraphs[task_id]
        success_edges = [
            (u, v) for u, v, data in self.graph.edges(data=True)
            if u in task_nodes and v in task_nodes and data.get("edge_type") == EdgeType.SUCCESS_NEXT.value
        ]

        # 构建顺序链
        chain = []
        visited = set()

        def follow_chain(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)

            # 添加到链
            node_data = self.graph.nodes[node_id]["data"]
            chain.append(ProblemFile.from_dict(node_data))

            # 查找下一个success_next边
            for _, target, data in self.graph.out_edges(node_id, data=True):
                if data.get("edge_type") == EdgeType.SUCCESS_NEXT.value:
                    follow_chain(target)

        # 找到起点（没有success_next入边的节点）
        start_nodes = []
        for node_id in task_nodes:
            has_incoming_success = False
            for _, target, data in self.graph.in_edges(node_id, data=True):
                if data.get("edge_type") == EdgeType.SUCCESS_NEXT.value:
                    has_incoming_success = True
                    break
            if not has_incoming_success:
                start_nodes.append(node_id)

        # 从每个起点开始构建链
        for start_node in start_nodes:
            follow_chain(start_node)

        return chain

    def get_fail_retry_pairs(self, task_id: str) -> List[Tuple[ProblemFile, ProblemFile]]:
        """
        获取任务的失败-重试对

        Args:
            task_id: 任务ID

        Returns:
            (失败ProblemFile, 重试ProblemFile) 对列表
        """
        if task_id not in self.task_subgraphs:
            return []

        task_nodes = self.task_subgraphs[task_id]
        pairs = []

        for u, v, data in self.graph.edges(data=True):
            if u in task_nodes and v in task_nodes and data.get("edge_type") == EdgeType.FAIL_RETRY.value:
                u_data = self.graph.nodes[u]["data"]
                v_data = self.graph.nodes[v]["data"]
                pairs.append((
                    ProblemFile.from_dict(u_data),
                    ProblemFile.from_dict(v_data)
                ))

        return pairs

    def get_task_subgraph(self, task_id: str) -> Dict[str, Any]:
        """
        获取任务子图的完整表示

        Args:
            task_id: 任务ID

        Returns:
            包含节点和边的字典表示
        """
        if task_id not in self.task_subgraphs:
            return {"nodes": [], "edges": []}

        task_nodes = self.task_subgraphs[task_id]

        # 收集节点
        nodes = []
        for node_id in task_nodes:
            node_data = self.graph.nodes[node_id]
            nodes.append({
                "id": node_id,
                "type": node_data.get("type", "unknown"),
                "task_id": node_data.get("task_id", ""),
                "timestamp": node_data.get("timestamp"),
                "data": node_data.get("data", {})
            })

        # 收集边
        edges = []
        for u, v, data in self.graph.edges(data=True):
            if u in task_nodes and v in task_nodes:
                edges.append({
                    "source": u,
                    "target": v,
                    "edge_type": data.get("edge_type"),
                    "metadata": data.get("metadata", {}),
                    "created_at": data.get("created_at")
                })

        return {"nodes": nodes, "edges": edges}

    def search_by_error_signature(self, error_signature: Dict[str, Any]) -> List[ProblemFile]:
        """
        根据错误签名搜索ProblemFile

        Args:
            error_signature: 错误签名字典

        Returns:
            匹配的ProblemFile列表
        """
        results = []
        for node_id, data in self.graph.nodes(data=True):
            problem_file_data = data.get("data", {})
            if not problem_file_data:
                continue

            pf_failure_sig = problem_file_data.get("failure_signature")
            if not pf_failure_sig:
                continue

            # 简单匹配：检查错误类型和关键token
            if self._signature_match(pf_failure_sig, error_signature):
                results.append(ProblemFile.from_dict(problem_file_data))

        return results

    def search_by_intent(self, intent_pattern: str) -> List[ProblemFile]:
        """
        根据意图模式搜索ProblemFile

        Args:
            intent_pattern: 意图文本模式（字符串匹配）

        Returns:
            匹配的ProblemFile列表
        """
        results = []
        for node_id, data in self.graph.nodes(data=True):
            problem_file_data = data.get("data", {})
            if not problem_file_data:
                continue

            intent_text = problem_file_data.get("intent_text", "")
            if intent_pattern.lower() in intent_text.lower():
                results.append(ProblemFile.from_dict(problem_file_data))

        return results

    def _signature_match(self, sig1: Dict[str, Any], sig2: Dict[str, Any]) -> bool:
        """
        简单的错误签名匹配
        """
        # 检查错误类型
        if sig1.get("error_type") != sig2.get("error_type"):
            return False

        # 检查关键token（如果有）
        tokens1 = set(sig1.get("key_tokens", []))
        tokens2 = set(sig2.get("key_tokens", []))
        if tokens1 and tokens2 and not tokens1.intersection(tokens2):
            return False

        return True

    def _save_node(self, problem_file: ProblemFile) -> None:
        """保存节点到本地存储"""
        if not self.storage_path:
            return

        node_path = Path(self.storage_path) / "nodes" / f"{problem_file.action_id}.json"
        node_path.parent.mkdir(parents=True, exist_ok=True)

        with open(node_path, "w", encoding="utf-8") as f:
            json.dump(problem_file.to_dict(), f, ensure_ascii=False, indent=2)

    def _save_edge(self, source_id: str, target_id: str, edge_data: Dict[str, Any]) -> None:
        """保存边到本地存储"""
        if not self.storage_path:
            return

        edge_path = Path(self.storage_path) / "edges" / f"{source_id}_{target_id}.json"
        edge_path.parent.mkdir(parents=True, exist_ok=True)

        with open(edge_path, "w", encoding="utf-8") as f:
            json.dump({
                "source_id": source_id,
                "target_id": target_id,
                **edge_data
            }, f, ensure_ascii=False, indent=2)

    def _load_from_storage(self) -> None:
        """从本地存储加载KG"""
        if not self.storage_path:
            return

        storage_path = Path(self.storage_path)

        # 加载节点
        nodes_dir = storage_path / "nodes"
        if nodes_dir.exists():
            for node_file in nodes_dir.glob("*.json"):
                with open(node_file, "r", encoding="utf-8") as f:
                    node_data = json.load(f)

                problem_file = ProblemFile.from_dict(node_data)
                task_id = problem_file.task_id

                self.graph.add_node(
                    problem_file.action_id,
                    type="problem_file",
                    data=node_data,
                    task_id=task_id,
                    timestamp=problem_file.timestamp
                )

                if task_id not in self.task_subgraphs:
                    self.task_subgraphs[task_id] = set()
                self.task_subgraphs[task_id].add(problem_file.action_id)

        # 加载边
        edges_dir = storage_path / "edges"
        if edges_dir.exists():
            for edge_file in edges_dir.glob("*.json"):
                with open(edge_file, "r", encoding="utf-8") as f:
                    edge_data = json.load(f)

                source_id = edge_data.get("source_id")
                target_id = edge_data.get("target_id")
                edge_type = edge_data.get("edge_type")
                metadata = edge_data.get("metadata", {})
                created_at = edge_data.get("created_at")

                if source_id in self.graph and target_id in self.graph:
                    self.graph.add_edge(
                        source_id,
                        target_id,
                        edge_type=edge_type,
                        metadata=metadata,
                        created_at=created_at
                    )

    def save(self) -> None:
        """保存整个KG到存储"""
        if not self.storage_path:
            return

        # 保存配置
        config = {
            "storage_path": self.storage_path,
            "graph_info": {
                "num_nodes": self.graph.number_of_nodes(),
                "num_edges": self.graph.number_of_edges(),
                "num_tasks": len(self.task_subgraphs)
            },
            "task_ids": list(self.task_subgraphs.keys())
        }

        config_path = Path(self.storage_path) / "config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)