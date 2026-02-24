"""
分层检索器

基于Agent-mem架构文档第5节，实现：
- Task-level检索：检索相似任务的成功骨架 + 高置信workflow/env beliefs
- Action-level检索：优先检索fail_retry结构附近的相似失败-修复模式

支持多视角embedding和融合检索。
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Set
import numpy as np
from datetime import datetime

from ..models.problem_file import ProblemFile
from ..models.observation_kg import ObservationKG
from .embedder import MultiViewEmbedder, EmbeddingType, EmbeddingManager


class RetrievalLevel(Enum):
    """检索层级枚举"""
    TASK_LEVEL = "task_level"  # 任务级检索
    ACTION_LEVEL = "action_level"  # Action级检索


class RetrievalMode(Enum):
    """检索模式枚举"""
    PLANNING = "planning"  # 规划时检索
    EXECUTION = "execution"  # 执行时检索


class HierarchicalRetriever:
    """
    分层检索器

    支持不同层级和模式的检索，针对不同场景优化。
    """

    def __init__(self,
                 observation_kg: ObservationKG,
                 embedding_manager: EmbeddingManager,
                 similarity_threshold: float = 0.7):
        """
        初始化检索器

        Args:
            observation_kg: Observation KG实例
            embedding_manager: Embedding管理器
            similarity_threshold: 相似度阈值
        """
        self.observation_kg = observation_kg
        self.embedding_manager = embedding_manager
        self.similarity_threshold = similarity_threshold

    def retrieve_for_planning(self,
                             query: Dict[str, Any],
                             limit: int = 5) -> Dict[str, Any]:
        """
        规划时检索

        Args:
            query: 结构化的检索查询
            limit: 返回结果数量

        Returns:
            检索结果，包含success_skeleton和相关经验
        """
        # 提取查询信息
        task_semantic = query.get("task_semantic", "")
        file_scope = query.get("file_scope", "")
        env_cluster = query.get("env_cluster", "")
        intent_patterns = query.get("intent_patterns", [])

        results = {
            "success_skeletons": [],
            "workflow_beliefs": [],
            "env_adaptations": [],
            "evidence_refs": []
        }

        # 1. 任务语义检索
        if task_semantic:
            task_results = self._retrieve_by_task_semantic(task_semantic, limit)
            results["success_skeletons"].extend(task_results)

        # 2. 文件范围检索
        if file_scope:
            file_results = self._retrieve_by_file_scope(file_scope, limit)
            results["success_skeletons"].extend(file_results)

        # 3. 意图模式检索
        for intent_pattern in intent_patterns:
            intent_results = self._retrieve_by_intent(intent_pattern, limit // 2)
            results["success_skeletons"].extend(intent_results)

        # 去重和排序
        results["success_skeletons"] = self._deduplicate_and_sort(
            results["success_skeletons"],
            limit
        )

        return results

    def retrieve_for_execution(self,
                              error_context: Dict[str, Any],
                              limit: int = 3) -> Dict[str, Any]:
        """
        执行时检索（错误修复）

        Args:
            error_context: 错误上下文信息
            limit: 返回结果数量

        Returns:
            修复建议和相关经验
        """
        error_type = error_context.get("error_type", "")
        error_message = error_context.get("error_message", "")
        current_action = error_context.get("current_action", "")
        env_signature = error_context.get("env_signature", {})

        results = {
            "repair_suggestions": [],
            "similar_failures": [],
            "evidence_refs": []
        }

        # 1. 错误签名检索
        error_signature = {
            "error_type": error_type,
            "key_tokens": self._extract_key_tokens(error_message),
            "context": error_message[:200]
        }

        similar_failures = self.observation_kg.search_by_error_signature(error_signature)
        for failure in similar_failures[:limit]:
            # 查找对应的修复
            repair_pairs = self._find_repair_for_failure(failure)
            if repair_pairs:
                results["repair_suggestions"].extend(repair_pairs)
                results["similar_failures"].append(failure)

        # 2. 工具输出检索
        if current_action:
            action_results = self._retrieve_by_action_similarity(current_action, limit)
            results["repair_suggestions"].extend(action_results)

        # 去重和排序
        results["repair_suggestions"] = self._deduplicate_and_sort(
            results["repair_suggestions"],
            limit
        )
        results["similar_failures"] = results["similar_failures"][:limit]

        return results

    def _retrieve_by_task_semantic(self, task_semantic: str, limit: int) -> List[Dict[str, Any]]:
        """根据任务语义检索"""
        # 使用任务语义embedding检索
        embeddings = self.embedding_manager.search_similar(
            task_semantic,
            EmbeddingType.TASK_SEM.value,
            limit * 2
        )

        results = []
        for item in embeddings:
            problem_file_id = item.get("problem_file_id")
            similarity = item.get("similarity", 0.0)

            if similarity < self.similarity_threshold:
                continue

            # 获取完整的ProblemFile
            # 这里需要从存储加载，简化处理返回占位符
            result = {
                "problem_file_id": problem_file_id,
                "similarity": similarity,
                "type": "task_semantic_match",
                "evidence": f"Task semantic match: {similarity:.3f}"
            }
            results.append(result)

        return results

    def _retrieve_by_file_scope(self, file_scope: str, limit: int) -> List[Dict[str, Any]]:
        """根据文件范围检索"""
        # 使用文件范围embedding检索
        embeddings = self.embedding_manager.search_similar(
            file_scope,
            EmbeddingType.FILE_SCOPE.value,
            limit * 2
        )

        results = []
        for item in embeddings:
            problem_file_id = item.get("problem_file_id")
            similarity = item.get("similarity", 0.0)

            if similarity < self.similarity_threshold:
                continue

            result = {
                "problem_file_id": problem_file_id,
                "similarity": similarity,
                "type": "file_scope_match",
                "evidence": f"File scope match: {similarity:.3f}"
            }
            results.append(result)

        return results

    def _retrieve_by_intent(self, intent_pattern: str, limit: int) -> List[Dict[str, Any]]:
        """根据意图模式检索"""
        # 使用意图embedding检索
        embeddings = self.embedding_manager.search_similar(
            intent_pattern,
            EmbeddingType.INTENT.value,
            limit * 2
        )

        results = []
        for item in embeddings:
            problem_file_id = item.get("problem_file_id")
            similarity = item.get("similarity", 0.0)

            if similarity < self.similarity_threshold:
                continue

            result = {
                "problem_file_id": problem_file_id,
                "similarity": similarity,
                "type": "intent_match",
                "evidence": f"Intent match: {similarity:.3f}"
            }
            results.append(result)

        return results

    def _find_repair_for_failure(self, failure: ProblemFile) -> List[Dict[str, Any]]:
        """查找失败对应的修复"""
        # 从KG中查找fail_retry边
        # 这里简化处理，实际应从KG查询
        repair_pairs = []

        # 假设failure有task_id
        task_id = failure.task_id
        if not task_id:
            return repair_pairs

        # 获取任务的所有fail_retry对
        fail_retry_pairs = self.observation_kg.get_fail_retry_pairs(task_id)

        for fail_pf, repair_pf in fail_retry_pairs:
            if fail_pf.action_id == failure.action_id:
                repair_info = {
                    "failure_id": fail_pf.action_id,
                    "repair_id": repair_pf.action_id,
                    "repair_action": repair_pf.intent_text,
                    "evidence": f"Found repair for failure {fail_pf.action_id}",
                    "similarity": 1.0  # 精确匹配
                }
                repair_pairs.append(repair_info)

        return repair_pairs

    def _retrieve_by_action_similarity(self, current_action: str, limit: int) -> List[Dict[str, Any]]:
        """根据action相似性检索"""
        # 使用任务语义embedding检索相似action
        embeddings = self.embedding_manager.search_similar(
            current_action,
            EmbeddingType.TASK_SEM.value,
            limit
        )

        results = []
        for item in embeddings:
            problem_file_id = item.get("problem_file_id")
            similarity = item.get("similarity", 0.0)

            if similarity < self.similarity_threshold:
                continue

            result = {
                "problem_file_id": problem_file_id,
                "similarity": similarity,
                "type": "action_similarity",
                "evidence": f"Action similarity: {similarity:.3f}"
            }
            results.append(result)

        return results

    def _extract_key_tokens(self, error_message: str) -> List[str]:
        """从错误消息中提取关键token"""
        # 简单实现：提取大写单词和带下划线的单词
        import re

        # 提取大写单词（通常为错误类型）
        uppercase_tokens = re.findall(r'\b[A-Z][A-Z_]+\b', error_message)

        # 提取带下划线的单词
        underscore_tokens = re.findall(r'\b[a-zA-Z]+_[a-zA-Z_]+\b', error_message)

        # 提取引号中的内容
        quoted_tokens = re.findall(r'[\'"]([^\'"]+)[\'"]', error_message)

        # 组合所有token
        all_tokens = uppercase_tokens + underscore_tokens + quoted_tokens

        # 去重和限制数量
        unique_tokens = list(set(all_tokens))
        return unique_tokens[:10]

    def _deduplicate_and_sort(self, items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """去重和排序"""
        if not items:
            return []

        # 去重（基于problem_file_id）
        seen_ids = set()
        unique_items = []
        for item in items:
            item_id = item.get("problem_file_id")
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                unique_items.append(item)

        # 按相似度排序
        unique_items.sort(key=lambda x: x.get("similarity", 0.0), reverse=True)

        return unique_items[:limit]

    def get_retrieval_stats(self) -> Dict[str, Any]:
        """获取检索统计信息"""
        return {
            "similarity_threshold": self.similarity_threshold,
            "kg_nodes": self.observation_kg.graph.number_of_nodes() if hasattr(self.observation_kg, 'graph') else 0,
            "kg_edges": self.observation_kg.graph.number_of_edges() if hasattr(self.observation_kg, 'graph') else 0
        }


class FusionRetriever:
    """
    融合检索器

    组合多个视角的检索结果，进行融合排序。
    """

    def __init__(self, retrievers: List[HierarchicalRetriever], weights: Dict[str, float] = None):
        """
        初始化融合检索器

        Args:
            retrievers: 基础检索器列表
            weights: 各视角权重
        """
        self.retrievers = retrievers
        self.weights = weights or {
            "task_sem": 0.3,
            "file_scope": 0.2,
            "error_sig": 0.25,
            "intent": 0.15,
            "action_sim": 0.1
        }

    def fuse_results(self, all_results: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        融合多个检索结果

        Args:
            all_results: 各视角检索结果列表

        Returns:
            融合后的排序结果
        """
        if not all_results:
            return []

        # 收集所有结果
        all_items = []
        for results in all_results:
            all_items.extend(results)

        # 按ID分组
        grouped_items = {}
        for item in all_items:
            item_id = item.get("problem_file_id")
            if not item_id:
                continue

            if item_id not in grouped_items:
                grouped_items[item_id] = {
                    "id": item_id,
                    "scores": {},
                    "details": item
                }

            # 记录各视角分数
            item_type = item.get("type", "unknown")
            similarity = item.get("similarity", 0.0)
            grouped_items[item_id]["scores"][item_type] = similarity

        # 计算融合分数
        fused_items = []
        for item_id, item_data in grouped_items.items():
            fused_score = 0.0
            for score_type, score in item_data["scores"].items():
                weight = self.weights.get(score_type, 0.1)
                fused_score += score * weight

            fused_item = {
                "problem_file_id": item_id,
                "fused_score": fused_score,
                "component_scores": item_data["scores"],
                "details": item_data["details"]
            }
            fused_items.append(fused_item)

        # 按融合分数排序
        fused_items.sort(key=lambda x: x["fused_score"], reverse=True)

        return fused_items