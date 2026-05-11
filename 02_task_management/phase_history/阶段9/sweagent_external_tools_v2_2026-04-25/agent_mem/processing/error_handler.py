"""
错误处理器 - 执行时修复建议

基于Agent-mem架构文档第5.2节：Execution-time出错回忆（易错点经验 + 修复建议）
触发：执行中遇到报错/异常返回/未达预期状态
"""

from typing import Dict, List, Optional, Any, Tuple
import json
from datetime import datetime

from ..core.problem_file import ProblemFile, ActionType, Outcome
from ..core.observation_kg import ObservationKG, EdgeType
from ..retrieval.retriever import HierarchicalRetriever
from ..storage.graph_store import GraphStore


class ErrorHandler:
    """
    错误处理器

    处理执行时错误，检索相似修复经验，生成修复建议。
    """

    def __init__(self,
                 graph_store: GraphStore,
                 observation_kg: ObservationKG,
                 retriever: HierarchicalRetriever = None):
        """
        初始化错误处理器

        Args:
            graph_store: 图存储
            observation_kg: Observation KG
            retriever: 检索器
        """
        self.graph_store = graph_store
        self.observation_kg = observation_kg
        self.retriever = retriever

    def handle_error(self,
                     error_context: Dict[str, Any],
                     current_problem_file: Optional[ProblemFile] = None) -> Dict[str, Any]:
        """
        处理错误并生成修复建议

        Args:
            error_context: 错误上下文信息
            current_problem_file: 当前ProblemFile（可选）

        Returns:
            修复建议结果
        """
        # 提取错误信息
        error_type = error_context.get("error_type", "unknown")
        error_message = error_context.get("error_message", "")
        current_action = error_context.get("action", "")
        thought = error_context.get("thought", "")
        env_signature = error_context.get("env_signature", {})

        # 构建检索查询
        query = self._build_repair_query(
            error_type, error_message, current_action, env_signature
        )

        # 检索相似修复经验
        if self.retriever:
            retrieval_results = self.retriever.retrieve_for_execution(query, limit=3)
        else:
            retrieval_results = self._simple_retrieval(query)

        # 生成修复建议
        suggestions = self._generate_repair_suggestions(
            retrieval_results, error_context, current_problem_file
        )

        # 记录错误（用于后续学习）
        if current_problem_file:
            self._record_error(current_problem_file, error_context, suggestions)

        return {
            "error_type": error_type,
            "error_message": error_message[:500],  # 限制长度
            "retrieval_query": query,
            "retrieval_results": retrieval_results,
            "repair_suggestions": suggestions,
            "generated_at": datetime.now().isoformat()
        }

    def analyze_error(self, error_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Compatibility wrapper for legacy callers expecting a suggestion list."""
        result = self.handle_error(error_context, current_problem_file=None)
        return result.get("repair_suggestions", [])

    def _build_repair_query(self,
                           error_type: str,
                           error_message: str,
                           current_action: str,
                           env_signature: Dict[str, Any]) -> Dict[str, Any]:
        """构建修复检索查询"""
        return {
            "error_type": error_type,
            "error_message": error_message,
            "current_action": current_action,
            "env_signature": env_signature,
            "key_tokens": self._extract_key_tokens(error_message),
            "timestamp": datetime.now().isoformat()
        }

    def _simple_retrieval(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """
        简单检索（在没有正式检索器时使用）

        Args:
            query: 检索查询

        Returns:
            检索结果
        """
        # 简化实现：基于错误类型和关键token的简单匹配
        error_type = query.get("error_type", "")
        key_tokens = query.get("key_tokens", [])

        # 从KG中搜索相似错误
        similar_failures = []

        # 这里简化处理，实际应使用KG的搜索功能
        # 假设我们有一个搜索方法
        if hasattr(self.observation_kg, 'search_by_error_signature'):
            error_signature = {
                "error_type": error_type,
                "key_tokens": key_tokens
            }
            similar_failures = self.observation_kg.search_by_error_signature(error_signature)

        # 查找修复
        repair_suggestions = []
        for failure in similar_failures[:3]:  # 限制数量
            repair_info = self._find_repair_for_failure(failure)
            if repair_info:
                repair_suggestions.append(repair_info)

        return {
            "similar_failures": similar_failures[:5],
            "repair_suggestions": repair_suggestions,
            "evidence_refs": []
        }

    def _generate_repair_suggestions(self,
                                    retrieval_results: Dict[str, Any],
                                    error_context: Dict[str, Any],
                                    current_problem_file: Optional[ProblemFile]) -> List[Dict[str, Any]]:
        """生成修复建议"""
        suggestions = []

        # 1. 从检索结果中提取修复建议
        repair_suggestions = retrieval_results.get("repair_suggestions", [])
        for repair in repair_suggestions[:3]:  # 取前3个
            suggestion = {
                "type": "retrieved_repair",
                "confidence": repair.get("similarity", 0.5),
                "description": repair.get("evidence", "Retrieved repair suggestion"),
                "action": repair.get("repair_action", ""),
                "source": repair.get("failure_id", "unknown"),
                "evidence_refs": [repair.get("failure_id"), repair.get("repair_id")]
            }
            suggestions.append(suggestion)

        # 2. 基于错误类型的通用建议
        error_type = error_context.get("error_type", "")
        generic_suggestions = self._get_generic_suggestions(error_type)
        suggestions.extend(generic_suggestions)

        # 3. 基于当前上下文的建议
        if current_problem_file:
            context_suggestion = self._generate_context_suggestion(current_problem_file, error_context)
            if context_suggestion:
                suggestions.append(context_suggestion)

        # 排序（按置信度）
        suggestions.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)

        return suggestions

    def _find_repair_for_failure(self, failure: ProblemFile) -> Optional[Dict[str, Any]]:
        """查找失败对应的修复"""
        # 这里简化处理，实际应从KG查询fail_retry边
        task_id = failure.task_id
        if not task_id:
            return None

        # 获取任务的所有fail_retry对
        fail_retry_pairs = self.observation_kg.get_fail_retry_pairs(task_id)

        for fail_pf, repair_pf in fail_retry_pairs:
            if fail_pf.action_id == failure.action_id:
                return {
                    "failure_id": fail_pf.action_id,
                    "repair_id": repair_pf.action_id,
                    "repair_action": repair_pf.intent_text,
                    "similarity": 1.0,
                    "evidence": f"Exact repair match for failure {fail_pf.action_id}"
                }

        return None

    def _extract_key_tokens(self, error_message: str) -> List[str]:
        """从错误消息中提取关键token"""
        import re

        # 提取大写单词
        uppercase_tokens = re.findall(r'\b[A-Z][A-Z_]+\b', error_message)

        # 提取带下划线的单词
        underscore_tokens = re.findall(r'\b[a-zA-Z]+_[a-zA-Z_]+\b', error_message)

        # 提取引号中的内容
        quoted_tokens = re.findall(r'[\'"]([^\'"]+)[\'"]', error_message)

        # 提取数字（如错误代码）
        number_tokens = re.findall(r'\b\d{3,}\b', error_message)

        # 组合所有token
        all_tokens = uppercase_tokens + underscore_tokens + quoted_tokens + number_tokens

        # 去重和限制数量
        unique_tokens = list(set(all_tokens))
        return unique_tokens[:15]

    def _get_generic_suggestions(self, error_type: str) -> List[Dict[str, Any]]:
        """获取基于错误类型的通用建议"""
        generic_suggestions = {
            "syntax_error": [
                {
                    "type": "generic",
                    "confidence": 0.6,
                    "description": "检查代码语法，查看错误行附近的拼写错误",
                    "action": "Review syntax around the error line"
                },
                {
                    "type": "generic",
                    "confidence": 0.5,
                    "description": "检查括号、引号是否匹配",
                    "action": "Check for matching brackets/quotes"
                }
            ],
            "import_error": [
                {
                    "type": "generic",
                    "confidence": 0.7,
                    "description": "检查模块是否已安装或路径是否正确",
                    "action": "Check if module is installed or path is correct"
                },
                {
                    "type": "generic",
                    "confidence": 0.6,
                    "description": "检查PYTHONPATH环境变量",
                    "action": "Check PYTHONPATH environment variable"
                }
            ],
            "file_not_found": [
                {
                    "type": "generic",
                    "confidence": 0.8,
                    "description": "检查文件路径是否存在，注意大小写",
                    "action": "Check if file path exists, note case sensitivity"
                },
                {
                    "type": "generic",
                    "confidence": 0.6,
                    "description": "检查当前工作目录",
                    "action": "Check current working directory"
                }
            ],
            "permission_error": [
                {
                    "type": "generic",
                    "confidence": 0.7,
                    "description": "检查文件/目录权限",
                    "action": "Check file/directory permissions"
                }
            ],
            "timeout": [
                {
                    "type": "generic",
                    "confidence": 0.6,
                    "description": "增加超时时间或优化操作",
                    "action": "Increase timeout or optimize operation"
                }
            ]
        }

        return generic_suggestions.get(error_type, [])

    def _generate_context_suggestion(self,
                                    problem_file: ProblemFile,
                                    error_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """生成基于上下文的建议"""
        # 基于当前action类型生成建议
        action_type = problem_file.action_type

        suggestions_by_type = {
            ActionType.TOOL_CALL.value: {
                "type": "context",
                "confidence": 0.5,
                "description": "检查工具参数和格式",
                "action": "Check tool parameters and formatting"
            },
            ActionType.CODE_EDIT.value: {
                "type": "context",
                "confidence": 0.5,
                "description": "检查代码更改是否引入错误",
                "action": "Check if code changes introduced the error"
            },
            ActionType.RUN_TEST.value: {
                "type": "context",
                "confidence": 0.5,
                "description": "检查测试环境和依赖",
                "action": "Check test environment and dependencies"
            }
        }

        return suggestions_by_type.get(action_type.value)

    def _record_error(self,
                     problem_file: ProblemFile,
                     error_context: Dict[str, Any],
                     suggestions: List[Dict[str, Any]]) -> None:
        """记录错误用于学习"""
        # 更新ProblemFile的outcome为FAIL
        problem_file.outcome = Outcome.FAIL
        problem_file.failure_signature = {
            "error_type": error_context.get("error_type"),
            "key_tokens": self._extract_key_tokens(error_context.get("error_message", "")),
            "context": error_context.get("error_message", "")[:500],
            "suggestions_tried": [s.get("type") for s in suggestions]
        }

        # 保存到存储
        if self.graph_store:
            # 这里简化处理，实际应调用存储接口
            pass

    def get_handler_stats(self) -> Dict[str, Any]:
        """获取处理器统计信息"""
        return {
            "initialized": True,
            "retriever_available": self.retriever is not None,
            "graph_store_available": self.graph_store is not None,
            "kg_available": self.observation_kg is not None
        }


class FixSuggester:
    """
    修复建议生成器

    专门负责生成具体的修复建议。
    """

    def __init__(self, error_handler: ErrorHandler):
        self.error_handler = error_handler

    def suggest_fixes(self,
                     error_context: Dict[str, Any],
                     max_suggestions: int = 3) -> List[Dict[str, Any]]:
        """
        生成修复建议

        Args:
            error_context: 错误上下文
            max_suggestions: 最大建议数量

        Returns:
            修复建议列表
        """
        # 使用ErrorHandler处理错误
        result = self.error_handler.handle_error(error_context)

        # 提取和建议
        suggestions = result.get("repair_suggestions", [])

        # 格式化为可执行的建议
        executable_suggestions = []
        for i, suggestion in enumerate(suggestions[:max_suggestions]):
            executable_suggestion = {
                "id": f"suggestion_{i+1}",
                "priority": i + 1,
                "description": suggestion.get("description", ""),
                "action": suggestion.get("action", ""),
                "confidence": suggestion.get("confidence", 0.0),
                "type": suggestion.get("type", "unknown"),
                "expected_outcome": f"Error should be resolved or reduced",
                "validation_steps": [
                    "Execute the suggested action",
                    "Check if error disappears or changes"
                ]
            }
            executable_suggestions.append(executable_suggestion)

        return executable_suggestions
