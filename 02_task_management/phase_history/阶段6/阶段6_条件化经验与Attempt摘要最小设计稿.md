# 阶段6：条件化经验与 Attempt 摘要最小设计稿

## 1. 设计目标

本设计稿的目标不是一次性重做整个 AgentMem，而是在当前框架基础上，用最小增量补齐四个最关键但当前缺失的能力：

1. `attempt_summary_v1`
2. `subproblem_type`
3. `strategy_label`
4. `prefer_actions / avoid_actions`

这四项能力的共同目标是：

- 不再只在 attempt 结束后得到一个粗粒度的全局失败标签；
- 能够把一次长轨迹压缩成下一轮可以直接消费的高密度经验；
- 能够把“失败”具体到某个子问题与某类动作路径；
- 能够把经验表达从抽象建议升级为可执行约束。

本设计稿遵循以下原则：

- 不引入新数据库；
- 不重写现有 graph_store；
- 不把系统做成通用 RCA 平台；
- 优先复用现有 `abstract_experience / failure_card_v2 / repair_pattern_v2 / preventive_rule_v2`；
- 新增对象和字段必须能直接服务于后续注入与行为约束。

---

## 2. 为什么要做这四项，而不是继续扩抽象经验

当前系统已经具备：

- 抽象经验提取；
- failure card / repair pattern / preventive rule；
- official eval feedback 回流；
- family 聚合；
- 粗粒度负经验在后续 attempt 中被读取。

但当前仍然存在三个核心缺陷：

1. 失败信息太粗，只知道 `unresolved / incomplete / over_exploration`；
2. 经验没有稳定绑定到具体子问题和具体策略路径；
3. 下一次 attempt 读到的是零散经验，而不是对上一次尝试的整体理解。

因此，这一轮不应该继续增加更多“抽象经验类型”，而应该先让经验表达具备以下能力：

- 这条经验属于哪个子问题；
- 这条经验来自哪类策略路径；
- 这条经验推荐做什么、避免做什么；
- 这次 attempt 的整体结论是什么，应该如何压缩传给下一轮。

---

## 3. 最小设计范围

### 3.1 In Scope

本轮只做以下对象与流程：

1. `attempt_summary_v1`
2. 在现有经验对象中增加：
   - `subproblem_type`
   - `strategy_label`
   - `prefer_actions`
   - `avoid_actions`
   - `applicability_scope`
3. 在提取流程中增加：
   - 最小版 `trial_overview`
   - 最小版 `subblock_analysis`
4. 在检索/注入中优先消费：
   - `attempt_summary_v1`
   - 与当前 `subproblem_type` 匹配的经验

### 3.2 Out of Scope

本轮不做：

- 通用图归因系统；
- 全自动精细 action-level causal attribution；
- 新的外部数据库；
- 大模型主导的全轨迹逐步归因器；
- 对 SWE-agent 主决策器的大规模侵入式重构。

---

## 4. 新对象一：`attempt_summary_v1`

### 4.1 设计动机

当前跨 attempt 继承的主要是碎片经验对象。它们有用，但不足以让下一轮一开始就理解：

- 上一轮想做什么；
- 实际做了什么；
- 哪些部分确认了；
- 哪些部分失败了；
- 哪些路线不该再走；
- 下一轮最值得先做什么。

因此需要一个高密度、结构化、可直接注入的尝试摘要对象。

### 4.2 最小字段设计

```json
{
  "schema_version": "1.0",
  "summary_id": "uuid",
  "instance_id": "astropy__astropy-11693",
  "run_id": "...",
  "attempt_id": "attempt-01",
  "problem_goal": "要解决什么问题",
  "initial_plan_outline": ["计划主步骤1", "计划主步骤2"],
  "actual_execution_outline": ["实际主步骤1", "实际主步骤2"],
  "plan_success": false,
  "final_outcome": "incomplete",
  "confirmed_signals": ["quiet=True 路径可返回结果"],
  "failed_strategies": [
    {
      "subproblem_type": "reproduce_issue",
      "strategy_label": "ad_hoc_repro_script_loop",
      "reason": "created multiple scripts without converging to fix"
    }
  ],
  "best_partial_progress": ["定位到 world_to_pixel_values / all_world2pix 行为差异"],
  "unverified_hypotheses": ["是否只需要最小 quiet 参数路径修复"],
  "next_best_actions": ["直接围绕最小 patch 做 target validation"],
  "source_action_ids": ["..."],
  "created_at": "..."
}
```

### 4.3 设计约束

- 只能保留高密度信息，不保留原始长链；
- 只能保留 1 份当前 attempt 摘要，不复制整份 traj；
- 该对象只为下一轮 attempt 的“开场 briefing”服务，不直接替代细粒度经验对象。

### 4.4 存储方式

建议先放在现有 `graph_store` 同目录下新文件：

- `attempt_summaries_v1.json`

键为 `summary_id`，值为对象内容。

---

## 5. 新字段一：`subproblem_type`

### 5.1 设计动机

如果不知道经验属于哪个子问题，就无法在相似子问题里稳定复用或规避。

### 5.2 最小枚举集合

初版固定少量稳定集合，避免过早扩散：

- `reproduce_issue`
- `localize_fix`
- `form_minimal_patch`
- `target_validation`
- `broad_regression_check`
- `tool_recovery`
- `unknown`

### 5.3 放置位置

先补到以下对象：

- `abstract_experience`
- `failure_card_v2.metadata`
- `repair_pattern_v2.metadata`
- `preventive_rule_v2.metadata`
- `attempt_summary_v1.failed_strategies[*]`

### 5.4 提取方式

最小版不做复杂模型推理，先基于规则与轨迹阶段信号归类：

- 新建 repro 脚本、运行复现命令：`reproduce_issue`
- grep / open files / read target code：`localize_fix`
- edit target file：`form_minimal_patch`
- 跑目标测试：`target_validation`
- 跑 broader test suite：`broad_regression_check`
- 工具故障恢复：`tool_recovery`

---

## 6. 新字段二：`strategy_label`

### 6.1 设计动机

即使知道子问题是 `reproduce_issue`，还不足以指导后续 agent。还需要知道在这个子问题里走的是哪条路径。

### 6.2 初版 strategy label 集合

初版用少量、高价值、可稳定识别的标签：

- `ad_hoc_repro_script_loop`
- `single_repro_then_target_check`
- `cross_module_expansion_after_key_signal`
- `broad_test_without_patch`
- `minimal_patch_then_target_validation`
- `api_alternative_probe_without_fix`
- `tool_recovery_retry_loop`
- `unknown_strategy`

### 6.3 放置位置

先补到以下对象：

- `abstract_experience`
- `failure_card_v2.metadata`
- `repair_pattern_v2.trigger_signature`
- `attempt_summary_v1.failed_strategies[*]`

### 6.4 识别方式

初版仍然以规则为主：

- 多个 `test_*.py / reproduce_*.py` 且没有 patch：`ad_hoc_repro_script_loop`
- 已见 key signal 后仍扩大到无关模块：`cross_module_expansion_after_key_signal`
- 未形成 patch 就跑广泛测试：`broad_test_without_patch`
- 围绕目标文件直接编辑后只跑目标测试：`minimal_patch_then_target_validation`

---

## 7. 新字段三：`prefer_actions / avoid_actions`

### 7.1 设计动机

经验如果只是抽象建议，Agent 很难真正执行。必须把经验转成可执行条目。

### 7.2 最小字段设计

```json
{
  "prefer_actions": [
    "run_target_validation_before_broad_tests",
    "edit_target_function_before_new_repro_script"
  ],
  "avoid_actions": [
    "create_new_repro_script_after_key_signal",
    "expand_search_to_unrelated_module_after_localization"
  ]
}
```

### 7.3 放置位置

建议先放在：

- `abstract_experience.metadata`
- `failure_card_v2.candidate_fix_actions`（偏 prefer）
- `attempt_summary_v1.next_best_actions`
- 新增 `attempt_summary_v1.failed_strategies[*].avoid_actions`

### 7.4 设计约束

- action 语义必须是归一化标签，不直接存原始命令；
- 原始命令只作为 evidence，不直接作为注入内容；
- `prefer/avoid` 初版只支持少量高价值动作模板。

---

## 8. 最小版 `trial_overview`

### 8.1 设计动机

具体提经验前，必须先形成对整条 trial 的最小理解。

### 8.2 最小输出

`trial_overview` 初版只回答 5 个问题：

1. 目标是什么？
2. 初始计划主链是什么？
3. 实际执行主链是什么？
4. 关键偏航点是什么？
5. 最终结果是什么？

### 8.3 最小结构

```json
{
  "problem_goal": "...",
  "initial_plan_outline": ["..."],
  "actual_execution_outline": ["..."],
  "key_divergences": ["..."],
  "final_outcome": "incomplete"
}
```

### 8.4 生成时机

- 优先在 attempt 结束后生成；
- 在 official eval feedback 之前或之后都可以，但建议在 feedback 后补 outcome。

---

## 9. 最小版 `subblock_analysis`

### 9.1 设计动机

trial_overview 解决“整体理解”，subblock_analysis 解决“为什么失败”。

### 9.2 子块切分原则

初版不要做复杂自动分段，按语义阶段切：

- reproduce
- localize
- patch
- validation
- fallback / drift

### 9.3 每个子块的最小结构

```json
{
  "subproblem_type": "reproduce_issue",
  "goal": "稳定复现问题",
  "is_goal_necessary": true,
  "plan_role": "required",
  "plan_success": false,
  "execution_paths": ["ad_hoc_repro_script_loop"],
  "key_actions": ["action_12", "action_13"],
  "positive_contribution": [],
  "negative_contribution": ["created multiple scripts without narrowing fix path"],
  "failure_source": "execution",
  "prefer_actions": ["reuse_confirmed_repro_path"],
  "avoid_actions": ["create_new_repro_script_after_repro_confirmed"]
}
```

### 9.4 初版限制

- 不做多层因果图；
- 不做复杂分数传播；
- 只输出：
  - goal
  - whether necessary
  - plan success
  - failure source (plan / execution / mixed)
  - prefer/avoid

---

## 10. 提取流程最小改造方案

### 10.1 当前流程

当前流程大致是：

1. actions 结束
2. LLM/规则提取 assessments
3. detect critical signals
4. map 到 abstract experience / failure card / repair pattern
5. 写 graph_store
6. official eval feedback 回流

### 10.2 目标流程

最小改造后应变成：

1. actions 结束
2. 生成 `trial_overview`
3. 基于 `trial_overview` 生成 `subblock_analysis`
4. 从 `subblock_analysis` 中提炼：
   - `subproblem_type`
   - `strategy_label`
   - `prefer_actions`
   - `avoid_actions`
5. 写入：
   - 细粒度经验对象
   - `attempt_summary_v1`
6. official eval feedback 回流后：
   - 补 outcome
   - promote / suppress
   - 更新 attempt summary 的 outcome 段

### 10.3 为什么这个流程可行

因为它不推翻当前系统，只是在 `run_done -> 提经验` 之间加两层薄分析：

- `trial_overview`
- `subblock_analysis`

并在已有经验对象上补几个关键字段。

---

## 11. 注入侧最小消费方案

### 11.1 `attempt_summary_v1` 的消费位置

建议只在新的 attempt 开始时使用一次，作为 briefing，不要在每一步都反复注入。

### 11.2 条件化经验的消费位置

在 planning/retrieval 阶段，优先匹配：

- 当前 `subproblem_type`
- 当前 `strategy_label`
- 当前 `applicability_scope`

### 11.3 行为约束

如果经验中有：
- `avoid_actions`

则可用于：

1. retrieval 降权；
2. runtime guard 软阻断；
3. 注入层显式提示。

初版优先做 1 和 2，不要只做抽象提示。

---

## 12. 测试口径

### 12.1 单测

要覆盖：

- `subproblem_type` 分类规则
- `strategy_label` 识别规则
- `attempt_summary_v1` 序列化与更新
- `prefer_actions / avoid_actions` 生成逻辑

### 12.2 集成测试

要覆盖：

- run_done 后是否生成 `attempt_summary_v1`
- official eval feedback 后是否更新 outcome
- 后续 attempt 是否读取到 summary
- 后续 retrieval 是否根据 `subproblem_type/strategy_label` 过滤经验

### 12.3 冒烟测试

建议继续用单实例 repeat5 实验验证：

- attempt2 是否读取 attempt1 的 summary
- attempt3 以后是否减少重复失败路径
- 是否不再只是重复增加 `support_count`

---

## 13. 第一批施工优先级

### P0

1. 新增 `attempt_summary_v1`
2. 给 `abstract_experience` 补：
   - `subproblem_type`
   - `strategy_label`
   - `prefer_actions`
   - `avoid_actions`
3. 新增最小版 `trial_overview`
4. 新增最小版 `subblock_analysis`

### P1

5. retrieval 根据 `subproblem_type/strategy_label` 做匹配
6. runtime guard 消费 `avoid_actions`
7. official eval feedback 更新 `attempt_summary_v1`

### P2

8. 更细的 plan vs execution 判断
9. 更丰富的 local progress signals
10. 更稳定的 strategy family 聚合

---

## 14. 结论

当前系统已经具备：

- 粗粒度经验提取；
- 粗粒度负经验回流；
- 跨 attempt 继承；
- family 聚合；
- official eval 绑定。

但它还不具备：

- 子问题级经验；
- 路径级失败表达；
- 可执行的 prefer/avoid 动作约束；
- 高密度的 attempt 摘要传递。

因此，下一阶段不应继续只扩抽象经验类型，而应优先补齐：

1. `attempt_summary_v1`
2. `subproblem_type`
3. `strategy_label`
4. `prefer_actions / avoid_actions`
5. 最小版 `trial_overview + subblock_analysis`

只有这样，AgentMem 才有可能从“记住失败”升级为“理解失败，并在下一次更有针对性地改变行为”。
