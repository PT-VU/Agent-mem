"""
RCA（根因分析）Agent

基于Agent-mem架构文档第4.3节：
- 输入：某次任务的事实图子图（主链 + retry分支）
- 输出：root_cause_nodes（最小集合）、propagation_chain（传播链）、corrective_actions（修复动作模板）

MVP简化版本，专注于常见错误模式分析。
"""

from typing import Dict, List, Optional, Any, Tuple, Set
from datetime import datetime
from enum import Enum

from ..models.problem_file import ProblemFile, Outcome, ActionType
from ..models.observation_kg import ObservationKG, EdgeType


class ErrorModule(Enum):
    """错误模块枚举"""
    MEMORY = "memory"
    REFLECTION = "reflection"
    PLANNING = "planning"
    ACTION = "action"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class ErrorType(Enum):
    """错误类型枚举"""
    SYNTAX_ERROR = "syntax_error"
    IMPORT_ERROR = "import_error"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_ERROR = "permission_error"
    TIMEOUT = "timeout"
    ASSERTION_FAILED = "assertion_failed"
    TEST_FAILURE = "test_failure"
    COMPILATION_ERROR = "compilation_error"
    RUNTIME_ERROR = "runtime_error"
    LOGIC_ERROR = "logic_error"
    CONFIGURATION_ERROR = "configuration_error"


class RCAAgent:
    """
    RCA Agent：根因分析代理

    从任务轨迹中分析失败的根本原因。
    """

    def __init__(self, observation_kg: ObservationKG):
        """
        初始化RCA Agent

        Args:
            observation_kg: Observation KG实例
        """
        self.observation_kg = observation_kg

    def analyze_task_failure(self, task_id: str) -> Dict[str, Any]:
        """
        分析任务失败原因

        Args:
            task_id: 任务ID

        Returns:
            RCA分析结果
        """
        # 获取任务子图
        task_subgraph = self.observation_kg.get_task_subgraph(task_id)
        if not task_subgraph.get("nodes"):
            return {"error": "Task not found", "task_id": task_id}

        # 找出失败节点
        failure_nodes = self._identify_failure_nodes(task_subgraph)

        # 如果没有失败节点，返回空结果
        if not failure_nodes:
            return {
                "task_id": task_id,
                "has_failures": False,
                "root_cause_nodes": [],
                "propagation_chains": [],
                "corrective_actions": [],
                "confidence": 0.0
            }

        # 分析每个失败节点
        analysis_results = []
        for failure_node in failure_nodes:
            analysis = self._analyze_single_failure(failure_node, task_subgraph)
            analysis_results.append(analysis)

        # 合并分析结果
        combined_result = self._combine_analysis_results(analysis_results, task_id)

        return combined_result

    def _identify_failure_nodes(self, task_subgraph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """识别失败节点"""
        failure_nodes = []
        for node in task_subgraph.get("nodes", []):
            node_data = node.get("data", {})
            outcome = node_data.get("outcome", "")

            if outcome == "fail":
                failure_nodes.append(node)

        return failure_nodes

    def _analyze_single_failure(self,
                               failure_node: Dict[str, Any],
                               task_subgraph: Dict[str, Any]) -> Dict[str, Any]:
        """分析单个失败节点"""
        node_id = failure_node.get("id")
        node_data = failure_node.get("data", {})

        # 提取失败信息
        failure_signature = node_data.get("failure_signature", {})
        error_type_str = failure_signature.get("error_type", "unknown")
        action_type = node_data.get("action_type", "")
        intent_text = node_data.get("intent_text", "")

        # 识别错误类型
        error_type = self._classify_error_type(error_type_str, intent_text)

        # 查找可能的根因节点
        root_cause_candidates = self._find_root_cause_candidates(
            node_id, task_subgraph, error_type
        )

        # 确定最可能的根因
        root_cause_nodes = self._select_root_causes(root_cause_candidates, task_subgraph)

        # 构建传播链
        propagation_chain = self._build_propagation_chain(
            root_cause_nodes, node_id, task_subgraph
        )

        # 生成纠正动作
        corrective_actions = self._generate_corrective_actions(
            root_cause_nodes, error_type, action_type
        )

        # 生成预防检查
        preventive_checks = self._generate_preventive_checks(
            root_cause_nodes, error_type, action_type
        )

        # 确定错误模块
        error_module = self._determine_error_module(root_cause_nodes, error_type, action_type)

        return {
            "failure_node_id": node_id,
            "error_type": error_type.value,
            "error_module": error_module.value,
            "root_cause_nodes": root_cause_nodes,
            "propagation_chain": propagation_chain,
            "corrective_actions": corrective_actions,
            "preventive_checks": preventive_checks,
            "confidence": self._calculate_confidence(root_cause_nodes, error_type),
            "evidence_refs": [node_id]
        }

    def _classify_error_type(self, error_type_str: str, intent_text: str) -> ErrorType:
        """分类错误类型"""
        error_type_str = error_type_str.lower()

        # 基于错误字符串分类
        error_mapping = {
            "syntax": ErrorType.SYNTAX_ERROR,
            "import": ErrorType.IMPORT_ERROR,
            "file": ErrorType.FILE_NOT_FOUND,
            "permission": ErrorType.PERMISSION_ERROR,
            "timeout": ErrorType.TIMEOUT,
            "assert": ErrorType.ASSERTION_FAILED,
            "test": ErrorType.TEST_FAILURE,
            "compile": ErrorType.COMPILATION_ERROR,
            "runtime": ErrorType.RUNTIME_ERROR,
            "logic": ErrorType.LOGIC_ERROR,
            "config": ErrorType.CONFIGURATION_ERROR,
        }

        for key, error_enum in error_mapping.items():
            if key in error_type_str:
                return error_enum

        # 基于意图文本分类
        intent_lower = intent_text.lower()
        if "test" in intent_lower:
            return ErrorType.TEST_FAILURE
        elif "import" in intent_lower or "require" in intent_lower:
            return ErrorType.IMPORT_ERROR
        elif "file" in intent_lower:
            return ErrorType.FILE_NOT_FOUND

        return ErrorType.UNKNOWN

    def _find_root_cause_candidates(self,
                                   failure_node_id: str,
                                   task_subgraph: Dict[str, Any],
                                   error_type: ErrorType) -> List[Dict[str, Any]]:
        """查找可能的根因候选节点"""
        candidates = []

        # 获取任务的所有节点
        all_nodes = task_subgraph.get("nodes", [])

        # 策略1：查找相同错误类型的早期节点
        for node in all_nodes:
            node_id = node.get("id")
            if node_id == failure_node_id:
                continue

            node_data = node.get("data", {})
            node_outcome = node_data.get("outcome", "")

            # 如果节点已经失败，可能是早期根因
            if node_outcome == "fail":
                node_error_type = self._classify_error_type(
                    node_data.get("failure_signature", {}).get("error_type", ""),
                    node_data.get("intent_text", "")
                )
                if node_error_type == error_type:
                    candidates.append(node)

        # 策略2：查找相关的文件操作节点
        failure_node = next(
            (n for n in all_nodes if n.get("id") == failure_node_id),
            None
        )
        if failure_node:
            failure_data = failure_node.get("data", {})
            failure_files = set(failure_data.get("touched_files", []))

            for node in all_nodes:
                node_id = node.get("id")
                if node_id == failure_node_id:
                    continue

                node_data = node.get("data", {})
                node_files = set(node_data.get("touched_files", []))

                # 如果有文件重叠，可能是相关节点
                if failure_files.intersection(node_files):
                    candidates.append(node)

        return candidates

    def _select_root_causes(self,
                           candidates: List[Dict[str, Any]],
                           task_subgraph: Dict[str, Any]) -> List[str]:
        """从候选节点中选择根因节点"""
        if not candidates:
            return []

        # 简单策略：选择最早的失败节点
        candidates_with_times = []
        for candidate in candidates:
            node_data = candidate.get("data", {})
            timestamp_str = node_data.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                candidates_with_times.append((candidate, timestamp))
            except:
                continue

        # 按时间排序（最早优先）
        candidates_with_times.sort(key=lambda x: x[1])

        # 选择前2个作为根因
        root_causes = [candidate[0].get("id") for candidate in candidates_with_times[:2]]

        return root_causes

    def _build_propagation_chain(self,
                                root_cause_ids: List[str],
                                failure_node_id: str,
                                task_subgraph: Dict[str, Any]) -> List[str]:
        """构建传播链（从根因到失败节点）"""
        if not root_cause_ids:
            return []

        # 简化实现：返回根因和失败节点的ID列表
        chain = root_cause_ids.copy()
        if failure_node_id not in chain:
            chain.append(failure_node_id)

        return chain

    def _generate_corrective_actions(self,
                                    root_cause_ids: List[str],
                                    error_type: ErrorType,
                                    action_type: str) -> List[Dict[str, Any]]:
        """生成纠正动作"""
        actions = []

        # 基于错误类型的通用纠正动作
        corrective_templates = {
            ErrorType.SYNTAX_ERROR: [
                {
                    "action": "review_syntax",
                    "description": "检查并修复语法错误",
                    "parameters": {"error_location": "near the reported line"}
                }
            ],
            ErrorType.IMPORT_ERROR: [
                {
                    "action": "install_missing_package",
                    "description": "安装缺失的包",
                    "parameters": {"package_name": "extract from error message"}
                },
                {
                    "action": "add_to_path",
                    "description": "添加路径到PYTHONPATH",
                    "parameters": {"path": "extract from error message"}
                }
            ],
            ErrorType.FILE_NOT_FOUND: [
                {
                    "action": "check_file_path",
                    "description": "检查文件路径是否正确",
                    "parameters": {"expected_path": "from action context"}
                },
                {
                    "action": "create_missing_file",
                    "description": "创建缺失的文件",
                    "parameters": {"file_path": "from action context"}
                }
            ],
            ErrorType.PERMISSION_ERROR: [
                {
                    "action": "change_permissions",
                    "description": "修改文件/目录权限",
                    "parameters": {"path": "from action context", "mode": "755"}
                }
            ],
            ErrorType.TIMEOUT: [
                {
                    "action": "increase_timeout",
                    "description": "增加超时时间",
                    "parameters": {"timeout_seconds": "current * 2"}
                },
                {
                    "action": "optimize_operation",
                    "description": "优化耗时操作",
                    "parameters": {}
                }
            ]
        }

        # 添加错误类型特定的动作
        if error_type in corrective_templates:
            actions.extend(corrective_templates[error_type])

        # 添加根因特定的动作
        for root_cause_id in root_cause_ids:
            actions.append({
                "action": "review_previous_action",
                "description": f"检查并修复根因动作 {root_cause_id}",
                "parameters": {"action_id": root_cause_id}
            })

        return actions

    def _generate_preventive_checks(self,
                                   root_cause_ids: List[str],
                                   error_type: ErrorType,
                                   action_type: str) -> List[Dict[str, Any]]:
        """生成预防检查"""
        checks = []

        # 基于错误类型的预防检查
        preventive_templates = {
            ErrorType.SYNTAX_ERROR: [
                {
                    "check": "syntax_check_before_execution",
                    "description": "执行前进行语法检查",
                    "trigger": "before code execution"
                }
            ],
            ErrorType.IMPORT_ERROR: [
                {
                    "check": "verify_imports",
                    "description": "验证所有导入语句",
                    "trigger": "before execution"
                }
            ],
            ErrorType.FILE_NOT_FOUND: [
                {
                    "check": "verify_file_existence",
                    "description": "检查文件是否存在",
                    "trigger": "before file operations"
                }
            ],
            ErrorType.PERMISSION_ERROR: [
                {
                    "check": "check_permissions",
                    "description": "检查文件权限",
                    "trigger": "before file operations"
                }
            ]
        }

        if error_type in preventive_templates:
            checks.extend(preventive_templates[error_type])

        return checks

    def _determine_error_module(self,
                               root_cause_ids: List[str],
                               error_type: ErrorType,
                               action_type: str) -> ErrorModule:
        """确定错误模块"""
        # 基于错误类型和action类型判断
        if error_type in [ErrorType.SYNTAX_ERROR, ErrorType.LOGIC_ERROR]:
            return ErrorModule.PLANNING
        elif error_type in [ErrorType.IMPORT_ERROR, ErrorType.FILE_NOT_FOUND, ErrorType.PERMISSION_ERROR]:
            return ErrorModule.ACTION
        elif error_type in [ErrorType.TEST_FAILURE, ErrorType.ASSERTION_FAILED]:
            return ErrorModule.SYSTEM
        else:
            return ErrorModule.UNKNOWN

    def _calculate_confidence(self,
                            root_cause_ids: List[str],
                            error_type: ErrorType) -> float:
        """计算置信度"""
        if not root_cause_ids:
            return 0.0

        # 基础置信度
        confidence = 0.5

        # 根因数量越多，置信度越低（可能分析不精确）
        if len(root_cause_ids) == 1:
            confidence += 0.2
        elif len(root_cause_ids) > 2:
            confidence -= 0.1

        # 错误类型明确性
        if error_type != ErrorType.UNKNOWN:
            confidence += 0.2

        return min(max(confidence, 0.0), 1.0)

    def _combine_analysis_results(self,
                                 analysis_results: List[Dict[str, Any]],
                                 task_id: str) -> Dict[str, Any]:
        """合并多个分析结果"""
        if not analysis_results:
            return {
                "task_id": task_id,
                "has_failures": False,
                "root_cause_nodes": [],
                "propagation_chains": [],
                "corrective_actions": [],
                "confidence": 0.0
            }

        # 合并所有根因节点
        all_root_causes = []
        for result in analysis_results:
            all_root_causes.extend(result.get("root_cause_nodes", []))

        # 去重
        unique_root_causes = list(set(all_root_causes))

        # 合并纠正动作
        all_corrective_actions = []
        for result in analysis_results:
            all_corrective_actions.extend(result.get("corrective_actions", []))

        # 合并传播链
        all_propagation_chains = [result.get("propagation_chain", []) for result in analysis_results]

        # 计算平均置信度
        confidences = [result.get("confidence", 0.0) for result in analysis_results]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # 确定主要错误类型
        error_types = [result.get("error_type", "unknown") for result in analysis_results]
        from collections import Counter
        most_common_error = Counter(error_types).most_common(1)
        primary_error_type = most_common_error[0][0] if most_common_error else "unknown"

        return {
            "task_id": task_id,
            "has_failures": True,
            "primary_error_type": primary_error_type,
            "root_cause_nodes": unique_root_causes,
            "propagation_chains": all_propagation_chains,
            "corrective_actions": all_corrective_actions[:5],  # 限制数量
            "confidence": avg_confidence,
            "num_failures_analyzed": len(analysis_results),
            "analysis_timestamp": datetime.now().isoformat()
        }