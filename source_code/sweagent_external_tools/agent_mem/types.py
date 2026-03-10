"""
Agent-mem核心数据类型定义

基于Agent-mem架构文档第3节和模块接口定义文档。
此文件包含基础枚举类型定义，具体数据模型在models模块中。
"""

from enum import Enum


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