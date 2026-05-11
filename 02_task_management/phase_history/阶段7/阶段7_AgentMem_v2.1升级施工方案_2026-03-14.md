# 阶段7：AgentMem v2.1 升级施工方案

**日期**：2026-03-14  
**状态**：Draft / Execution Plan  
**上游文档**：

1. `阶段7_AgentMem_v2最终框架完整流程与模块说明_2026-03-14.md`
2. `v2.1 实施约束清单1.0.md`
3. `v2.1 接口与状态转移规范1.0.md`

> 一句话结论：**本方案的目标不是一口气把 v2 做全，而是在不破坏阶段6 主链路的前提下，用 5 个渐进阶段把 v2.1 的关键闭环落地。**

## 0.1 2026-03-15 实际执行与测试更新

截至 2026-03-15，v2.1 的最小闭环代码已经落地，并在真实 `pytest + networkx + sweagent 源码接入` 环境中完成一轮新增测试和关键回归测试。

本轮实际测试结果：

1. v2.1 新增测试：
   - `12 passed in 0.34s`
2. 关键回归测试：
   - `34 passed, 1 skipped in 0.49s`

本轮关键修复结论：

1. 首轮回归失败根因不是 `GraphStore`、不是 sidecar 幂等，也不是 `SubtaskProjector` 本身。
2. 真正根因是 `AGENT_MEM_ENABLE_LLM_EXTRACTION=0` 时，`ExtractionOrchestrator` 之前会把整个 `process_attempt()` 早退掉，连启发式 `trial_overview / subblock_analysis / attempt_summary_v1` 也一起关掉。
3. 这会导致 `run_done -> projected_subtask` 在真实集成场景下拿到空 `subblock_analysis`，于是 `subtask_count == 0`。
4. 当前修复方式是：关闭 LLM extraction 时，仍保留启发式 attempt summary 与 subblock analysis，只关闭 LLM 深抽取和 signal/pattern 衍生层。

这条修复直接保证了：

1. v2.1 在默认“不开 LLM 深抽取”的实验设置下仍能跑通 `run_done -> projection -> compiler`
2. `projected_subtask` 的收益不再被 LLM extraction 开关意外屏蔽
3. 后续 repeat-run 重测可以把“是否开启深抽取”和“是否开启 v2.1 长期层”分开做消融

---

## 0. 本文档解决什么问题

前面的文档已经明确了：

1. AgentMem v2 的最终框架是什么
2. v2.1 的实施约束是什么
3. 接口和状态转移应该如何定义

现在需要的是一份能直接指导工程实施的升级施工方案。  
这份方案要回答的是：

1. 先做什么，后做什么
2. 每个阶段改哪些模块
3. 每个阶段的交付物、验收标准和测试点是什么
4. 每个阶段的风险、降级和回滚怎么处理

---

## 1. 升级目标与 Definition of Done

## 1.1 v2.1 升级总目标

本轮升级完成后，系统应满足：

1. **成功事实能被稳定采集，而不再主要记失败**
2. **`run_done` 冷路径能补齐 success truth，并长出 sidecar 账本**
3. **projected subtask 能以 candidate 形式存在，并和当前主链共存**
4. **控制层开始消费统一 card，而不是散乱对象**
5. **promotion / suppression / 去重 / budget 开始由治理层接管**

## 1.2 DoD

只有满足下面五条，才算 v2.1 第一阶段闭环完成：

1. `on_action_executed()` 能落下最小 success fact，且失败时可安全降级
2. `handle_run_done()` 能生成 `success_fact_report` 和 `sidecar_write_report`
3. `SubtaskProjector` 和 `SubtaskEdgeBuilder` 能在冷路径产出 candidate 对象
4. `CardCompiler` 能编译 4 类白名单 card，并被 `on_model_query()` 消费
5. `official_eval_feedback` 只做受限写回，不直接覆盖 local subtask 结果

---

## 2. 升级原则

## 2.1 只做增量，不做重写

必须保留当前在线主链：

```text
ExternalToolBridgeHook
  -> dispatcher.py
    -> agent_mem_main.py
      -> SWEAgentAdapter
```

## 2.2 先事实，后结构，再治理

施工顺序必须遵守：

1. 成功事实
2. sidecar 账本
3. projected subtask / edge
4. card compiler
5. governance

## 2.3 不提前引入研究性模块

下面这些都不应进入本轮默认施工范围：

1. `declared_subtask`
2. `PathSegmentMiner`
3. `PrototypeCompiler`
4. 完整 `Skill Compiler`
5. 在线逐子任务 LLM

## 2.4 不为了放新模块而先改目录

推荐新增模块优先长在现有目录：

1. `agent_mem/storage/episode_ledger_store.py`
2. `agent_mem/processing/subtask_projector.py`
3. `agent_mem/processing/subtask_edge_builder.py`
4. `agent_mem/processing/card_compiler.py`
5. `agent_mem/processing/object_governance_policy.py`

## 2.5 施工前 Gate 0：最后必须写死的实现约束

这一步不是“建议”，而是进入 P1 施工前的硬门槛。

### G0.1 Success Fact 最小 schema 与幂等规则

必须写死：

1. 最小字段集合：
   - `instance_id`
   - `run_id`
   - `attempt_id`
   - `trace_id`
   - `step_index`
   - `action_text`
   - `success_like`
   - `timestamp`
2. 唯一真值入口：
   - `on_action_executed()` 写热路径最小事实
   - `run_done` 负责冷路径补全与 reconcile
3. 幂等键规则：
   - 第一版固定为 `trace_id + step_index`
4. `success_like` 的统一判定责任方：
   - 固定在 adapter/shared utility

验收标准：

1. 同一次运行重复写入不会产生重复 success fact
2. 热路径与冷路径对同一 action 的事实最终一致
3. sidecar 写失败时不会影响主链运行

### G0.2 `run_done_context` 字段表与来源表

必须写死：

1. 字段清单至少包含：
   - `touched_files`
   - `diff_summary`
   - `validation_summary`
   - `patch_digest`
   - `task_closed_cleanly`
2. 每个字段的：
   - 来源模块
   - 必填/选填
   - 缺失 fallback
   - 写入位置
3. 哪些字段只存摘要，哪些字段保留原始证据 ref

验收标准：

1. `run_done_context` 缺字段时系统仍能降级运行
2. 每个字段都能追溯到唯一来源
3. `projected_subtask` 不依赖未定义字段

### G0.3 `projected_subtask` 稳定性门槛

必须写死：

1. 解释性稳定指标
2. 决策性稳定指标
3. 至少三类阈值：
   - retry 成功率提升阈值
   - post-success retrieval sharpness 提升阈值
   - 注入噪声下降阈值
4. 不达标时的处理：
   - 只保留 sidecar
   - 不进入默认 compiler 强路径
   - 不作为在线收益主张依据

验收标准：

1. 有明确 pass/fail 门槛
2. 达不到门槛时主链功能不受影响
3. ablation 能单独隔离 `projected_subtask` 收益

### G0.4 CardCompiler 白名单、证据层级与 traceability

必须写死：

1. v1 输入白名单：
   - `attempt_summary_v1`
   - `failure_card_v2`
   - `repair_pattern_v2`
   - `SubtaskInstance`
2. v1 输出白名单：
   - `PlanHintCard`
   - `SubtaskRiskCard`
   - `RetryHintCard`
   - `ClosureGuardCard`
3. 每张 card 必带：
   - `card_id`
   - `card_type`
   - `family_id`
   - `source_object_ids`
   - `confidence`
   - `promotion_state`
   - `evidence_level`

验收标准：

1. 每张注入卡都能追溯来源对象和证据层级
2. 新对象默认不会自动进入 compiler
3. compiler 关闭时，阶段6 控制层仍可独立运行

### G0.5 Governance 状态机与权限表

必须写死：

1. 最小状态机：
   - `candidate`
   - `promoted`
   - `suppressed`
   - `deprecated`
2. 每种对象适用的状态范围
3. 谁能触发状态转移
4. pre-eval success-like object 处理规则
5. growth cap / merge / deprecation 规则

验收标准：

1. 任一对象状态变化都有唯一责任模块
2. official eval 只做最终闸门，不直接承担全部细粒度因果解释
3. suppressed / deprecated 对象不会进入默认在线消费链

### G0.6 热路径 / 冷路径预算必须写成硬约束

必须写死：

1. 热路径允许的操作
2. 热路径禁止的操作
3. sidecar 写失败时的降级规则
4. 冷路径超时后的 fallback

验收标准：

1. 热路径新逻辑不会把主代理变成强依赖长期层
2. 冷路径失败时最小 `attempt_summary_v1` 仍然存在
3. 所有降级路径都能在响应或日志中看到 `skipped_reason`

---

## 3. 施工总览

| Phase | 核心目标 | 主要产物 | 风险级别 |
| --- | --- | --- | --- |
| P0 | 施工准备与护栏 | feature flags、配置项、响应骨架 | 低 |
| P1 | 成功事实链和 sidecar 基础 | hot-path success capture、EpisodeLedgerStore | 中 |
| P2 | `run_done` 增强与 projection candidate | success truth reconcile、SubtaskProjector、SubtaskEdgeBuilder | 中 |
| P3 | CardCompiler v1 + 注入接线 | 4 类 card、MemoryAgent 接线、注入预算 | 中 |
| P4 | Governance v1 + official eval 受限写回 | 状态机、suppression/promotion、ablation gate | 中高 |

## 3.1 当前执行状态

按当前实现与测试结果看，状态可以更新为：

1. `P0`：已落地并通过配置/默认关闭相关测试
2. `P1`：已落地并通过 hot-path success fact / sidecar 相关测试
3. `P2`：已落地；其中 `ExtractionOrchestrator` 的启发式 summary 保留语义已修正
4. `P3`：已落地并通过 compiler/retrieval 相关测试
5. `P4`：已落地并通过 governance / official eval 关键回归测试

当前下一阶段不再是继续补框架代码，而是：

1. 把 v2.1 开关显式接进实验启动脚本
2. 设计 SWEAgent prompt 侧的最小升级与消融矩阵
3. 启动正式 repeat-run 重测

---

## 4. Phase P0：施工准备与护栏

## 4.1 目标

在不改变现有行为的前提下，为 v2.1 升级准备开关、配置和最小响应骨架。

## 4.2 主要修改点

**建议涉及文件**：

1. `agent_mem/config/config_manager.py`
2. `agent_mem_main.py`
3. `agent_mem/integration/sweagent_adapter.py`
4. `bridge_hook.py`

## 4.3 任务拆分

### T0.0 完成 Gate 0 约束固化

在开始任何 P1 代码前，必须把以下内容写成实现级常量、schema、表格或权限定义：

1. success fact schema / 幂等键 / `success_like` 判定责任方
2. `run_done_context` 字段来源表
3. `projected_subtask` pass/fail 门槛
4. card 白名单与 `evidence_level`
5. governance 权限表
6. 热/冷路径预算硬约束

### T0.1 新增 feature flags

建议新增最小配置：

1. `agent_mem.v21.enable_success_fact_hotpath`
2. `agent_mem.v21.enable_sidecar`
3. `agent_mem.v21.enable_subtask_projection`
4. `agent_mem.v21.enable_card_compiler`
5. `agent_mem.v21.enable_governance`
6. `agent_mem.v21.hotpath_timeout_ms`
7. `agent_mem.v21.coldpath_timeout_ms`
8. `agent_mem.v21.max_cards_per_query`

### T0.2 扩展响应骨架

在不破坏旧响应的前提下，为以下 report 预留字段：

1. `success_fact_report`
2. `sidecar_write_report`
3. `projection_report`
4. `compiler_report`
5. `governance_report`

### T0.3 默认全部可关闭

所有 v2.1 新能力必须可通过配置完全关闭，关闭后行为应接近当前阶段6。

## 4.4 验收标准

1. 默认配置下，现有主链行为不变
2. 打开单一功能开关时，其余功能不被隐式带起
3. 新增响应字段缺省为空或 `disabled`
4. Gate 0 的 6 类约束已经写成实现级文档或代码常量，不再停留在口头描述

## 4.5 测试点

1. 配置解析单测
2. 默认关闭回归测试
3. 各 feature flag 单独开启 smoke test

## 4.6 回滚策略

1. 配置级一键关闭
2. 不涉及数据迁移

---

## 5. Phase P1：成功事实链和 sidecar 基础

## 5.1 目标

让系统第一次稳定记住成功动作，而不是继续只强化失败记忆。

## 5.2 施工重点

这一步必须解决两个问题：

1. `on_action_executed()` 里怎么记录最小 success fact
2. sidecar 账本如何 append-only 落地

## 5.3 主要修改点

**建议涉及文件**：

1. `bridge_hook.py`
2. `agent_mem/integration/sweagent_adapter.py`
3. `agent_mem/storage/episode_ledger_store.py` 新增
4. `agent_mem/processing/action_logger.py`
5. `agent_mem/tests/`

## 5.4 任务拆分

### T1.1 新增 `EpisodeLedgerStore`

能力要求：

1. append-only 写入 JSONL
2. 支持统一 `append(event)` 接口
3. 返回 `written / record_id / skipped_reason`
4. 写失败不抛致命异常给在线主链

### T1.2 为 `on_action_executed()` 增加最小 success fact 采集

最小字段：

1. `instance_id`
2. `run_id`
3. `attempt_id`
4. `trace_id`
5. `step_index`
6. `action_text`
7. `success_like`
8. `timestamp`

并且必须同步落下：

1. 幂等键：`trace_id + step_index`
2. `success_like` 的统一判定 shared utility
3. 写失败降级为 telemetry 的分支

### T1.3 不新增新的公开事件类型

第一刀不引入新的公开 `action_success` 外部事件。  
热路径 success 记录优先直接写 sidecar 或内部 helper。

### T1.4 保留 `handle_action_success()` 作为内部 helper

可以扩充其参数，但不要求它立刻成为外部事件路由入口。

## 5.5 验收标准

1. 成功动作发生后，sidecar 中有最小 success event
2. sidecar 写失败时，主代理不受影响
3. 打开该功能开关后，旧 planning / error 提示链仍正常工作

## 5.6 测试点

1. `EpisodeLedgerStore.append()` 单测
2. `on_action_executed()` 成功路径单测
3. sidecar 写失败降级测试
4. v2.1 开关关闭回归测试

## 5.7 风险与缓解

**风险**：热路径开销膨胀  
**缓解**：只记录最小字段；不做 LLM、embedding、merge

---

## 6. Phase P2：`run_done` 增强与 projection candidate

## 6.1 目标

让 `run_done` 真正成为 v2.1 的 bootstrap 真值源，并产出 candidate 级的结构对象。

## 6.2 主要修改点

**建议涉及文件**：

1. `agent_mem/integration/sweagent_adapter.py`
2. `agent_mem/processing/extraction_orchestrator.py`
3. `agent_mem/processing/subtask_projector.py` 新增
4. `agent_mem/processing/subtask_edge_builder.py` 新增
5. `agent_mem/storage/episode_ledger_store.py`
6. `agent_mem/tests/`

## 6.3 任务拆分

### T2.1 扩展 `run_done_context`

逐步补齐：

1. `touched_files`
2. `diff_summary`
3. `validation_summary`
4. `patch_digest`
5. `task_closed_cleanly`

并且必须补一张字段来源表，写清：

1. 来源模块
2. 必填/选填
3. fallback
4. 写入位置

### T2.2 在 `handle_run_done()` 中生成 `success_fact_report`

需要回答：

1. 本次 attempt 是否采集到 success fact
2. 热路径与冷路径事实是否一致
3. 哪些字段是冷路径补齐的

### T2.3 新增 `SubtaskProjector`

输入：

1. `attempt_summary_v1`
2. `trial_overview`
3. `subblock_analysis`
4. `ProblemFile[]`
5. `run_done_context`

输出：

1. `SubtaskInstance[]`
2. `projection_report`

并且在这一阶段必须同步定义：

1. 解释性稳定指标
2. 决策性稳定指标
3. pass/fail 门槛
4. 不达标时只保留 sidecar candidate 的降级规则

### T2.4 新增 `SubtaskEdgeBuilder`

第一版只生成：

1. `PRECEDES`
2. `RETRY_OF`
3. `ALTERNATIVE_TO`

并只写：

1. `effectiveness_candidate`
2. `supporting_attempt_ids`

### T2.5 candidate 对象只进 sidecar

这一阶段不把 projected objects 放进默认主检索视图。

## 6.4 验收标准

1. `run_done` 能稳定返回 `success_fact_report`
2. 即使热路径没有记录成功事实，冷路径仍能补齐基础真值
3. `SubtaskProjector` 和 `SubtaskEdgeBuilder` 能在 sidecar 中产生 candidate 对象
4. candidate 对象不影响当前 retrieval 主链

## 6.5 测试点

1. `run_done` fallback summary 单测
2. `run_done_context` 补齐测试
3. `SubtaskProjector` 结构化输出测试
4. `SubtaskEdgeBuilder` 边类型测试
5. extraction timeout / projection error 降级测试

## 6.6 风险与缓解

**风险**：`projected_subtask` 解释性很强，但决策性不稳定  
**缓解**：本阶段只产 candidate，不提前进入注入主链

**新增实证风险结论**：如果把 `AGENT_MEM_ENABLE_LLM_EXTRACTION=0` 实现成“整个 orchestrator 关闭”，会误伤启发式 `attempt_summary_v1 / subblock_analysis`，从而让 `projected_subtask` 在真实回归场景下退化为 0。  
**当前修复**：即使 LLM extraction 关闭，也必须保留启发式 cold-path summary 构建。

---

## 7. Phase P3：CardCompiler v1 与注入接线

## 7.1 目标

让控制层开始消费统一 card，而不是继续让对象层直接驱动注入。

## 7.2 主要修改点

**建议涉及文件**：

1. `agent_mem/processing/card_compiler.py` 新增
2. `agent_mem/retrieval/memory_agent.py`
3. `bridge_hook.py`
4. `agent_mem/tests/`

## 7.3 任务拆分

### T3.1 新增 `CardCompiler`

v1 输入白名单：

1. `attempt_summary_v1`
2. `failure_card_v2`
3. `repair_pattern_v2`
4. `SubtaskInstance`

v1 输出白名单：

1. `PlanHintCard`
2. `SubtaskRiskCard`
3. `RetryHintCard`
4. `ClosureGuardCard`

### T3.2 为 card 设计最小统一字段

建议包含：

1. `card_id`
2. `card_type`
3. `hint`
4. `family_id`
5. `source_object_ids`
6. `confidence`
7. `promotion_state`
8. `evidence_level`

其中 `evidence_level` 必须固定在：

```text
local / attempt / official
```

### T3.3 `MemoryAgent` 接入 compiler cards

`MemoryAgent` 负责：

1. 召回
2. 去重
3. 预算内选取
4. 输出给 hook

### T3.4 `on_model_query()` 只消费 card

明确禁止：

1. raw subtask 直接注入
2. raw failure card 直接注入

## 7.4 验收标准

1. 打开 compiler 开关后，控制层能消费统一 card
2. card 数量受 `max_cards_per_query` 控制
3. family cooldown 仍有效
4. compiler 关闭时，旧 retrieval 仍可工作

## 7.5 测试点

1. `CardCompiler` 单测
2. card fingerprint 去重测试
3. `MemoryAgent` compiler 集成测试
4. `on_model_query()` 注入预算测试

## 7.6 风险与缓解

**风险**：噪声从对象层转移到 card 层  
**缓解**：输入白名单冻结；输出类型冻结；预算受控

---

## 8. Phase P4：Governance v1 与 official eval 受限写回

## 8.1 目标

把对象治理和最终信用闸门正式纳入主链，避免系统进入“对象越来越多、却没有生命周期”的状态。

## 8.2 主要修改点

**建议涉及文件**：

1. `agent_mem/processing/object_governance_policy.py` 新增
2. `agent_mem/processing/evaluation_feedback.py`
3. `agent_mem/integration/sweagent_adapter.py`
4. `agent_mem/storage/graph_store.py`
5. `agent_mem/tests/`

## 8.3 任务拆分

### T4.1 新增治理状态机

最小状态：

1. `candidate`
2. `promoted`
3. `suppressed`
4. `deprecated`

并且必须补一张权限表，写清：

1. 哪些模块可做 `candidate -> promoted`
2. 哪些模块可做 `candidate -> suppressed`
3. 哪些转移只能由 `ObjectGovernancePolicy` 执行
4. 哪些转移必须经过 `official_eval_feedback`

### T4.2 对现有对象加治理入口

至少纳入：

1. `abstract_experience`
2. `failure_card_v2`
3. `repair_pattern_v2`
4. `CompilerCard`

### T4.3 限制 official eval 写回边界

只允许直接推动：

1. `attempt_summary_v1.final_outcome`
2. governance 状态
3. `CompilerCard.promotion_state`
4. `SubtaskInstance.eval_context`
5. `SubtaskEdge.eval_support`

明确禁止：

1. 直接覆盖 `SubtaskInstance.local_result_status`
2. 直接声明最终因果边
3. 直接全量 promote 本次 attempt 所有对象

### T4.4 growth cap / merge / suppression

至少实现：

1. `failure_card_v2` 近重复合并
2. `repair_pattern_v2` growth cap
3. `CompilerCard` 去重与 suppression
4. pre-eval success guard

## 8.4 验收标准

1. candidate 对象都有明确状态
2. official eval 不再直接承担细粒度因果解释
3. unresolved / infra_failure / resolved 三类结果均有可解释写回
4. governance 失败时不会破坏已有稳定对象

## 8.5 测试点

1. 状态机合法转移测试
2. `official_eval_feedback` 写回边界测试
3. merge / suppression 测试
4. governance failure 降级测试

## 8.6 风险与缓解

**风险**：治理层成为新的复杂度中心  
**缓解**：只上最小状态机；避免第一版做过多策略化 heuristics

---

## 9. 验证门与实验计划

这部分不是“最后再补”，而是和施工同步进行。

## 9.1 Gate A：Success Fact Capture Gate

要回答：

1. 成功动作是否真的被稳定记录
2. 冷路径是否能补齐事实
3. success memory 是否不再明显弱于 failure memory

## 9.2 Gate B：Projected Subtask Stability Gate

要回答两件事：

1. 解释性稳定
2. 决策性稳定

至少看：

1. retry 成功率
2. retrieval sharpness
3. 注入噪声变化

## 9.3 Gate C：Compiler Noise Gate

要确认：

1. card 数量可控
2. card 重复率下降
3. card 的实际命中价值高于噪声增长

## 9.4 必做 ablation

至少拆四组：

1. 仅阶段6 控制层
2. 控制层 + success fact
3. 上述基础上 + projected_subtask
4. 上述基础上 + compiler/governance

---

## 10. 里程碑建议

## M1：主链无回归 + feature flags 完成

对应：P0  
完成标志：v2.1 能关、能开、能独立 smoke test

## M2：success fact 热/冷双轨完成

对应：P1 + P2 前半  
完成标志：`success_fact_report` 可用

## M3：sidecar projection candidate 完成

对应：P2 后半  
完成标志：`SubtaskInstance / SubtaskEdge` 出现在 sidecar

## M4：compiler card 注入闭环完成

对应：P3  
完成标志：hook 开始消费统一 card

## M5：governance + official eval 受限写回完成

对应：P4  
完成标志：状态机、promotion/suppression 和 ablation 跑通

---

## 11. 施工期间明确禁止事项

1. 不要先做 `declared_subtask`
2. 不要先做 `Path / Prototype / Skill`
3. 不要在热路径上做 LLM 深分析
4. 不要让 sidecar 对主代理形成硬依赖
5. 不要让 official eval 直接写穿 local subtask 结果
6. 不要为了新模块先重构整个目录树

---

## 12. 回滚与兼容策略

## 12.1 配置级回滚

所有 v2.1 新能力必须支持 feature flag 关闭。

## 12.2 数据级回滚

1. sidecar 是 append-only，可直接停读
2. `GraphStore` 仍保留阶段6 可工作对象
3. compiler / governance 关闭后，旧 retrieval 应继续工作

## 12.3 行为级回滚

1. 关闭 success fact hotpath
2. 关闭 sidecar
3. 关闭 projection
4. 关闭 compiler
5. 关闭 governance

---

## 13. 一句话施工结论

**AgentMem v2.1 的升级，不应该按“先发明更多对象”的方式推进，而应该按“先补成功事实，再长 sidecar，再做 candidate projection，再统一 card，最后再治理和 official eval 写回”的顺序推进。**

**只要这个顺序守住，当前框架就能在不破坏阶段6 主链的前提下，逐步长成真正可验证的长期记忆系统。**

---

## 14. 当前重测前检查结论

在正式启动 repeat-run 重测前，需要额外确认两件 SWEAgent 侧事项：

1. Hook 接口层不需要新增事件类型，当前 `ExternalToolBridgeHook` 已经覆盖：
   - `plan_generated`
   - `action_error`
   - `run_done`
   - `on_action_executed()` 热路径 success fact
   - `on_model_query()` compiler card 注入
2. 但实验启动层还需要显式管理 `AGENT_MEM_V21_*` 开关，避免“代码已经支持、脚本没有暴露”的隐性偏差。
3. prompt 侧升级不是 v2.1 生效的前置条件；第一次重测应优先保持基线 prompt 不变，先验证 memory 框架更新本身。
4. 如果要做 prompt 升级，必须以独立 prompt profile 落地，和 v2.1 flags 正交控制，便于做 2x2 消融。
