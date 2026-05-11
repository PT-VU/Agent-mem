"""
Agent-mem核心数据类型定义

基于Agent-mem架构文档第3节和模块接口定义文档。
此文件包含基础枚举类型定义，具体数据模型在models模块中。
"""

from enum import Enum


class ActionType(str, Enum):
    """Action类型枚举"""

    TOOL_CALL = "tool_call"
    CODE_EDIT = "code_edit"
    RUN_TEST = "run_test"
    GUI_CLICK = "gui_click"
    GUI_TYPE = "gui_type"
    WEB_NAV = "web_nav"


class Outcome(str, Enum):
    """执行结果枚举"""

    SUCCESS = "success"
    FAIL = "fail"
    UNKNOWN = "unknown"


class EdgeType(str, Enum):
    """图边类型枚举"""

    SUCCESS_NEXT = "success_next"  # 成功推进流程的主链
    FAIL_RETRY = "fail_retry"  # 失败重试链


class GovernanceState(str, Enum):
    """Governance 生命周期状态。"""

    CANDIDATE = "candidate"
    PROMOTED = "promoted"
    SUPPRESSED = "suppressed"
    DEPRECATED = "deprecated"


class EvidenceLevel(str, Enum):
    """证据层级。"""

    LOCAL = "local"
    ATTEMPT = "attempt"
    OFFICIAL = "official"


class SubtaskRelationType(str, Enum):
    """Subtask candidate 之间允许的边类型。"""

    PRECEDES = "PRECEDES"
    RETRY_OF = "RETRY_OF"
    ALTERNATIVE_TO = "ALTERNATIVE_TO"


class SubtaskState(str, Enum):
    """SubtaskInstance 状态机最小集合。"""

    PROJECTED_CANDIDATE = "projected_candidate"
    LOCALLY_SUPPORTED = "locally_supported"
    LOCALLY_FAILED = "locally_failed"
    EVAL_CONTEXT_ATTACHED = "eval_context_attached"
    DEPRECATED = "deprecated"


class SubtaskEdgeState(str, Enum):
    """SubtaskEdge 状态机最小集合。"""

    CANDIDATE = "candidate"
    SUPPORTED_CANDIDATE = "supported_candidate"
    SUPPRESSED = "suppressed"
    DEPRECATED = "deprecated"


class CompilerCardType(str, Enum):
    """Compiler 输出白名单。"""

    PLAN_HINT = "PlanHintCard"
    SUCCESS_PATH = "SuccessPathCard"
    BUG_INVARIANT = "BugInvariantCard"
    BUG_ANTI_PATTERN = "BugAntiPatternCard"  # 阶段9-v2 新增：失败侧对称卡
    SUBTASK_RISK = "SubtaskRiskCard"
    RETRY_HINT = "RetryHintCard"
    TIMEOUT_GOVERNANCE = "TimeoutGovernanceCard"
    CLOSURE_GUARD = "ClosureGuardCard"
