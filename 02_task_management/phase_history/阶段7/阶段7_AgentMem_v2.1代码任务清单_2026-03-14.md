# 阶段7：AgentMem v2.1 代码任务清单

**日期**：2026-03-14  
**状态**：Execution Backlog / Partially Implemented  
**上游文档**：

1. `阶段7_AgentMem_v2最终框架完整流程与模块说明_2026-03-14.md`
2. `阶段7_AgentMem_v2.1升级施工方案_2026-03-14.md`
3. `v2.1 实施约束清单1.0.md`
4. `v2.1 接口与状态转移规范1.0.md`

> 一句话结论：**这份文档不是“阶段性建议”，而是把当前框架升级到 v2.1 的代码施工 backlog。每个任务都给出文件边界、函数落点、明确不做什么、验收标准和测试要求。**

## 0.1 2026-03-15 执行状态更新

截至 2026-03-15，当前 backlog 中的 v2.1 最小闭环已经实现并完成一轮真实测试。

### 已完成的代码组

1. `G0`：配置、v2.1 共享类型、预算和 sidecar 配置入口已落地
2. `P1`：`EpisodeLedgerStore`、hot-path success fact、adapter success helper 已落地
3. `P2`：`run_done_context`、`success_fact_report`、`SubtaskProjector`、`SubtaskEdgeBuilder` 已落地
4. `P3`：`CardCompiler`、`compiler_cards_v21`、`MemoryAgent` compiler card 接线已落地
5. `P4`：`ObjectGovernancePolicy`、official eval 对 compiler cards 与 sidecar 对象的受限写回已落地

### 已完成的真实测试

1. v2.1 新增测试：
   - `12 passed in 0.34s`
2. 关键回归测试：
   - `34 passed, 1 skipped in 0.49s`

### 本轮修复的真实回归问题

首次跑回归时，发现两处 v2.1 集成失败：

1. `run_done -> subtask_projection` 在真实集成链路下得到 `subtask_count = 0`
2. `official_eval_feedback` 无法更新到 `subtask_instances` 最新视图

其中第二个问题已在前一轮通过 versioned `record_id` 修复。  
这次新增修复的是第一个问题，根因如下：

1. `AGENT_MEM_ENABLE_LLM_EXTRACTION=0` 之前会让 `ExtractionOrchestrator.process_attempt()` 提前返回
2. 启发式 `trial_overview / subblock_analysis / attempt_summary_v1` 也被一起关闭
3. 导致 `projected_subtask` 在真实测试场景里失去输入

当前修复原则：

1. 关闭 LLM extraction 只关闭深抽取
2. 不关闭启发式 attempt summary 与 subblock analysis

这条修复已经通过：

1. 定向测试
2. v2.1 新增测试
3. 关键回归测试

所以本文档后续任务项可以理解为：

1. 已落地代码的边界说明
2. 后续重测和进一步扩展时的核对清单

---

## 0. 本文档解决什么问题

前面的文档已经回答了：

1. 新框架是什么
2. 为什么这么设计
3. 升级顺序是什么
4. 施工前哪些约束必须写死

但真正开始写代码时，还需要最后一层：

> **具体改哪个文件、改什么函数、产出什么、什么不能顺手一起做。**

本文档就是这层。

---

## 1. 当前源码基线与实施边界

## 1.1 当前主要代码入口

升级工作默认围绕下面这些真实文件展开：

### 外部入口

1. `source_code/sweagent_external_tools/bridge_hook.py`
2. `source_code/sweagent_external_tools/agent_mem_main.py`

### 编排层

1. `source_code/sweagent_external_tools/agent_mem/integration/sweagent_adapter.py`

### 事实与学习层

1. `source_code/sweagent_external_tools/agent_mem/processing/action_logger.py`
2. `source_code/sweagent_external_tools/agent_mem/processing/extraction_orchestrator.py`
3. `source_code/sweagent_external_tools/agent_mem/processing/evaluation_feedback.py`
4. `source_code/sweagent_external_tools/agent_mem/processing/failure_card_builder.py`
5. `source_code/sweagent_external_tools/agent_mem/processing/rca_agent.py`

### 检索与存储层

1. `source_code/sweagent_external_tools/agent_mem/retrieval/memory_agent.py`
2. `source_code/sweagent_external_tools/agent_mem/storage/graph_store.py`
3. `source_code/sweagent_external_tools/agent_mem/config/config_manager.py`
4. `source_code/sweagent_external_tools/agent_mem/types.py`

### 测试目录

1. `source_code/sweagent_external_tools/agent_mem/tests/`

## 1.2 推荐新增文件

为了减少目录 churn，v2.1 新模块优先长在现有目录：

1. `source_code/sweagent_external_tools/agent_mem/storage/episode_ledger_store.py`
2. `source_code/sweagent_external_tools/agent_mem/processing/subtask_projector.py`
3. `source_code/sweagent_external_tools/agent_mem/processing/subtask_edge_builder.py`
4. `source_code/sweagent_external_tools/agent_mem/processing/card_compiler.py`
5. `source_code/sweagent_external_tools/agent_mem/processing/object_governance_policy.py`
6. `source_code/sweagent_external_tools/agent_mem/tests/test_v21_success_fact.py`
7. `source_code/sweagent_external_tools/agent_mem/tests/test_v21_projection.py`
8. `source_code/sweagent_external_tools/agent_mem/tests/test_v21_card_compiler.py`
9. `source_code/sweagent_external_tools/agent_mem/tests/test_v21_governance.py`

## 1.3 明确不在本轮做的事

1. 不新增公开 `action_success` 外部事件类型
2. 不实现 `declared_subtask`
3. 不实现 `PathSegmentMiner`
4. 不实现 `PrototypeCompiler`
5. 不实现完整 `Skill Compiler`
6. 不在热路径引入重型 LLM / embedding / merge
7. 不让 sidecar 成为主链硬依赖

## 1.4 当前已确认的 SWEAgent 侧边界

1. 当前不需要新增 Hook API，也不需要新增第五类公开事件
2. 现有 `ExternalToolBridgeHook` 已经覆盖：
   - `on_actions_generated()`
   - `on_action_error()`
   - `on_action_executed()` hot-path success fact
   - `on_run_done()`
   - `on_model_query()`
3. 但实验启动脚本还应显式暴露 `AGENT_MEM_V21_*` 开关，避免重测时出现“代码支持、脚本未控”的隐性偏差
4. prompt 升级不属于本轮 memory backlog 的默认实现范围，应作为独立实验变量处理

---

## 2. 任务总览

| 任务组 | 核心目标 | 任务数量 |
| --- | --- | --- |
| G0 | 施工前硬约束固化 | 4 |
| P1 | 成功事实链和 sidecar 基础 | 4 |
| P2 | `run_done` 增强与 projection candidate | 5 |
| P3 | CardCompiler v1 与注入接线 | 4 |
| P4 | Governance v1 与 official eval 受限写回 | 4 |
| T | 测试与回归 | 4 |

---

## 3. G0：施工前硬约束固化

## G0-01 配置开关与预算常量

**目标**：为全部 v2.1 新行为提供显式开关和预算配置。  

**涉及文件**：

1. `agent_mem/config/config_manager.py`
2. `agent_mem_main.py`

**具体改动**：

1. 新增 `agent_mem.v21.*` 配置项：
   - `enable_success_fact_hotpath`
   - `enable_sidecar`
   - `enable_subtask_projection`
   - `enable_card_compiler`
   - `enable_governance`
   - `hotpath_timeout_ms`
   - `coldpath_timeout_ms`
   - `max_cards_per_query`
2. 给默认值，默认保持兼容当前阶段6 行为
3. 配置解析失败时必须可诊断，但不得破坏默认主链启动

**边界**：

1. 只加配置和读取逻辑
2. 不在这个任务里接功能实现

**验收标准**：

1. 新配置默认关闭时，旧行为不变
2. 单开一个 feature flag 时，不会把其他功能隐式带起

**测试**：

1. 配置解析单测
2. 默认关闭回归测试

---

## G0-02 v2.1 类型、状态与证据层级常量

**目标**：把 v2.1 新对象的最小公共类型先钉死。  

**涉及文件**：

1. `agent_mem/types.py`
2. 可选新增：`agent_mem/processing/v21_shared.py`

**具体改动**：

1. 在 `types.py` 中新增或扩展：
   - `GovernanceState`
   - `EvidenceLevel`
   - `SubtaskRelationType`
2. 明确：
   - `candidate / promoted / suppressed / deprecated`
   - `local / attempt / official`
   - `PRECEDES / RETRY_OF / ALTERNATIVE_TO`
3. 如果需要共享工具函数，新增 `v21_shared.py`，集中放：
   - `build_success_fact_idempotency_key()`
   - `classify_success_like()`

**边界**：

1. 只定义最小公共常量和 helper
2. 不在这里实现 projector / compiler / governance 主逻辑

**验收标准**：

1. Hook、adapter、compiler、governance 共用同一套状态和证据层级定义
2. 不存在各模块自己硬编码字符串的情况

**测试**：

1. 枚举值单测
2. 幂等键 helper 单测

---

## G0-03 `run_done_context` 字段来源表固化

**目标**：防止 `run_done_context` 在实现过程中变成新的模糊中心。  

**涉及文件**：

1. `agent_mem/integration/sweagent_adapter.py`
2. `agent_mem/processing/extraction_orchestrator.py`

**具体改动**：

1. 在 `SWEAgentAdapter._build_run_done_context()` 附近，明确字段：
   - `touched_files`
   - `diff_summary`
   - `validation_summary`
   - `patch_digest`
   - `task_closed_cleanly`
2. 对每个字段写死：
   - 来源模块
   - fallback
   - 摘要还是 evidence ref
3. 在代码注释或常量表中保留这张字段来源表

**边界**：

1. 这个任务只定义字段和来源，不实现 SubtaskProjector

**验收标准**：

1. `run_done_context` 每个字段都能追溯到唯一来源
2. 缺字段时有明确定义的 fallback

**测试**：

1. `run_done_context` 结构单测
2. 缺字段 fallback 单测

---

## G0-04 compiler 与 governance 权限边界固化

**目标**：让后续 P3/P4 不会在“谁有权改状态”上重新吵一轮。  

**涉及文件**：

1. `agent_mem/types.py`
2. 可选新增：`agent_mem/processing/v21_shared.py`
3. `agent_mem/processing/evaluation_feedback.py`

**具体改动**：

1. 固定 `CompilerCard` 最小字段要求：
   - `card_id`
   - `card_type`
   - `family_id`
   - `source_object_ids`
   - `confidence`
   - `promotion_state`
   - `evidence_level`
2. 固定 governance 权限边界：
   - 哪些转移只允许 `ObjectGovernancePolicy`
   - 哪些转移可由 `EvaluationFeedbackProcessor`
3. 固定 pre-eval success-like object 不得直接 promoted

**边界**：

1. 只固化契约，不实现具体 compiler/governance 逻辑

**验收标准**：

1. 权限边界能被后续代码直接引用
2. `official_eval_feedback` 不能再被误用为全能状态修改器

**测试**：

1. 权限表一致性单测

---

## 4. P1：成功事实链和 sidecar 基础

## P1-01 新增 `EpisodeLedgerStore`

**目标**：实现 append-only sidecar 基础存储。  

**涉及文件**：

1. 新增 `agent_mem/storage/episode_ledger_store.py`
2. `agent_mem/storage/__init__.py`
3. `agent_mem/tests/test_v21_success_fact.py`

**具体改动**：

1. 实现最小接口：
   - `append(event: dict) -> dict`
   - `append_batch(events: list[dict]) -> dict` 可选
2. 支持写：
   - `episode_ledger.jsonl`
   - 未来的 `subtask_instances.jsonl`
   - 未来的 `subtask_edges.jsonl`
3. 返回：
   - `written`
   - `record_id`
   - `skipped_reason`
4. 写失败时不抛致命异常给主链

**边界**：

1. 不做 merge
2. 不做读取重排
3. 不做治理

**验收标准**：

1. JSONL 可稳定追加
2. sidecar 写失败可降级

**测试**：

1. append 正常写入
2. 路径不存在自动创建
3. 写失败降级

---

## P1-02 Hook 热路径最小 success fact 记录

**目标**：让 `on_action_executed()` 开始记录最小 success fact。  

**涉及文件**：

1. `bridge_hook.py`
2. `agent_mem/types.py`
3. `agent_mem/processing/v21_shared.py` 可选
4. `agent_mem/tests/test_v21_success_fact.py`

**具体改动**：

1. 在 `on_action_executed()` 中生成最小 success fact：
   - `instance_id`
   - `run_id`
   - `attempt_id`
   - `trace_id`
   - `step_index`
   - `action_text`
   - `success_like`
   - `timestamp`
2. 调用统一 `classify_success_like()`
3. 通过 `EpisodeLedgerStore.append()` 或等价 sidecar writer 写入
4. 使用固定幂等键：`trace_id + step_index`

**边界**：

1. 不在这里生成 `ProblemFile`
2. 不在这里生成 `SubtaskInstance`
3. 不在这里做 LLM / embedding / merge

**验收标准**：

1. 成功动作发生后有最小 success fact
2. 重放同一事件不会重复写入
3. sidecar 写失败不会影响当前 step

**测试**：

1. 正常写入
2. 重复写入幂等
3. 缺 `trace_id` 时降级为 telemetry

---

## P1-03 Adapter 成功事实 helper 扩展

**目标**：把成功动作事实从“散落逻辑”收敛到 adapter helper。  

**涉及文件**：

1. `agent_mem/integration/sweagent_adapter.py`
2. `agent_mem/processing/action_logger.py`
3. `agent_mem/tests/test_stage6_adapter.py`

**具体改动**：

1. 扩展 `handle_action_success()` 的参数能力，支持：
   - `instance_id`
   - `run_id`
   - `attempt_id`
   - `trace_id`
   - `step_index`
   - 可选 `touched_files / diff_content / test_output`
2. 内部调用 `ActionLogger.log_action()` 时，把这些字段带全
3. 保持它作为内部 helper，而不是新的公开事件入口

**边界**：

1. 不改 `agent_mem_main.py` 的公开事件白名单
2. 不在这个任务里接 `run_done` reconcile

**验收标准**：

1. helper 可以被未来冷路径复用
2. 不破坏现有 adapter 初始化和 task context 管理

**测试**：

1. helper 参数扩展回归测试
2. `ProblemFile` 关键字段透传测试

---

## P1-04 v2.1 成功事实链测试骨架

**目标**：先把最关键链路的测试骨架搭起来。  

**涉及文件**：

1. 新增 `agent_mem/tests/test_v21_success_fact.py`

**测试覆盖至少包括**：

1. success fact 最小 schema
2. 幂等键
3. sidecar 写失败降级
4. feature flag 关闭回归

**边界**：

1. 只写测试，不扩实现功能

---

## 5. P2：`run_done` 增强与 projection candidate

## P2-01 `run_done_context` 补全与 `success_fact_report`

**目标**：把 `run_done` 真正变成 success truth 的 bootstrap 真值源。  

**涉及文件**：

1. `agent_mem/integration/sweagent_adapter.py`
2. `agent_mem/processing/extraction_orchestrator.py`
3. `agent_mem/tests/test_stage6_adapter.py`

**具体改动**：

1. 扩展 `_build_run_done_context()`，补齐：
   - `touched_files`
   - `diff_summary`
   - `validation_summary`
   - `patch_digest`
   - `task_closed_cleanly`
2. 在 `handle_run_done()` 中新增：
   - `success_fact_report`
   - `sidecar_write_report`
3. 做热/冷路径 reconcile：
   - 是否捕获了 success fact
   - 哪些字段由冷路径补齐
   - 最终 reconcile 是否一致

**边界**：

1. 不在这个任务里接入 SubtaskProjector

**验收标准**：

1. 即使热路径没写成功事实，冷路径仍能补基础真值
2. `run_done` 返回新增 report
3. 超时或异常时仍保底 `attempt_summary_v1`

**测试**：

1. `run_done_context` 补齐单测
2. `success_fact_report` 单测
3. fallback summary 单测

---

## P2-02 `SubtaskProjector` candidate 实现

**目标**：从 cold-path 材料投影出 candidate subtasks。  

**涉及文件**：

1. 新增 `agent_mem/processing/subtask_projector.py`
2. `agent_mem/types.py`
3. `agent_mem/tests/test_v21_projection.py`

**具体改动**：

1. 提供 `project(...) -> dict` 或等价接口
2. 输入：
   - `attempt_summary_v1`
   - `trial_overview`
   - `subblock_analysis`
   - `ProblemFile[]`
   - `run_done_context`
3. 输出：
   - `SubtaskInstance[]`
   - `projection_report`
4. 初始状态固定为 `projected_candidate`

**边界**：

1. 只产 candidate
2. 不进入默认 retrieval
3. 不直接编成 card

**验收标准**：

1. 输出结构稳定
2. 缺字段可降级
3. 不依赖未定义 `run_done_context` 字段

**测试**：

1. 正常投影测试
2. 缺字段降级测试
3. 最小输出结构测试

---

## P2-03 `SubtaskEdgeBuilder` candidate 实现

**目标**：从 subtasks 之间生成最小结构边。  

**涉及文件**：

1. 新增 `agent_mem/processing/subtask_edge_builder.py`
2. `agent_mem/types.py`
3. `agent_mem/tests/test_v21_projection.py`

**具体改动**：

1. 支持三类边：
   - `PRECEDES`
   - `RETRY_OF`
   - `ALTERNATIVE_TO`
2. 输出字段至少包含：
   - `edge_type`
   - `effectiveness_candidate`
   - `supporting_attempt_ids`
3. 与 `SubtaskProjector` 对接

**边界**：

1. 不生成最终因果边
2. 不写 `verified_causal`

**验收标准**：

1. 三类边类型可区分
2. 只写 candidate 级支持信息

**测试**：

1. 边类型测试
2. candidate 输出测试

---

## P2-04 `projected_subtask` Gate 指标实现位预留

**目标**：在代码里给稳定性 gate 留明确挂点。  

**涉及文件**：

1. `agent_mem/processing/subtask_projector.py`
2. `agent_mem/processing/card_compiler.py` 未来接线
3. `agent_mem/tests/test_v21_projection.py`

**具体改动**：

1. 在 `projection_report` 中预留：
   - 解释性稳定字段
   - 决策性稳定字段
   - pass/fail 结果
2. 不在本阶段真正跑线上 gate，只预留结构和默认 `candidate_only`

**边界**：

1. 不做真实实验阈值判定逻辑
2. 只留字段和开关位

**验收标准**：

1. 后续可以不改接口直接接 Gate B

---

## P2-05 P2 测试包

**目标**：把 cold-path 和 projection 的回归锁住。  

**涉及文件**：

1. 新增 `agent_mem/tests/test_v21_projection.py`
2. 扩展 `test_extraction_orchestrator.py`

**测试覆盖至少包括**：

1. `run_done_context` 补齐
2. `success_fact_report`
3. `SubtaskProjector`
4. `SubtaskEdgeBuilder`
5. projection error 降级

---

## 6. P3：CardCompiler v1 与注入接线

## P3-01 `CardCompiler` 基础实现

**目标**：建立唯一默认编译入口。  

**涉及文件**：

1. 新增 `agent_mem/processing/card_compiler.py`
2. `agent_mem/types.py`
3. `agent_mem/tests/test_v21_card_compiler.py`

**具体改动**：

1. 固定输入白名单：
   - `attempt_summary_v1`
   - `failure_card_v2`
   - `repair_pattern_v2`
   - `SubtaskInstance`
2. 固定输出白名单：
   - `PlanHintCard`
   - `SubtaskRiskCard`
   - `RetryHintCard`
   - `ClosureGuardCard`
3. card 最小字段：
   - `card_id`
   - `card_type`
   - `hint`
   - `family_id`
   - `source_object_ids`
   - `confidence`
   - `promotion_state`
   - `evidence_level`

**边界**：

1. 不提前接 `Path / Prototype / Skill`
2. 不允许 raw object 直接注入

**验收标准**：

1. 每张 card 都能追溯到 source objects
2. 每张 card 都有 `evidence_level`

**测试**：

1. 输入白名单测试
2. 输出字段完整性测试
3. `evidence_level` 测试

---

## P3-02 `MemoryAgent` 接入 compiler cards

**目标**：让 retrieval 层开始消费统一 card。  

**涉及文件**：

1. `agent_mem/retrieval/memory_agent.py`
2. `agent_mem/tests/test_v21_card_compiler.py`
3. `agent_mem/tests/test_stage6_adapter.py`

**具体改动**：

1. 在 planning / repair 两条检索链中接入 compiler cards
2. 做：
   - 去重
   - 预算控制
   - family 排序
3. 输出保持与 hook 当前消费格式兼容

**边界**：

1. compiler 关闭时必须回退到旧 retrieval
2. 不修改 hook 注入协议格式

**验收标准**：

1. compiler 开关打开后能召回统一 card
2. compiler 关闭时旧链保持工作

**测试**：

1. compiler on/off A/B 测试
2. retrieval 去重测试

---

## P3-03 Hook 注入链兼容 card

**目标**：让 `on_model_query()` 消费 compiler 输出时不打破现有注入控制。  

**涉及文件**：

1. `bridge_hook.py`
2. `agent_mem/tests/test_v21_card_compiler.py`

**具体改动**：

1. 保持 `on_model_query()` 的：
   - `max_hints`
   - `hint_char_budget`
   - family cooldown
2. 让 compiler card 的 `family_id` 和 `source_object_ids` 透传到 hook 选择逻辑

**边界**：

1. 不改注入消息格式大结构
2. 不新增第二注入口

**验收标准**：

1. card 注入仍受预算控制
2. traceability 不丢失

**测试**：

1. family cooldown 测试
2. hint budget 测试

---

## P3-04 P3 测试包

**目标**：把 compiler 链条单独锁住。  

**涉及文件**：

1. 新增 `agent_mem/tests/test_v21_card_compiler.py`

**覆盖至少包括**：

1. compiler 输入白名单
2. compiler 输出字段
3. card fingerprint 去重
4. compiler 关闭回退

---

## 7. P4：Governance v1 与 official eval 受限写回

## P4-01 `ObjectGovernancePolicy` 基础实现

**目标**：给 candidate 对象加上生命周期。  

**涉及文件**：

1. 新增 `agent_mem/processing/object_governance_policy.py`
2. `agent_mem/types.py`
3. `agent_mem/tests/test_v21_governance.py`

**具体改动**：

1. 支持最小状态机：
   - `candidate`
   - `promoted`
   - `suppressed`
   - `deprecated`
2. 支持：
   - growth cap
   - 近重复合并
   - suppression
   - deprecation
   - pre-eval success guard

**边界**：

1. 第一版不做复杂启发式评分系统
2. 第一版不做跨任务 prototype 聚类

**验收标准**：

1. 任一对象状态变更都有统一治理入口
2. suppressed / deprecated 对象不会进入默认在线消费链

**测试**：

1. 状态转移测试
2. suppression / deprecation 测试

---

## P4-02 `EvaluationFeedbackProcessor` 受限写回

**目标**：把 official eval 收束成最终闸门。  

**涉及文件**：

1. `agent_mem/processing/evaluation_feedback.py`
2. `agent_mem/integration/sweagent_adapter.py`
3. `agent_mem/tests/test_evaluation_feedback.py`
4. `agent_mem/tests/test_v21_governance.py`

**具体改动**：

1. 保留 attempt summary outcome 更新
2. 只允许直接写回：
   - governance state
   - `CompilerCard.promotion_state`
   - `SubtaskInstance.eval_context`
   - `SubtaskEdge.eval_support`
3. 禁止：
   - 覆盖 `SubtaskInstance.local_result_status`
   - 直接宣布最终因果边

**边界**：

1. 不把 official eval 变成细粒度因果解释器

**验收标准**：

1. resolved / unresolved / infra_failure 三类结果都有清晰写回
2. 权限边界可测

**测试**：

1. 写回边界测试
2. 权限表测试

---

## P4-03 `GraphStore` 与治理结果接线

**目标**：让治理后的稳定对象进入 curated view，同时保留 sidecar 分工。  

**涉及文件**：

1. `agent_mem/storage/graph_store.py`
2. `agent_mem/tests/test_v21_governance.py`

**具体改动**：

1. 为治理状态存储提供最小字段位
2. 确保：
   - sidecar candidate 不直接混写
   - governed stable objects 才进入主视图

**边界**：

1. 不让 GraphStore 承担 append-only ledger

**验收标准**：

1. `GraphStore` 仍是 curated store
2. sidecar 仍是 append-only candidate store

**测试**：

1. 写入边界测试

---

## P4-04 P4 测试包与实验挂点

**目标**：把 Gate C 和 ablation 的代码挂点留出来。  

**涉及文件**：

1. 新增 `agent_mem/tests/test_v21_governance.py`
2. 可选扩展现有实验脚本或 notes tooling

**具体改动**：

1. 预留统计字段：
   - card 重复率
   - suppression 数
   - promoted 数
2. 为后续 ablation 预留 on/off 配置组合

**边界**：

1. 第一版不要求把实验平台自动化做完
2. 但必须留出观测点

---

## 8. T：跨阶段测试与回归任务

## T-01 旧主链无回归

**涉及文件**：

1. `agent_mem/tests/test_stage6_adapter.py`
2. `agent_mem/tests/test_stage4_memory.py`

**要求**：

1. v2.1 开关全关时，行为接近当前阶段6

---

## T-02 `official_eval_feedback` 回归

**涉及文件**：

1. `agent_mem/tests/test_evaluation_feedback.py`
2. `agent_mem/tests/test_official_eval_bridge.py`

**要求**：

1. 旧 feedback promote/suppress 不被破坏
2. 新的受限写回边界可验证

---

## T-03 `run_done` 冷路径保底回归

**涉及文件**：

1. `agent_mem/tests/test_extraction_orchestrator.py`
2. `agent_mem/tests/test_stage6_adapter.py`

**要求**：

1. cold path 超时时仍有最小 `attempt_summary_v1`
2. projector / compiler / governance 失败不破坏 `run_done`

---

## T-04 注入链预算回归

**涉及文件**：

1. `bridge_hook.py`
2. `agent_mem/tests/test_v21_card_compiler.py`

**要求**：

1. card 接入后，`max_hints`、`hint_char_budget`、family cooldown 仍然有效

---

## 9. 推荐实施顺序

实际代码执行顺序建议如下：

1. `G0-01 -> G0-04`
2. `P1-01 -> P1-04`
3. `P2-01 -> P2-05`
4. `P3-01 -> P3-04`
5. `P4-01 -> P4-04`
6. `T-01 -> T-04` 穿插执行

---

## 10. 一句话执行原则

**先把 schema、幂等、来源表、权限表和预算写死，再写 success fact、projection、compiler 和 governance 的代码。**

**只要这个顺序守住，v2.1 的升级就会是“渐进长出来”，而不是“再造一个平行系统”。**
