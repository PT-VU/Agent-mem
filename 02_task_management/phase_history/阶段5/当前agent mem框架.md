# 当前 AgentMem 框架（阶段五代码现状）

> 目的：基于当前代码的“已实现状态”给出准确说明，而不是仅复述规划。
> 参考基线：`PDDL_work_mem/00_project_context/resources/Agent-mem架构.md`
> 代码基线：`PDDL_work_mem/source_code/sweagent_external_tools/`

---

## 0. 一句话总览
当前 AgentMem 已经是一个“**SWE-agent 运行时 Hook + 外部事件适配器 + 经验提取/存储/检索/注入闭环**”系统：
1. 在线阶段记录 action 轨迹并检索经验给当前 LLM。
2. 结束阶段（run_done）做 RCA + 抽象经验提取 + 失败卡/修复模式写入。
3. 下一轮规划或报错时复用这些经验。

系统是 **training-free**（不改模型权重），核心依赖结构化经验与检索注入。

---

## 1. 代码模块全景（按职责分层）

### 1.1 运行时接入层（SWE-agent 侧）
- `bridge_hook.py`：`ExternalToolBridgeHook`
  - 挂在 SWE-agent 生命周期回调里：
    - `on_actions_generated`（计划产生）
    - `on_action_error`（执行报错）
    - `on_model_query`（模型请求前，注入记忆）
    - `on_action_executed`（动作执行后，更新干预反馈）
    - `on_run_done`（任务结束，收尾与门禁评估）
  - 负责：事件打包、调用外部工具、hint 缓冲、注入、干预效果反馈、质量门控统计。

- `dispatcher.py`
  - 当 AgentMem 可用时，统一把 Tool A / Tool B 请求转到 `agent_mem_main.py`。
  - 不可用时才回退旧版 `tools/tool_a.py` 与 `tools/tool_b.py`（纯日志模式）。

### 1.2 外部工具入口层
- `agent_mem_main.py`
  - 从环境变量 `SWE_AGENT_EXT_EVENT_JSON` 读取事件。
  - 识别并路由事件：`plan_generated` / `action_error` / `run_done`。
  - 调用 `SWEAgentAdapter` 处理。

### 1.3 编排与领域服务层
- `agent_mem/integration/sweagent_adapter.py`：`SWEAgentAdapter`
  - 编排核心组件：
    - `ActionLogger`（轨迹写入）
    - `KGWriter`（embedding 生成）
    - `MemoryAgent`（检索与建议生成）
    - `RCAAgent`（根因分析）
    - `FailureCardBuilder`（失败卡）
    - `AbstractExperienceBuilder`（抽象经验）
    - `ExtractionOrchestrator`（run_done 后提取流水线）
  - 维护运行态索引：
    - `active_tasks.json`（当前活动 task 映射）
    - `experience_rw_map.jsonl`（读写经验映射，便于审计）

### 1.4 经验处理与学习层
- `processing/action_logger.py`：把每个 action 落成 `ProblemFile` 节点并建边。
- `processing/kg_writer.py`：多视角 embedding 生成与写回。
- `processing/rca_agent.py`：失败轨迹根因分析（模块/传播链/修复建议）。
- `processing/failure_card_builder.py`：unresolved -> `failure_card_v2`。
- `processing/llm_extractor.py`：可选 LLM 辅助 step 级错误分析（hybrid）。
- `processing/extraction_orchestrator.py`：run_done 时触发抽取、质量门控、模板映射。

### 1.5 存储与检索层
- `storage/graph_store.py`：统一持久化（JSON 文件）+ 查询。
- `retrieval/memory_agent.py`：按 query_type 检索、融合、去重、重排、生成建议。
- `core/`：领域对象
  - `ProblemFile`、`ObservationKG`、`BeliefGraph`
  - `FailureCardV2`、`RepairPatternV2`、`PreventiveRuleV2`

---

## 2. 关键输入输出与协议

## 2.1 `SWE_AGENT_EXT_EVENT_JSON` 是什么
它是 Hook 调外部工具时注入的环境变量，值是一个 JSON 字符串。它是 AgentMem 的在线事件输入协议。

### 2.1.1 通用字段
- `version`: 协议版本（当前 `v1`）
- `event` / `event_type`: 事件名
- `source`: 来源（当前 `bridge_hook`）
- `agent`: agent 名称
- `instance_id`: SWEBench 实例 id
- `run_id`: 批次/运行 id
- `attempt_id`: 尝试 id
- `step_index`: 当前步骤号
- `timestamp`: 事件时间戳
- `trace_id`: 事件追踪 id（用于跨日志关联）

### 2.1.2 事件特有字段
- `plan_generated`：`thought`、`action`
- `action_error`：`error_type`、`error_message`、`thought`、`action`
- `run_done`：`trajectory_steps`、`exit_status`、`has_submission`

## 2.2 Tool A / Tool B 在当前实现中是什么
- 旧逻辑里 Tool A / Tool B 是两个独立脚本。
- 当前实现中，A/B 主要是“**事件路由语义**”：
  - A 偏计划事件（`plan_generated`）
  - B 偏错误与收尾（`action_error` / `run_done`）
- 真实处理已经统一走 `dispatcher.py -> agent_mem_main.py -> SWEAgentAdapter`。

---

## 3. 核心数据结构（落地字段）

## 3.1 ProblemFile（action 原子）
`ProblemFile` 是事实图节点。每个 agent action 会落一个节点，字段包含：
- 标识：`action_id`、`task_id`、`instance_id`、`run_id`、`trace_id`
- 行为：`action_type`、`action_text`、`intent_text`、`action_family`
- 输入与工具：`inputs`、`tool_calls`
- 证据指针：`stdout_ref`、`stderr_ref`、`diff_summary_ref`、`tests_ref`、`evidence_index`
- 结果与分析：`outcome`、`failure_signature`、`env_signature`
- 统计：`patch_stats`、`test_stats`、`execution_stats`
- 向量：`emb_task_sem`、`emb_file_scope`、`emb_error_sig`、`emb_tool_output`、`emb_diff_summary`、`emb_intent`

## 3.2 结构化经验对象
- `abstract_experience`：跨任务可复用经验摘要
- `failure_card_v2`：失败资产（错误签名、候选修复、验证命令、证据）
- `repair_pattern_v2`：可复用修复模式
- `preventive_rule_v2`：预防规则（当前写入能力已在模型中，在线主流程使用较少）

## 3.3 信念图对象
- `AttemptBelief`：一次尝试级总结
- `AtomicBelief`：原子规则（workflow/pitfall/env_adaptation）
- 状态支持 `active/deprecated/promoted_to_preference/promoted_to_constraint`

---

## 4. 在线流程（实时链路）

## 4.1 计划阶段（plan_generated）
1. Hook 在 `on_actions_generated` 触发，构造 payload。
2. 调外部命令（通常是 Tool A 路由到 adapter）。
3. Adapter `handle_plan_generated`：
   - `ActionLogger.log_action` 写 `ProblemFile`（success）
   - `KGWriter` 生成向量
   - `MemoryAgent.retrieve_for_query_type(query_type=planning)` 检索建议
4. 响应返回 `planning_tips/evidence/confidence/retrieval_debug`。
5. Hook 把建议放入 `pending hint buffer`。

## 4.2 报错阶段（action_error）
1. Hook 在 `on_action_error` 触发，记录 `error_type/error_message`。
2. 调外部命令（通常 Tool B）。
3. Adapter `handle_action_error`：
   - 写失败 `ProblemFile`
   - 生成错误相关向量
   - 检索 `error_recovery` 或 `test_failure_fix`
4. 响应返回 `repair_suggestions/next_step_fix/evidence/confidence`。
5. Hook 缓冲这些修复 hint，等待下一次模型请求注入。

## 4.3 注入阶段（on_model_query）
1. Hook 读取 `_pending_memory_hints`。
2. 按规则筛选：
   - 最小置信度（`min_confidence`/`min_item_confidence`）
   - 预算（`hint_char_budget` / `max_hint_chars`）
   - 可选触发门槛（`require_trigger_for_injection`）
3. 将选中的 hints 拼成一段用户消息注入到 `messages`。
4. 写日志 `memory_injected`，并注册 `intervention_id` 跟踪后续 N 步是否有效。

### 4.3.1 `pending hint buffer` 来自哪里
来自外部工具响应（`plan_generated` / `action_error`）中的建议字段：
- `planning_tips`
- `repair_suggestions`
- `next_step_fix`
- `recommendations`

这些候选先进入 `_pending_memory_hints`，不是立刻注入，避免在不合适时机打断。

### 4.3.2 Hook 的触发机制是 AI 驱动还是关键词匹配
是“**事件驱动 + 规则驱动 + 检索驱动**”混合：
- 事件驱动：SWE-agent 生命周期回调触发。
- 规则驱动：关键词识别 proactive trigger（如首次访问文件、连续失败、测试前）。
- 检索驱动：真正 hint 内容来自 MemoryAgent 检索结果（非纯关键词模板）。

## 4.4 收尾阶段（run_done）
1. Hook `on_run_done` 发送结束事件。
2. Adapter `handle_run_done`：
   - 结束 task、读取任务子图
   - `update_beliefs`
   - 生成抽象经验
   - unresolved 时执行 RCA + failure card + repair pattern
   - 执行 `ExtractionOrchestrator.process_attempt`（含可选 LLM 步级分析）
   - 把 extractor 产物映射并 upsert 到标准结构
3. 写 `experience_rw_map.jsonl`（本轮读了什么、写了什么）。
4. Hook 输出 `memory_gate_evaluation`（门禁指标）。

---

## 5. 经验提取原理（当前实现版）

## 5.1 何时提取
提取是 **run_done 后触发为主**，不是每步都完整抽取。

触发条件（`ExtractionOrchestrator`）：
- `run_done_unresolved`
- `run_done_success_with_recovery`
- `run_done_high_cost`（步数高）

## 5.2 如何提取
1. 先做 rule-based 分析（taxonomy）。
2. 若启用 LLM（`AGENT_MEM_LLM_API_URL/KEY`），用 LLM 对步骤做补充分析。
3. 形成一个或多个 `CriticalSignal`（关键失败信号）。
4. 映射到既有模板：
   - `abstract_experience`
   - `failure_card_patch`
   - `repair_patterns`
5. 通过质量门（证据是否存在、置信度是否达阈值）。

## 5.3 LLM 在提取中的角色
- 不是直接决定最终存储格式。
- 是“增强分析器”：补充 step-level 根因解释和纠偏建议。
- 最终写库结构仍由 orchestrator 的模板映射固定。

---

## 6. 经验存储与关系保存

## 6.1 持久化文件
在 `AGENT_MEM_STORAGE_DIR` 下，核心文件：
- `observation_kg.json`
- `belief_graph.json`
- `abstract_experiences.json`
- `failure_cards_v2.json`
- `repair_patterns_v2.json`
- `preventive_rules_v2.json`
- `metadata.json`
- `active_tasks.json`
- `experience_rw_map.jsonl`

## 6.2 经验关联如何保存
通过多种字段关联：
- `trace_id`（事件级）
- `task_id/instance_id/run_id/attempt_id`（运行级）
- `source_event_ids/source_run_ids/source_attempt_ids`（来源级）
- `links.repair_pattern_ids`（结构化经验之间）

## 6.3 向量存储方式
当前向量嵌入在 `ProblemFile.embeddings` 字段中，随 `observation_kg.json` 持久化，不是独立向量数据库。

---

## 7. 经验检索与注入原理

## 7.1 检索入口
`MemoryAgent.retrieve_for_query_type`，按 `query_type` 路由：
- `planning`
- `error_recovery`
- `test_failure_fix`
- `regression_guard`

## 7.2 检索融合
组合三类来源：
1. 结构子图检索（SubgraphSelector）
2. embedding 相似检索（多视角）
3. 结构化经验检索（abstract/failure_card/repair_pattern/belief）

再做：
- 动态预算（不是固定 top-k）
- 去重 + 重排（类型偏置 + confidence + score）

## 7.3 注入方式
注入是“文本 hint”追加到模型输入消息中（`on_model_query`），并跟踪注入后 N 步表现（`memory_intervention_feedback`）。

---

## 8. 对 `Agent-mem架构.md` 的对齐结论（当前状态）

## 8.1 已落地
1. ProblemFile + ObservationKG + BeliefGraph 三层基础。
2. plan/error/run_done 三事件闭环。
3. run_done 后 RCA + 失败卡 + 修复模式提取。
4. 可选 LLM 辅助 step-level 提取。
5. 经验注入、门控日志、干预反馈链路。

## 8.2 部分落地
1. 经验“可验证”主要通过 evidence refs 与日志审计实现；自动验证动作仍偏轻量。
2. preventive rule 有数据结构与存储，但在线使用权重不高。

## 8.3 尚未完全落地
1. PDDL3 preference/constraint 编译与 validator 硬门禁（仍主要停留在设计/字段层）。
2. 更系统的跨实例统计学习与自动晋升策略仍可继续强化。

---

## 9. 全流程案例（从一次失败到下次改进）

> 场景：某实例在运行测试时报错，下一次 attempt 希望复用经验。

### 第 1 次 attempt（失败）
1. 计划生成：
   - Hook 发 `plan_generated`。
   - Adapter 记录计划动作 `ProblemFile`，检索到历史 planning tips，放入 hint buffer。
2. 执行中报错：
   - Hook 发 `action_error`（例如 `test_failure`）。
   - Adapter 记录失败动作，检索到 `repair_suggestions` + `next_step_fix`。
   - 这些建议进入 pending buffer。
3. 注入：
   - 下次 `on_model_query` 时，Hook 从 buffer 选中若干 hints 注入。
   - 写 `memory_injected`（包含 trace_id、memory_id、hint_count）。
4. 任务结束仍失败：
   - Hook 发 `run_done`。
   - Adapter 生成：
     - `failure_card_v2`（错误签名、候选修复、验证命令、证据）
     - `repair_pattern_v2`（可复用修复模板）
     - `abstract_experience`
     - `belief_update`
   - 记录到持久化 JSON，并写 `experience_rw_map.jsonl`。

### 第 2 次 attempt（复用）
1. 新一轮 `plan_generated`：
   - 检索会命中上一轮写入的 `failure_card_v2/repair_pattern_v2/abstract_experience`。
2. 如果又遇到类似报错：
   - `action_error` 检索将优先返回对应错误签名的修复模式。
3. 注入后执行：
   - Hook 在干预窗口内记录 `memory_intervention_feedback`。
   - 若错误减少、动作成功增加，该经验后续会在重排中更靠前。

### 这个案例体现的核心机制
- 不是“凭空聪明”，而是把历史尝试沉淀为结构化经验并在下一轮有条件复用。
- 经验是否有用可通过：`memory_injected -> intervention_feedback -> run_done` 三段日志做闭环验证。

---

## 10. 当前框架的工程定位
当前框架已经具备“可运行、可记录、可复用、可审计”的 AgentMem 主闭环，适合继续做两类工作：
1. **效果向强化**：提高提取覆盖、提升注入命中与有效率。
2. **约束向强化**：把高置信经验编译为更硬的执行前检查（向 PDDL3/validator 收敛）。

