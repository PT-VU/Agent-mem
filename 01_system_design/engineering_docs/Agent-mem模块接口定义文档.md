# Agent-mem模块接口定义文档

## 1. 概述

本文档定义Agent-mem系统中各模块的详细接口，包括类定义、方法签名、参数类型和返回值。所有接口都使用Python类型注解，遵循PEP 484规范。

## 2. 核心数据类型

### 2.1 基础类型
```python
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Union, Any
from datetime import datetime
import numpy as np

class ActionType(Enum):
    TOOL_CALL = "tool_call"
    CODE_EDIT = "code_edit"
    RUN_TEST = "run_test"
    GUI_CLICK = "gui_click"
    GUI_TYPE = "gui_type"
    WEB_NAV = "web_nav"

class Outcome(Enum):
    SUCCESS = "success"
    FAIL = "fail"
    UNKNOWN = "unknown"

class EdgeType(Enum):
    SUCCESS_NEXT = "success_next"
    FAIL_RETRY = "fail_retry"
    DEPENDS_ON = "depends_on"
    ALTERNATIVES = "alternatives"

class BeliefType(Enum):
    WORKFLOW = "workflow"
    PITFALL = "pitfall"
    ENV_ADAPTATION = "env_adaptation"

class BeliefStatus(Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    PROMOTED_TO_PREFERENCE = "promoted_to_preference"
    PROMOTED_TO_CONSTRAINT = "promoted_to_constraint"

class EmbeddingType(Enum):
    TASK_SEM = "task_sem"
    FILE_SCOPE = "file_scope"
    ERROR_SIG = "error_sig"
    TOOL_OUTPUT = "tool_output"
    INTENT = "intent"
    UI_STATE = "ui_state"
```

### 2.2 Problem File数据结构
```python
@dataclass
class FailureSignature:
    """归一化错误签名"""
    error_type_cluster: str
    key_tokens: List[str]
    pattern_hash: str

@dataclass
class EnvSignature:
    """环境签名"""
    toolchain_version: str
    env_vars: Dict[str, str]
    path_hash: str
    container_info: Optional[Dict[str, Any]]
    proxy_info: Optional[Dict[str, Any]]

@dataclass
class ProblemFile:
    """Action级经验原子"""
    action_id: str  # 全局唯一
    task_id: str    # 本次任务唯一
    timestamp: datetime
    action_type: ActionType
    intent_text: str  # 执行者意图层
    inputs: Dict[str, Any]  # 参数、prompt片段摘要、所需上下文摘要
    tool_calls: List[Dict[str, Any]]  # 命令/工具调用、参数
    stdout_ref: str  # 证据坐标
    stderr_ref: str  # 证据坐标
    exception_stack_ref: str  # 证据坐标
    touched_files: List[str]  # 文件集合
    diff_summary_ref: str  # 证据坐标
    tests_ref: str  # 测试输出证据
    ui_state_ref: str  # GUI：截图/可访问树/元素树坐标
    outcome: Outcome
    failure_signature: Optional[FailureSignature]
    env_signature: EnvSignature
    evidence_index: List[str]  # 所有可追溯证据坐标集合
    embeddings: Dict[EmbeddingType, np.ndarray]  # 多视角embedding
    epistemic_tags: Dict[str, str]  # 字段标注为EVIDENCE/INFERENCE
```

### 2.3 图数据结构
```python
@dataclass
class Edge:
    """KG边"""
    source: str  # source action_id
    target: str  # target action_id
    edge_type: EdgeType
    weight: float = 1.0
    metadata: Dict[str, Any] = None

@dataclass
class ObservationKG:
    """事实图"""
    task_id: str
    nodes: Dict[str, ProblemFile]  # action_id -> ProblemFile
    edges: Dict[str, List[Edge]]   # source_action_id -> [Edge]

    def add_node(self, pf: ProblemFile) -> None:
        """添加节点"""

    def add_edge(self, edge: Edge) -> None:
        """添加边"""

    def get_subgraph(self, node_ids: List[str]) -> "ObservationKG":
        """获取子图"""
```

### 2.4 信念数据结构
```python
@dataclass
class ConditionSignature:
    """条件签名"""
    env_cluster: str
    repo_toolchain: str
    action_type_pattern: str
    intent_pattern: str
    file_scope_pattern: str
    error_signature: Optional[str]

@dataclass
class Rule:
    """规则"""
    trigger: str  # WHEN/IF
    recommend: List[str]  # DO（插入动作、参数模板、验证步骤）
    avoid: List[str]  # NOT DO（禁止动作、互斥动作）
    redundant: List[str]  # DO-NOT-REPEAT（有一个就不必做另一个）

@dataclass
class BeliefStats:
    """信念统计"""
    support_n: int
    success_with: int
    success_without: int
    uplift: float
    uncertainty: float  # CI或Bayesian posterior
    recent_window_metrics: Dict[str, float]

@dataclass
class AtomicBelief:
    """原子信念"""
    belief_id: str
    type: BeliefType
    condition_signature: ConditionSignature
    rule: Rule
    stats: BeliefStats
    confidence: float
    evidence_refs: List[str]  # 指向事实图节点/证据坐标
    attribution_refs: List[str]  # RCA输出引用
    status: BeliefStatus
    last_updated: datetime

@dataclass
class AttemptBelief:
    """任务尝试信念"""
    attempt_id: str
    task_summary: str
    failure_causal_chain: List[str]
    key_turning_points: List[str]
    attribution_results: List[Dict[str, Any]]
    reusable_workflow_points: List[str]
    evidence_refs: List[str]
```

## 3. 存储系统接口

### 3.1 存储系统抽象接口
```python
class StorageSystem(ABC):
    """存储系统抽象接口"""

    @abstractmethod
    def save_problem_file(self, pf: ProblemFile) -> str:
        """保存Problem File，返回存储ID"""

    @abstractmethod
    def load_problem_file(self, action_id: str) -> Optional[ProblemFile]:
        """加载Problem File"""

    @abstractmethod
    def save_kg_edge(self, task_id: str, edge: Edge) -> None:
        """保存KG边"""

    @abstractmethod
    def load_task_kg(self, task_id: str) -> Optional[ObservationKG]:
        """加载任务KG"""

    @abstractmethod
    def save_embedding(self, action_id: str, embedding_type: EmbeddingType, vector: np.ndarray) -> None:
        """保存embedding"""

    @abstractmethod
    def load_embedding(self, action_id: str, embedding_type: EmbeddingType) -> Optional[np.ndarray]:
        """加载embedding"""

    @abstractmethod
    def save_atomic_belief(self, belief: AtomicBelief) -> None:
        """保存原子信念"""

    @abstractmethod
    def load_atomic_belief(self, belief_id: str) -> Optional[AtomicBelief]:
        """加载原子信念"""

    @abstractmethod
    def save_attempt_belief(self, belief: AttemptBelief) -> None:
        """保存任务尝试信念"""

    @abstractmethod
    def load_attempt_belief(self, attempt_id: str) -> Optional[AttemptBelief]:
        """加载任务尝试信念"""
```

### 3.2 向量检索接口
```python
class VectorRetrievalSystem(ABC):
    """向量检索系统接口"""

    @abstractmethod
    def index_embedding(self, action_id: str, embedding_type: EmbeddingType, vector: np.ndarray) -> None:
        """索引embedding"""

    @abstractmethod
    def search_similar(self, query_vector: np.ndarray, embedding_type: EmbeddingType,
                      k: int = 10, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """搜索相似向量，返回[{"action_id": str, "score": float}, ...]"""

    @abstractmethod
    def search_by_multiview(self, query_vectors: Dict[EmbeddingType, np.ndarray],
                           weights: Optional[Dict[EmbeddingType, float]] = None,
                           k: int = 10) -> List[Dict[str, Any]]:
        """多视角搜索"""
```

### 3.3 证据存储接口
```python
class EvidenceStorage(ABC):
    """证据存储接口"""

    @abstractmethod
    def save_evidence(self, evidence_type: str, content: bytes, metadata: Dict[str, Any]) -> str:
        """保存证据，返回证据坐标"""

    @abstractmethod
    def load_evidence(self, evidence_ref: str) -> Optional[bytes]:
        """加载证据"""

    @abstractmethod
    def get_evidence_metadata(self, evidence_ref: str) -> Optional[Dict[str, Any]]:
        """获取证据元数据"""
```

## 4. 处理模块接口

### 4.1 Embedding生成器接口
```python
class EmbeddingGenerator(ABC):
    """Embedding生成器接口"""

    @abstractmethod
    def generate_task_semantics_embedding(self, task_description: str) -> np.ndarray:
        """生成任务语义embedding"""

    @abstractmethod
    def generate_file_scope_embedding(self, file_paths: List[str]) -> np.ndarray:
        """生成文件范围embedding"""

    @abstractmethod
    def generate_error_signature_embedding(self, error_text: str) -> np.ndarray:
        """生成错误签名embedding"""

    @abstractmethod
    def generate_tool_output_embedding(self, output_text: str) -> np.ndarray:
        """生成工具输出embedding"""

    @abstractmethod
    def generate_intent_embedding(self, intent_text: str) -> np.ndarray:
        """生成意图embedding"""

    @abstractmethod
    def generate_ui_state_embedding(self, ui_state: Dict[str, Any]) -> np.ndarray:
        """生成UI状态embedding"""
```

### 4.2 RCA Agent接口
```python
@dataclass
class RCAResult:
    """RCA分析结果"""
    root_cause_nodes: List[str]  # 最小根因集合
    propagation_chain: List[str]  # 根因→失败终点的传播链
    error_module: str  # memory/reflection/planning/action/system
    error_type: str  # 可扩展细分类
    corrective_actions: List[Dict[str, Any]]  # 修复动作模板
    preventive_checks: List[Dict[str, Any]]  # 规划阶段应插入的检查
    confidence: float
    evidence_refs: List[str]

class RCAAgent(ABC):
    """RCA Agent接口"""

    @abstractmethod
    def analyze_failure(self, task_kg: ObservationKG) -> RCAResult:
        """分析失败任务的根因"""

    @abstractmethod
    def analyze_partial_failure(self, partial_kg: ObservationKG, failure_node_id: str) -> RCAResult:
        """分析部分失败（在线分析）"""
```

### 4.3 剪枝提炼器接口
```python
@dataclass
class SuccessSkeleton:
    """成功骨架"""
    key_nodes: List[str]
    essential_edges: List[Edge]
    verification_nodes: List[str]
    distilled_summary: str

@dataclass
class FailureRepairPattern:
    """失败修复模式"""
    failure_node_id: str
    repair_node_id: str
    repair_path: List[str]
    pattern_summary: str
    applicability_conditions: Dict[str, Any]

class PrunerDistiller(ABC):
    """剪枝提炼器接口"""

    @abstractmethod
    def distill_success_skeleton(self, task_kg: ObservationKG) -> SuccessSkeleton:
        """提取成功骨架"""

    @abstractmethod
    def distill_failure_repair_patterns(self, task_kg: ObservationKG) -> List[FailureRepairPattern]:
        """提取失败修复模式"""

    @abstractmethod
    def generate_task_summary(self, task_kg: ObservationKG) -> str:
        """生成任务摘要"""
```

### 4.4 信念更新器接口
```python
class BeliefUpdater(ABC):
    """信念更新器接口"""

    @abstractmethod
    def update_from_rca(self, rca_result: RCAResult) -> List[AtomicBelief]:
        """根据RCA结果更新信念"""

    @abstractmethod
    def update_from_success(self, success_skeleton: SuccessSkeleton) -> List[AtomicBelief]:
        """根据成功骨架更新信念"""

    @abstractmethod
    def compute_belief_stats(self, belief: AtomicBelief, new_evidence: List[str]) -> BeliefStats:
        """计算信念统计量"""

    @abstractmethod
    def evaluate_promotion_criteria(self, belief: AtomicBelief) -> BeliefStatus:
        """评估信念提升条件"""

    @abstractmethod
    def resolve_belief_conflicts(self, beliefs: List[AtomicBelief]) -> List[AtomicBelief]:
        """解决信念冲突"""
```

## 5. 检索系统接口

### 5.1 检索查询类型
```python
@dataclass
class TaskQuery:
    """任务级查询"""
    task_description: str
    env_signature: EnvSignature
    file_scope: List[str]
    toolchain: str
    max_results: int = 5

@dataclass
class ActionQuery:
    """Action级查询"""
    intent_text: str
    action_type: ActionType
    error_signature: Optional[str]
    tool_output: Optional[str]
    env_signature: EnvSignature
    max_results: int = 10

@dataclass
class ErrorQuery:
    """错误查询"""
    error_signature: str
    action_type: ActionType
    env_signature: EnvSignature
    max_results: int = 5
```

### 5.2 检索器接口
```python
@dataclass
class TaskExperience:
    """任务经验"""
    task_id: str
    success_skeleton: SuccessSkeleton
    relevant_beliefs: List[AtomicBelief]
    similarity_score: float
    evidence_refs: List[str]

@dataclass
class ActionExperience:
    """Action经验"""
    action_id: str
    problem_file: ProblemFile
    repair_patterns: List[FailureRepairPattern]
    similarity_score: float
    evidence_refs: List[str]

class Retriever(ABC):
    """检索器接口"""

    @abstractmethod
    def retrieve_task_experience(self, query: TaskQuery) -> List[TaskExperience]:
        """检索任务经验"""

    @abstractmethod
    def retrieve_action_experience(self, query: ActionQuery) -> List[ActionExperience]:
        """检索Action经验"""

    @abstractmethod
    def retrieve_by_error(self, query: ErrorQuery) -> List[ActionExperience]:
        """按错误检索"""

    @abstractmethod
    def retrieve_by_intent(self, intent: str, action_type: ActionType,
                          max_results: int = 10) -> List[ActionExperience]:
        """按意图检索"""
```

## 6. Memory Agent服务接口

### 6.1 服务输入输出类型
```python
@dataclass
class TaskContext:
    """任务上下文"""
    task_description: str
    env_signature: EnvSignature
    current_files: List[str]
    toolchain_info: Dict[str, Any]
    agent_state: Dict[str, Any]

@dataclass
class ErrorContext:
    """错误上下文"""
    error_message: str
    error_type: str
    current_action: Dict[str, Any]
    env_signature: EnvSignature
    agent_state: Dict[str, Any]

@dataclass
class PlanningTips:
    """规划建议"""
    workflow_template: List[Dict[str, Any]]
    preventive_checks: List[Dict[str, Any]]
    env_adaptations: List[Dict[str, Any]]
    evidence_refs: List[str]
    confidence: float
    assumptions: List[str]

@dataclass
class FixSuggestions:
    """修复建议"""
    next_step_fix: Dict[str, Any]
    alternative_fixes: List[Dict[str, Any]]
    expected_outcome: str
    validator_check: Optional[Dict[str, Any]]
    evidence_refs: List[str]
    confidence: float
```

### 6.2 Memory Agent核心接口
```python
class MemoryAgentService(ABC):
    """Memory Agent服务接口"""

    @abstractmethod
    def process_planning_request(self, context: TaskContext) -> PlanningTips:
        """处理规划请求"""

    @abstractmethod
    def process_error_request(self, context: ErrorContext) -> FixSuggestions:
        """处理错误请求"""

    @abstractmethod
    def log_action(self, action_data: Dict[str, Any]) -> str:
        """记录action"""

    @abstractmethod
    def validate_action(self, action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """验证action"""

    @abstractmethod
    def get_evidence(self, evidence_refs: List[str]) -> List[Dict[str, Any]]:
        """获取证据"""
```

## 7. 集成接口

### 7.1 SWEAgent Hook接口
```python
class SWEAgentMemoryHook(ABC):
    """SWEAgent记忆Hook接口"""

    @abstractmethod
    def on_action_logged(self, step: Any, action_data: Dict[str, Any]) -> None:
        """Action记录时调用"""

    @abstractmethod
    def on_planning_start(self, task_description: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """规划开始时调用"""

    @abstractmethod
    def on_execution_error(self, step: Any, error_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """执行错误时调用"""

    @abstractmethod
    def on_task_complete(self, task_result: Dict[str, Any]) -> None:
        """任务完成时调用"""
```

### 7.2 客户端接口
```python
class AgentMemClient:
    """Agent-mem客户端"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.service: Optional[MemoryAgentService] = None

    def connect(self) -> bool:
        """连接服务"""

    def disconnect(self) -> None:
        """断开连接"""

    def is_connected(self) -> bool:
        """检查连接状态"""

    def get_planning_tips(self, task_description: str, context: Dict[str, Any]) -> Optional[PlanningTips]:
        """获取规划建议"""

    def get_fix_suggestions(self, error_info: Dict[str, Any], context: Dict[str, Any]) -> Optional[FixSuggestions]:
        """获取修复建议"""

    def log_action(self, action_data: Dict[str, Any]) -> Optional[str]:
        """记录action"""
```

## 8. 配置接口

### 8.1 配置类
```python
@dataclass
class StorageConfig:
    """存储配置"""
    kg_backend: str = "networkx"  # networkx, neo4j
    vector_backend: str = "faiss"  # faiss, chroma
    evidence_backend: str = "local"  # local, s3
    metadata_backend: str = "sqlite"  # sqlite, postgresql
    storage_path: str = "./agent_mem_data"

@dataclass
class RetrievalConfig:
    """检索配置"""
    task_level_k: int = 5
    action_level_k: int = 10
    embedding_models: Dict[str, str] = None
    retrieval_strategy: str = "hybrid"  # vector_only, graph_only, hybrid

@dataclass
class ProcessingConfig:
    """处理配置"""
    rca_enabled: bool = True
    pruning_enabled: bool = True
    belief_update_enabled: bool = True
    async_processing: bool = True
    processing_interval: str = "1h"

@dataclass
class AgentMemConfig:
    """Agent-mem配置"""
    enabled: bool = True
    mode: str = "embedded"  # embedded, service, hybrid
    storage: StorageConfig = None
    retrieval: RetrievalConfig = None
    processing: ProcessingConfig = None
    log_level: str = "INFO"

    def __post_init__(self):
        if self.storage is None:
            self.storage = StorageConfig()
        if self.retrieval is None:
            self.retrieval = RetrievalConfig()
        if self.processing is None:
            self.processing = ProcessingConfig()
```

## 9. 错误处理接口

### 9.1 错误类型
```python
class AgentMemError(Exception):
    """Agent-mem基础错误"""
    pass

class StorageError(AgentMemError):
    """存储错误"""
    pass

class RetrievalError(AgentMemError):
    """检索错误"""
    pass

class ProcessingError(AgentMemError):
    """处理错误"""
    pass

class ConfigurationError(AgentMemError):
    """配置错误"""
    pass

class IntegrationError(AgentMemError):
    """集成错误"""
    pass
```

### 9.2 错误处理工具
```python
def handle_agent_mem_error(func):
    """Agent-mem错误处理装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AgentMemError as e:
            # 记录错误但不中断主流程
            logger.error(f"Agent-mem error in {func.__name__}: {e}")
            return None
        except Exception as e:
            # 未知错误
            logger.error(f"Unexpected error in {func.__name__}: {e}")
            return None
    return wrapper
```

## 10. 日志接口

### 10.1 日志配置
```python
import logging

def setup_agent_mem_logging(config: AgentMemConfig) -> logging.Logger:
    """设置Agent-mem日志"""
    logger = logging.getLogger("agent_mem")

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(getattr(logging, config.log_level.upper()))
    return logger
```

## 11. 使用示例

### 11.1 初始化示例
```python
# 配置
config = AgentMemConfig(
    enabled=True,
    mode="embedded",
    storage=StorageConfig(
        storage_path="./agent_mem_data"
    ),
    retrieval=RetrievalConfig(
        task_level_k=5,
        action_level_k=10
    )
)

# 初始化客户端
client = AgentMemClient(config)
if client.connect():
    print("Agent-mem connected successfully")
```

### 11.2 使用示例
```python
# 记录action
action_data = {
    "action_type": "code_edit",
    "intent_text": "Fix syntax error in function",
    "inputs": {"file": "src/main.py", "line": 42},
    "outcome": "success"
}
action_id = client.log_action(action_data)

# 获取规划建议
context = {
    "task_description": "Fix bug in authentication module",
    "env_signature": {"python_version": "3.9", "os": "linux"},
    "current_files": ["src/auth.py"]
}
tips = client.get_planning_tips("Fix authentication bug", context)

# 获取修复建议
error_info = {
    "error_message": "SyntaxError: invalid syntax",
    "error_type": "syntax_error",
    "current_action": {"action_type": "code_edit"}
}
fixes = client.get_fix_suggestions(error_info, context)
```

---

**文档版本**: 1.0
**最后更新**: 2026-02-16
**维护者**: 代码工程师Agent