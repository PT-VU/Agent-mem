# Agent-mem: Work-Experience Memory for SWE-agent

## 概述

Agent-mem是一个为SWE-agent设计的工作经验记忆模块，基于训练自由（training-free）的方法，通过记录和分析agent的执行轨迹来提供规划时经验注入和执行时出错回忆功能。

## 核心架构

### 1. Problem File (经验原子)
- **定位**: Action级别的经验原子，包含证据指针和多视角embedding
- **关键字段**: `task_id`, `action_type`, `intent_text`, `outcome`, `failure_signature`, `evidence_index`, `embeddings`
- **证据指针**: 指向stdout/stderr/diff/test_output等原始输出

### 2. Observation KG (事实图)
- **节点**: ProblemFile实例
- **边类型**: `SUCCESS_NEXT`（成功链）, `FAIL_RETRY`（失败-重试）
- **存储**: 基于networkx的内存存储，支持持久化到JSON

### 3. Belief Graph (信念图)
- **原子信念**: 工作流模板、易错点、环境适配等
- **尝试信念**: 记录agent的尝试决策过程
- **置信度**: 基于统计证据的动态更新

### 4. Multi-view Embedding (多视角嵌入)
- **任务语义**: 任务描述的高层语义
- **文件范围**: 涉及的文件和目录
- **错误签名**: 错误类型和关键token
- **工具输出**: 工具执行结果
- **差异摘要**: 代码变更摘要
- **意图**: agent的意图描述

### 5. Hierarchical Retrieval (分层检索)
- **任务级检索**: 相似任务的成功骨架 + 高置信workflow/env beliefs
- **Action级检索**: 优先检索fail_retry结构附近的相似失败-修复模式

### 6. Memory Agent (内存代理服务)
- **Query Rewriting**: 自然语言任务描述改写成结构化可检索query
- **Subgraph Selection**: 从KG中选择最有用的经验子图（而非简单top-k节点）
- **Experience Distillation**: 压缩为可执行建议/流程tips/约束候选
- **Evidence Referencing**: 返回证据坐标，支持回放与追责
- **Belief Update**: 异步更新信念统计与状态（promote/deprecate）

### 7. Processing Modules (处理模块)
- **ActionLogger**: 执行时生成ProblemFile + 证据指针
- **KGWriter**: 写入Observation KG并生成多视角embedding
- **ErrorHandler**: 执行时修复建议生成
- **RCAAgent**: 根因分析（最小root_cause集合 + 传播链）

## 集成方式

Agent-mem通过SWE-agent的外部工具框架集成，替换原有的Tool A/Tool B：

### Hook事件
1. **规划时经验注入** (范式A): `plan_generated`事件
   - 触发时机: agent生成新plan时
   - 输入: agent思考(thought), 计划动作(action)
   - 输出: 规划建议 + 证据引用

2. **执行时出错回忆** (范式B): `action_error`事件
   - 触发时机: 动作执行出错时
   - 输入: 错误类型, 错误消息, 失败动作
   - 输出: 修复建议 + 相似失败经验

### 配置步骤

#### 1. 安装依赖
```bash
cd /home/pt/SWE-bench/PDDL_work_mem/tools/sweagent_ext_tools
pip install -e .
```

#### 2. 配置SWE-agent使用Agent-mem
在SWE-agent配置中添加：

```yaml
hooks:
  - class: sweagent_ext_tools.bridge_hook.ExternalToolBridgeHook
    kwargs:
      tool_a_cmd: "python -m agent_mem_main --tool A"
      tool_b_cmd: "python -m agent_mem_main --tool B"
      timeout_sec: 5.0
```

或者通过环境变量配置：
```bash
export SWE_AGENT_EXT_TOOL_A_CMD="python -m agent_mem_main --tool A"
export SWE_AGENT_EXT_TOOL_B_CMD="python -m agent_mem_main --tool B"
export SWE_AGENT_EXT_TOOL_TIMEOUT_SEC=5.0
```

#### 3. 配置Agent-mem存储
创建配置文件 `agent_mem_config.yaml`:
```yaml
storage:
  graph_store_dir: "/path/to/agent_mem_data/graphs"
  evidence_dir: "/path/to/agent_mem_data/evidence"
  auto_save: true

retrieval:
  similarity_threshold: 0.7
  max_planning_results: 5
  max_repair_results: 3

embedding:
  model: "text-embedding-3-small"  # 或其他本地模型
  batch_size: 32
```

#### 4. 运行示例
```bash
# 测试规划时经验注入
export SWE_AGENT_EXT_EVENT_JSON='{"event":"plan_generated","agent":"test_agent","thought":"Fix bug in calculate function","action":"Edit file src/calculator.py"}'
python -m agent_mem_main --config agent_mem_config.yaml

# 测试执行时出错回忆
export SWE_AGENT_EXT_EVENT_JSON='{"event":"action_error","agent":"test_agent","error_type":"FileNotFoundError","error_message":"File not found: src/calculator.py","thought":"Try to edit the file","action":"Edit file src/calculator.py"}'
python -m agent_mem_main --config agent_mem_config.yaml
```

## 数据流

```
SWE-agent执行
    ↓
ExternalToolBridgeHook捕获事件
    ↓
设置SWE_AGENT_EXT_EVENT_JSON环境变量
    ↓
调用agent_mem_main.py
    ↓
SWEAgentAdapter处理事件
    ↓
ActionLogger记录ProblemFile
    ↓
KGWriter写入Observation KG
    ↓
MemoryAgent检索相关经验
    ↓
返回建议和证据引用
    ↓
SWE-agent接收并利用建议
```

## 目录结构

```
sweagent_ext_tools/
├── agent_mem_main.py              # 主入口点
├── bridge_hook.py                 # SWE-agent钩子
├── README_AGENT_MEM.md            # 本文档
└── agent_mem/                     # 核心模块
    ├── core/                      # 核心数据结构
    │   ├── problem_file.py        # ProblemFile定义
    │   ├── observation_kg.py      # Observation KG
    │   └── belief_graph.py        # Belief Graph
    ├── models/                    # 数据模型（兼容旧版）
    │   ├── problem_file.py        # ProblemFile模型
    │   └── observation_kg.py      # Observation KG模型
    ├── retrieval/                 # 检索模块
    │   ├── memory_agent.py        # Memory Agent服务
    │   ├── embedder.py            # 多视角Embedding
    │   └── retriever.py           # 分层检索器
    ├── processing/                # 处理模块
    │   ├── action_logger.py       # 动作记录器
    │   ├── kg_writer.py           # KG写入器
    │   ├── error_handler.py       # 错误处理器
    │   └── rca_agent.py           # 根因分析
    ├── storage/                   # 存储模块
    │   ├── graph_store.py         # 图存储
    │   └── interface.py           # 存储接口
    ├── integration/               # 集成模块
    │   └── sweagent_adapter.py    # SWE-agent适配器
    ├── config/                    # 配置管理
    │   └── config_manager.py      # 配置管理器
    └── tests/                     # 测试
        └── test_core.py           # 核心测试
```

## 验证方法

### 单元测试
```bash
cd /home/pt/SWE-bench/PDDL_work_mem/tools/sweagent_ext_tools
python -m pytest agent_mem/tests/test_core.py -v
```

### 集成测试
```bash
# 测试规划时经验注入
python -c "
import os
os.environ['SWE_AGENT_EXT_EVENT_JSON'] = '{\"event\":\"plan_generated\",\"agent\":\"test\",\"thought\":\"test thought\",\"action\":\"test action\"}'
from agent_mem_main import main
import sys
sys.exit(main())
"

# 查看统计数据
python -m agent_mem_main --stats
```

## 性能考虑

1. **内存使用**: Observation KG基于networkx内存存储，大规模使用需考虑分片或持久化到图数据库
2. **检索效率**: 分层检索优先使用embedding相似度，复杂查询可能需优化索引
3. **证据存储**: 原始输出存储在文件系统，考虑压缩和清理策略
4. **并发安全**: 多agent并发访问需加锁或使用数据库事务

## 扩展方向

1. **持久化后端**: 支持Neo4j、GraphDB等图数据库
2. **Embedding模型**: 支持本地模型和多种embedding策略
3. **检索优化**: 向量数据库集成、混合检索策略
4. **信念推理**: 更复杂的信念更新和冲突消解逻辑
5. **可视化界面**: 经验图谱和信念状态的可视化

## 论文研究方向匹配

Agent-mem系统匹配《中文论文开题.md》中的研究方向：

- **RQ1**: 训练自由（training-free）的工作经验记忆机制有效性
- **RQ2**: 多视角embedding对经验检索的精度影响
- **RQ3**: 失败-重试结构对修复建议生成的作用
- **RQ4**: 信念图对长期经验积累的支撑效果

对应假设H1-H3均可通过本系统进行实证验证。