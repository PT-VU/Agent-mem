# Agent-mem代码框架设计文档

## 1. 设计目标与原则

### 1.1 核心目标
构建一个training-free的工作经验记忆模块，为SWE/GUI Agent提供可检索、可结构化、可验证的长期记忆能力。

### 1.2 设计原则
1. **可插拔性**：通过对SWEAgent进行最小改造即可接入系统
2. **模块化**：清晰的模块划分和接口定义
3. **可扩展性**：支持未来功能扩展和模块替换
4. **可维护性**：代码结构清晰，易于理解和维护
5. **学术合规**：符合论文研究要求，支持实验和评估

## 2. 整体架构

### 2.1 系统分层
```
┌─────────────────────────────────────────────────────────┐
│                    SWE/GUI Agent                         │
├─────────────────────────────────────────────────────────┤
│              Agent-mem 集成层 (最小改造)                 │
├─────────────────────────────────────────────────────────┤
│              Agent-mem 核心服务层                        │
│  ┌─────────┬─────────┬─────────┬─────────┬─────────┐    │
│  │ Memory  │ 存储    │ 检索    │ 处理    │ 编译    │    │
│  │ Agent   │ 系统    │ 系统    │ 链路    │ 系统    │    │
│  └─────────┴─────────┴─────────┴─────────┴─────────┘    │
├─────────────────────────────────────────────────────────┤
│              Agent-mem 数据存储层                        │
│  ┌─────────┬─────────┬─────────┬─────────┬─────────┐    │
│  │ 事实图  │ 信念图  │ 向量    │ 证据    │ 元数据  │    │
│  │ (KG)    │ (BG)    │ 存储    │ 存储    │ 存储    │    │
│  └─────────┴─────────┴─────────┴─────────┴─────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 2.2 核心模块划分

#### 2.2.1 在线模块（执行时）
1. **ActionLogger**：生成Problem File和证据指针
2. **KGWriter**：写入事实图节点/边和多视角embedding
3. **Retriever**：分层检索（task/action级别，多视角）
4. **MemoryAgentService**：提供query rewrite / subgraph select / distill服务
5. **Injector**：planning/execution经验注入器
6. **Validator**：约束/偏好检查（fail-fast）

#### 2.2.2 异步模块（任务结束后）
1. **RCAAgent**：最小根因集合 + 传播链分析
2. **PrunerDistiller**：生成skeleton subgraph
3. **BeliefUpdater**：生成/更新attempt & atomic beliefs + 统计
4. **Compiler**：belief → preferences/constraints编译
5. **ForgettingManager**：子图级遗忘/归档
6. **SkillPromoter**：经验固化为skill文档

## 3. 模块详细设计

### 3.1 集成层设计

#### 3.1.1 SWEAgent集成方案
```python
# 最小改造点：
# 1. 扩展hook接口：on_action_logged, on_planning_start, on_execution_error
# 2. 添加MemoryAgentHook，将事件转发给Agent-mem服务
# 3. 通过环境变量或配置文件启用/禁用Agent-mem
```

#### 3.1.2 集成接口定义
```python
class AgentMemIntegration:
    """Agent-mem与SWEAgent的集成接口"""

    def log_action(self, action_data: ProblemFile) -> str:
        """记录action到Agent-mem，返回action_id"""

    def retrieve_planning_tips(self, task_context: TaskContext) -> PlanningTips:
        """检索规划阶段经验"""

    def retrieve_fix_suggestions(self, error_context: ErrorContext) -> FixSuggestions:
        """检索执行阶段修复建议"""

    def validate_action(self, action: Action, context: Context) -> ValidationResult:
        """验证action是否符合约束"""
```

### 3.2 数据模型设计

#### 3.2.1 Problem File Schema
```python
@dataclass
class ProblemFile:
    action_id: str  # 全局唯一
    task_id: str    # 本次任务唯一
    timestamp: datetime
    action_type: ActionType  # tool_call / code_edit / run_test / ...
    intent_text: str  # 执行者意图层
    inputs: dict  # 参数、prompt片段摘要、所需上下文摘要
    tool_calls: list  # 命令/工具调用、参数
    stdout_ref: str  # 证据坐标
    stderr_ref: str  # 证据坐标
    exception_stack_ref: str  # 证据坐标
    touched_files: list  # 文件集合
    diff_summary_ref: str  # 证据坐标
    tests_ref: str  # 测试输出证据
    ui_state_ref: str  # GUI：截图/可访问树/元素树坐标
    outcome: Outcome  # success / fail / unknown
    failure_signature: FailureSignature  # 归一化错误签名
    env_signature: EnvSignature  # 环境签名
    evidence_index: list  # 所有可追溯证据坐标集合
    embeddings: dict  # 多视角embedding
    epistemic_tags: dict  # 字段标注为EVIDENCE/INFERENCE
```

#### 3.2.2 事实图（Observation KG）
```python
@dataclass
class ObservationKG:
    nodes: Dict[str, ProblemFile]  # action_id -> ProblemFile
    edges: Dict[str, List[Edge]]   # action_id -> [Edge]

@dataclass
class Edge:
    source: str  # source action_id
    target: str  # target action_id
    edge_type: EdgeType  # success_next / fail_retry / ...
    weight: float  # 边权重
```

#### 3.2.3 信念图（Belief Graph）
```python
@dataclass
class AtomicBelief:
    belief_id: str
    type: BeliefType  # workflow / pitfall / env_adaptation
    condition_signature: ConditionSignature
    rule: Rule
    stats: BeliefStats
    confidence: float
    evidence_refs: list  # 指向事实图节点/证据坐标
    attribution_refs: list  # RCA输出引用
    status: BeliefStatus  # active / deprecated / promoted_to_preference / promoted_to_constraint
    last_updated: datetime

@dataclass
class AttemptBelief:
    attempt_id: str
    task_summary: str
    failure_causal_chain: list
    key_turning_points: list
    attribution_results: list
    reusable_workflow_points: list
    evidence_refs: list
```

### 3.3 存储系统设计

#### 3.3.1 存储架构
```
存储系统
├── 图数据库 (Neo4j/NetworkX) - 存储事实图和信念图结构
├── 向量数据库 (FAISS/Chroma) - 存储多视角embedding
├── 对象存储 (本地文件/S3) - 存储证据文件（stdout/stderr/diff等）
└── 元数据存储 (SQLite/PostgreSQL) - 存储统计信息和索引
```

#### 3.3.2 存储接口
```python
class StorageSystem:
    """统一的存储系统接口"""

    def save_problem_file(self, pf: ProblemFile) -> str:
        """保存Problem File"""

    def save_kg_edge(self, edge: Edge) -> None:
        """保存KG边"""

    def save_embedding(self, action_id: str, embeddings: dict) -> None:
        """保存多视角embedding"""

    def save_belief(self, belief: Union[AtomicBelief, AttemptBelief]) -> None:
        """保存信念"""

    def query_similar_actions(self, query: Query, k: int = 10) -> List[SimilarAction]:
        """查询相似action"""

    def query_task_level_experience(self, task_context: TaskContext) -> List[TaskExperience]:
        """查询任务级经验"""
```

### 3.4 检索系统设计

#### 3.4.1 多视角Embedding体系
```python
class MultiViewEmbedder:
    """多视角embedding生成器"""

    def embed_task_semantics(self, task_description: str) -> np.ndarray:
        """任务语义embedding"""

    def embed_file_scope(self, file_paths: List[str]) -> np.ndarray:
        """文件范围embedding"""

    def embed_error_signature(self, error_text: str) -> np.ndarray:
        """错误签名embedding"""

    def embed_tool_output(self, output_text: str) -> np.ndarray:
        """工具输出embedding"""

    def embed_intent(self, intent_text: str) -> np.ndarray:
        """意图embedding"""

    def embed_ui_state(self, ui_state: UIState) -> np.ndarray:
        """UI状态embedding（GUI专用）"""
```

#### 3.4.2 分层检索器
```python
class HierarchicalRetriever:
    """分层检索器"""

    def retrieve_task_level(self, query: TaskQuery) -> List[TaskExperience]:
        """任务级检索：返回相似任务的成功骨架"""

    def retrieve_action_level(self, query: ActionQuery) -> List[ActionExperience]:
        """action级检索：返回相似失败-修复模式"""

    def retrieve_by_error_signature(self, error_sig: str) -> List[FixPattern]:
        """按错误签名检索修复模式"""

    def retrieve_by_intent(self, intent: str) -> List[WorkflowPattern]:
        """按意图检索工作流模式"""
```

### 3.5 处理链路设计

#### 3.5.1 RCA Agent（根因分析）
```python
class RCAAgent:
    """根因分析Agent"""

    def analyze_failure(self, task_subgraph: ObservationKG) -> RCAResult:
        """分析失败任务的根因"""

    @dataclass
    class RCAResult:
        root_cause_nodes: list  # 最小根因集合
        propagation_chain: list  # 根因→失败终点的传播链
        error_module: ErrorModule  # memory/reflection/planning/action/system
        error_type: str  # 可扩展细分类
        corrective_actions: list  # 修复动作模板
        preventive_checks: list  # 规划阶段应插入的检查
        confidence: float
        evidence_refs: list
```

#### 3.5.2 剪枝提炼器
```python
class PrunerDistiller:
    """剪枝提炼器"""

    def distill_success_skeleton(self, task_subgraph: ObservationKG) -> SuccessSkeleton:
        """提取成功骨架"""

    def distill_failure_repair(self, task_subgraph: ObservationKG) -> FailureRepairPattern:
        """提取失败修复模式"""

    def generate_task_summary(self, task_subgraph: ObservationKG) -> str:
        """生成任务摘要"""
```

#### 3.5.3 信念更新器
```python
class BeliefUpdater:
    """信念更新器"""

    def update_atomic_beliefs(self, rca_results: List[RCAResult]) -> List[AtomicBelief]:
        """根据RCA结果更新原子信念"""

    def update_attempt_beliefs(self, task_subgraph: ObservationKG) -> AttemptBelief:
        """更新任务尝试信念"""

    def compute_belief_stats(self, belief: AtomicBelief) -> BeliefStats:
        """计算信念统计量"""

    def promote_belief_status(self, belief: AtomicBelief) -> None:
        """提升信念状态（active→preference→constraint）"""
```

### 3.6 编译系统设计

#### 3.6.1 PDDL3编译器
```python
class PDDL3Compiler:
    """PDDL3编译器"""

    def compile_preference(self, belief: AtomicBelief) -> PDDL3Preference:
        """编译为PDDL3偏好"""

    def compile_constraint(self, belief: AtomicBelief) -> PDDL3Constraint:
        """编译为PDDL3约束"""

    def generate_validator(self, constraints: List[PDDL3Constraint]) -> Validator:
        """生成validator"""
```

#### 3.6.2 Validator
```python
class Validator:
    """约束验证器"""

    def validate_action(self, action: Action, constraints: List[PDDL3Constraint]) -> ValidationResult:
        """验证单个action"""

    def validate_plan(self, plan: List[Action], constraints: List[PDDL3Constraint]) -> ValidationResult:
        """验证计划"""

    @dataclass
    class ValidationResult:
        is_valid: bool
        violations: List[Violation]
        suggestions: List[Suggestion]
```

### 3.7 Memory Agent服务设计

#### 3.7.1 Memory Agent核心服务
```python
class MemoryAgentService:
    """Memory Agent核心服务"""

    def rewrite_query(self, natural_query: str, context: Context) -> StructuredQuery:
        """Query Rewriting：将自然语言查询改写成结构化查询"""

    def select_subgraph(self, query: StructuredQuery) -> SelectedSubgraph:
        """Subgraph Selection：从KG中选择最有用的经验子图"""

    def distill_experience(self, subgraph: SelectedSubgraph) -> DistilledExperience:
        """Experience Distillation：压缩为可执行建议"""

    def reference_evidence(self, experience: DistilledExperience) -> EvidenceReferences:
        """Evidence Referencing：返回证据坐标"""

    def update_beliefs(self, new_evidence: Evidence) -> BeliefUpdates:
        """Belief Update：异步更新信念统计与状态"""
```

## 4. 接口定义

### 4.1 外部接口（供SWEAgent调用）
```python
# agent_mem/client.py
class AgentMemClient:
    """Agent-mem客户端接口"""

    def __init__(self, config: AgentMemConfig):
        self.config = config
        self.service = MemoryAgentService(config)

    def log_action(self, action_data: dict) -> str:
        """记录action"""

    def get_planning_tips(self, task_description: str, context: dict) -> dict:
        """获取规划建议"""

    def get_fix_suggestions(self, error_info: dict, context: dict) -> dict:
        """获取修复建议"""

    def validate_plan(self, plan: list, context: dict) -> dict:
        """验证计划"""
```

### 4.2 内部接口（模块间通信）
```python
# agent_mem/types.py
@dataclass
class Query:
    """检索查询"""
    text: str
    embedding_type: EmbeddingType
    filters: dict

@dataclass
class Experience:
    """经验数据"""
    id: str
    type: ExperienceType
    content: dict
    embeddings: dict
    evidence_refs: list

@dataclass
class Recommendation:
    """推荐结果"""
    recommendations: list
    evidence_refs: list
    confidence: float
    assumptions: list
```

## 5. 配置系统

### 5.1 配置文件结构
```yaml
# config/agent_mem.yaml
agent_mem:
  enabled: true
  mode: "online"  # online, offline, hybrid

  storage:
    kg_backend: "networkx"  # networkx, neo4j
    vector_backend: "faiss"  # faiss, chroma
    evidence_backend: "local"  # local, s3
    metadata_backend: "sqlite"  # sqlite, postgresql

  retrieval:
    task_level_k: 5
    action_level_k: 10
    embedding_models:
      task_sem: "all-MiniLM-L6-v2"
      file_scope: "all-MiniLM-L6-v2"
      error_sig: "all-MiniLM-L6-v2"

  processing:
    rca_enabled: true
    pruning_enabled: true
    belief_update_interval: "1h"

  compilation:
    pddl3_enabled: false  # MVP阶段禁用
    validator_enabled: false

  integration:
    sweagent_hook_class: "agent_mem.integration.SWEAgentMemoryHook"
    gui_agent_hook_class: "agent_mem.integration.GUIAgentMemoryHook"
```

### 5.2 环境变量
```bash
# 启用Agent-mem
export AGENT_MEM_ENABLED=true

# 存储配置
export AGENT_MEM_STORAGE_PATH=/path/to/storage

# 检索配置
export AGENT_MEM_RETRIEVAL_K=10

# 集成配置
export SWE_AGENT_EXTERNAL_HOOK_CLASS="agent_mem.integration.SWEAgentMemoryHook"
```

## 6. 部署架构

### 6.1 部署模式
1. **嵌入式模式**：Agent-mem作为库直接集成到Agent中
2. **服务模式**：Agent-mem作为独立服务，通过gRPC/REST调用
3. **混合模式**：轻量级组件嵌入式，重型组件服务化

### 6.2 MVP推荐部署
```
SWEAgent进程
├── Agent-mem轻量客户端
│   ├── ActionLogger（嵌入式）
│   ├── MemoryAgentHook（嵌入式）
│   └── 本地缓存
└── Agent-mem服务进程（可选）
    ├── 存储系统
    ├── 检索系统
    ├── 处理链路
    └── 编译系统
```

## 7. 实施路线图

### 7.1 阶段一：MVP（最小可行产品）
1. **基础数据结构**：实现ProblemFile、ObservationKG基础结构
2. **简单存储**：使用NetworkX + FAISS + 本地文件存储
3. **基础检索**：实现单视角embedding和简单检索
4. **执行时修复**：实现fail_retry模式检索和修复建议
5. **异步RCA**：实现基础根因分析

### 7.2 阶段二：功能完善
1. **多视角embedding**：实现完整的多视角embedding体系
2. **分层检索**：实现task/action分层检索
3. **信念系统**：实现完整的信念图系统
4. **规划时注入**：实现planning-time经验注入
5. **统计系统**：实现信念统计和状态提升

### 7.3 阶段三：高级功能
1. **PDDL3编译**：实现PDDL3约束/偏好编译
2. **Validator**：实现fail-fast验证器
3. **技能固化**：实现经验固化为skill文档
4. **遗忘机制**：实现子图级遗忘策略
5. **冲突消解**：实现信念冲突检测和消解

### 7.4 阶段四：优化扩展
1. **性能优化**：优化检索和存储性能
2. **可扩展性**：支持分布式部署
3. **多模态支持**：完善GUI多模态支持
4. **评估系统**：集成完整评估指标
5. **生产就绪**：完善监控、日志、错误处理

## 8. 与现有代码的集成

### 8.1 利用现有基础
1. **复用bridge_hook机制**：扩展现有hook系统
2. **复用dispatcher架构**：作为事件分发基础
3. **复用配置系统**：扩展环境变量配置

### 8.2 增量开发策略
1. **逐步替换**：逐步用Agent-mem组件替换现有tool_a/tool_b
2. **向后兼容**：保持现有接口兼容性
3. **平滑迁移**：支持配置开关切换新旧系统

## 9. 测试策略

### 9.1 单元测试
- 各模块接口测试
- 数据结构序列化/反序列化测试
- 检索算法正确性测试

### 9.2 集成测试
- 端到端经验记录和检索测试
- SWEAgent集成测试
- 存储系统集成测试

### 9.3 性能测试
- 检索延迟测试
- 存储容量测试
- 并发性能测试

### 9.4 评估测试
- 检索准确率评估
- 修复成功率评估
- 规划改进效果评估

## 10. 风险与缓解

### 10.1 技术风险
1. **性能风险**：复杂检索可能影响Agent响应时间
   - 缓解：异步处理、缓存、性能优化

2. **存储风险**：经验数据可能快速增长
   - 缓解：压缩、归档、遗忘策略

3. **集成风险**：与SWEAgent集成可能引入不稳定因素
   - 缓解：最小化改造、充分测试、回滚机制

### 10.2 学术风险
1. **评估风险**：难以准确评估系统效果
   - 缓解：设计严谨的评估指标和实验方案

2. **复现风险**：系统复杂导致难以复现结果
   - 缓解：详细文档、可配置参数、开源代码

## 11. 后续工作

### 11.1 立即行动
1. 细化各模块接口定义
2. 创建详细实施计划
3. 开始MVP阶段开发

### 11.2 长期规划
1. 论文实验设计
2. 大规模评估
3. 社区推广和开源

---

**设计者**：代码工程师Agent
**日期**：2026-02-16
**版本**：1.0