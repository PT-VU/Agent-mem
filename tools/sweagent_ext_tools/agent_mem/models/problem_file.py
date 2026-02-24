"""
ProblemFile数据模型

基于Agent-mem架构文档第3.1节：
每个action封装为一个ProblemFile，并写入事实图节点。
"""

from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Union, Any, Tuple
from datetime import datetime
from uuid import uuid4


class ActionType(Enum):
    """Action类型枚举"""
    TOOL_CALL = "tool_call"
    CODE_EDIT = "code_edit"
    RUN_TEST = "run_test"
    GUI_CLICK = "gui_click"
    GUI_TYPE = "gui_type"
    WEB_NAV = "web_nav"


class Outcome(Enum):
    """执行结果枚举"""
    SUCCESS = "success"
    FAIL = "fail"
    UNKNOWN = "unknown"


class EdgeType(Enum):
    """图边类型枚举"""
    SUCCESS_NEXT = "success_next"  # 成功推进流程的主链
    FAIL_RETRY = "fail_retry"      # 失败重试链


class EvidencePointer:
    """证据指针，指向可追溯的证据"""

    def __init__(self,
                 evidence_type: str,
                 location: str,
                 content_hash: Optional[str] = None):
        self.evidence_type = evidence_type  # stdout, stderr, diff, etc.
        self.location = location            # 文件路径或存储位置
        self.content_hash = content_hash    # 内容哈希用于验证

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "location": self.location,
            "content_hash": self.content_hash
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidencePointer":
        return cls(
            evidence_type=data["evidence_type"],
            location=data["location"],
            content_hash=data.get("content_hash")
        )


@dataclass
class ProblemFile:
    """
    Action级经验原子，对应架构文档3.1节
    每个action封装为一个ProblemFile，并写入事实图节点
    """

    # 基础标识
    action_id: str = field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    # Action信息
    action_type: ActionType = ActionType.TOOL_CALL
    intent_text: str = ""  # 执行者意图层：本步目的/策略角色
    inputs: Dict[str, Any] = field(default_factory=dict)  # 参数、prompt片段摘要、所需上下文摘要
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # 命令/工具调用、参数

    # 证据指针
    stdout_ref: Optional[EvidencePointer] = None
    stderr_ref: Optional[EvidencePointer] = None
    exception_stack_ref: Optional[EvidencePointer] = None
    diff_summary_ref: Optional[EvidencePointer] = None
    tests_ref: Optional[EvidencePointer] = None
    ui_state_ref: Optional[EvidencePointer] = None

    # 环境与结果
    touched_files: List[str] = field(default_factory=list)
    outcome: Outcome = Outcome.UNKNOWN
    failure_signature: Optional[Dict[str, Any]] = None  # 归一化错误签名
    env_signature: Optional[Dict[str, Any]] = None      # 环境签名

    # 检索支持
    embeddings: Dict[str, List[float]] = field(default_factory=dict)  # 多视角embedding

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，便于序列化"""
        result = {
            "action_id": self.action_id,
            "task_id": self.task_id,
            "timestamp": self.timestamp.isoformat(),
            "action_type": self.action_type.value,
            "intent_text": self.intent_text,
            "inputs": self.inputs,
            "tool_calls": self.tool_calls,
            "touched_files": self.touched_files,
            "outcome": self.outcome.value,
            "embeddings": self.embeddings
        }

        # 添加证据指针
        for field_name, pointer in [
            ("stdout_ref", self.stdout_ref),
            ("stderr_ref", self.stderr_ref),
            ("exception_stack_ref", self.exception_stack_ref),
            ("diff_summary_ref", self.diff_summary_ref),
            ("tests_ref", self.tests_ref),
            ("ui_state_ref", self.ui_state_ref)
        ]:
            if pointer:
                result[field_name] = pointer.to_dict()

        # 添加可选字段
        if self.failure_signature:
            result["failure_signature"] = self.failure_signature
        if self.env_signature:
            result["env_signature"] = self.env_signature

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProblemFile":
        """从字典创建ProblemFile"""
        # 处理证据指针
        evidence_fields = {}
        for field_name in ["stdout_ref", "stderr_ref", "exception_stack_ref",
                          "diff_summary_ref", "tests_ref", "ui_state_ref"]:
            if field_name in data and data[field_name]:
                evidence_fields[field_name] = EvidencePointer.from_dict(data[field_name])

        return cls(
            action_id=data.get("action_id", str(uuid4())),
            task_id=data.get("task_id", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            action_type=ActionType(data.get("action_type", "tool_call")),
            intent_text=data.get("intent_text", ""),
            inputs=data.get("inputs", {}),
            tool_calls=data.get("tool_calls", []),
            touched_files=data.get("touched_files", []),
            outcome=Outcome(data.get("outcome", "unknown")),
            failure_signature=data.get("failure_signature"),
            env_signature=data.get("env_signature"),
            embeddings=data.get("embeddings", {}),
            **evidence_fields
        )


@dataclass
class KGGraphEdge:
    """Knowledge Graph边"""
    source_id: str
    target_id: str
    edge_type: EdgeType
    metadata: Dict[str, Any] = field(default_factory=dict)