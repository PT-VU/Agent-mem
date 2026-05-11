# 同题测试分析：phase7_formal_parallel_003

## 1. 分析范围

本分析只覆盖阶段7最终验证中的“同题”部分，即同一个实例 `astropy__astropy-14182` 的两条实验线：

- `NoMem`：`same_problem/nomem`
- `WithMem`：`same_problem/phase7_formal_parallel_003/candidates/astropy__astropy-14182`

本次分析目标有三点：

1. 判断当前 `AgentMem v2.1` 在同题 repeat 测试上是否提升了解题正确率。
2. 判断它是否帮助 agent 更早找到正确路径，或更稳定地复用成功路径。
3. 判断当前记忆系统到底真实做了什么，而不是只看开关是否打开。

## 2. 数据来源

主要证据来自以下产物：

- `metrics/attempt_summaries.json`
- `metrics/attempt_summaries/*.summary.json`
- `metrics/attempt_feedback/*.feedback.json`
- `metrics/attempt_reports/*.official_eval.json`
- `logs/*.log`
- `logs/*.jsonl`
- `outputs/*/preds.json`
- `persistence/graph_store/*`
- `persistence/sidecar_store/*`

## 3. 结论摘要

### 3.1 总体结论

截止当前这轮正式验证，**同题维度上，`v2.1 WithMem` 没有表现出相对 `NoMem` 的整体优势**。

直接结论如下：

- `NoMem`：`2/10` resolved
- `WithMem`：`1/10` resolved，另有 `1/10` incomplete
- `NoMem` 第 `1` 次尝试就成功
- `WithMem` 直到第 `10` 次尝试才成功

这说明在“同一个问题的多次重复求解”这个维度上，当前 `AgentMem v2.1` **还没有证明它能更早找到正确路径，也没有证明它能提高同题成功率**。

### 3.2 但这不等于记忆系统没工作

`WithMem` 并不是“没生效”，恰恰相反，它在这轮实验里：

- 明确积累了经验对象
- 明确执行了记忆检索
- 明确进行了提示注入
- 明确对最终成功的 `attempt_10` 施加了计划类和 retry 类干预

所以当前更准确的判断是：

> **记忆系统已经在工作，但在这次同题实验里，它更多表现为“晚期收敛辅助器”，而不是“提前找到正确路径的加速器”。**

## 4. 结果对比

### 4.1 核心指标对比

| 指标 | NoMem | WithMem | 结论 |
|---|---:|---:|---|
| 总尝试数 | 10 | 10 | 持平 |
| resolved 次数 | 2 | 1 | NoMem 更好 |
| unresolved 次数 | 8 | 8 | 持平 |
| incomplete 次数 | 0 | 1 | WithMem 更差 |
| 首次成功 attempt | 1 | 10 | NoMem 明显更好 |
| 首次成功前失败次数 | 0 | 8 + 1 incomplete | WithMem 明显更差 |
| 成功路径复现 | 第 8 次再次成功 | 无后续复现机会 | NoMem 更好 |

### 4.2 NoMem 逐轮结果

| Attempt | official eval | 最大 step | 备注 |
|---|---|---:|---|
| 01 | resolved | 113 | 首次成功 |
| 02 | unresolved | 91 | 失败 |
| 03 | unresolved | 118 | 失败 |
| 04 | unresolved | 102 | 失败 |
| 05 | unresolved | 100 | 失败 |
| 06 | unresolved | 96 | 失败 |
| 07 | unresolved | 73 | 失败 |
| 08 | resolved | 97 | 再次成功 |
| 09 | unresolved | 91 | 失败 |
| 10 | unresolved | 112 | 失败 |

### 4.3 WithMem 逐轮结果

| Attempt | official eval / feedback | 最大 step | 备注 |
|---|---|---:|---|
| 01 | unresolved | 108 | 失败 |
| 02 | unresolved | 116 | 失败 |
| 03 | unresolved | 89 | 失败 |
| 04 | unresolved | 105 | 失败 |
| 05 | unresolved | 93 | 失败 |
| 06 | unresolved | 96 | 失败 |
| 07 | unresolved | 109 | 失败 |
| 08 | incomplete | 0 | 非完整尝试，不能等同普通失败 |
| 09 | unresolved | 103 | 失败 |
| 10 | resolved | 88 | 最终成功 |

## 5. 路径探索分析

### 5.1 两条线都没有“乱改很多文件”

一个很重要的事实是：**两条线 10 次尝试里，所有最终 patch 都集中在同一个文件**：

- `astropy/io/ascii/rst.py`

这说明：

- agent 在问题定位上总体是收敛的
- 这轮实验的主要区别，不是“有没有跑偏到别的模块”
- 差异主要出在：**对同一目标文件的修复路径选择、验证纪律和收敛速度**

### 5.2 两条线都在探索不同 patch 变体

按 `preds.json` 中 `model_patch` 的哈希来看：

- `NoMem` 的 10 个 attempt 对应 10 个不同 patch 指纹
- `WithMem` 的 9 个有效 attempt 也对应 9 个不同 patch 指纹

因此当前同题实验的现象不是“每次都重复同一错误 patch”，而是：

> **两条线都在探索不同修复变体，但 `WithMem` 没有把探索更快地收敛到正确变体。**

### 5.3 最终成功路径与早期成功路径有明显同族性

从 patch 内容看：

- `NoMem attempt_01` 的成功 patch 已经抓住了两个核心方向：
  - `RST.__init__` 支持 `header_rows`
  - `data.start_line` 需要随 `header_rows` 变化

- `WithMem attempt_10` 的成功 patch 也收敛到了相近的修复家族：
  - 给 `RST.__init__` 增加 `header_rows`
  - 重新计算 position/data 起始位置

这说明：

> **WithMem 最终不是找到了一条全新的成功路径，而是晚于 NoMem 才收敛到同一类正确修法。**

## 6. 记忆系统行为证据

### 6.1 记忆积累是真实发生的

`WithMem` 的 persistence 产物规模如下：

| 对象 | 数量 |
|---|---:|
| `failure_cards_v2.json` | 8 |
| `repair_patterns_v2.json` | 63 |
| `compiler_cards_v21.json` | 20 |
| `episode_ledger.jsonl` | 124 行 |
| `subtask_instances.jsonl` | 41 行 |
| `subtask_edges.jsonl` | 41 行 |
| `compiler_cards.jsonl` | 36 行 |

这足以说明：

- 失败经验被沉淀了
- 修复模式被沉淀了
- sidecar 长期层也被真实写入了
- compiler/gov 路径不是空转

进一步看内容，当前提取出来的经验大致分成三类：

1. **失败经验**
   - 典型 failure card 都来自 `official_eval_feedback`
   - 核心内容几乎都在强调：
     - 先复现实验路径
     - 用 target validation 验证修补
     - 不要直接继续堆 patch

2. **修复模式经验**
   - 当前最强的一组 repair pattern，几乎都围绕同一个主题：
     - planning 阶段出现 `constraint_ignorance`
     - 计划里缺测试、缺验证、缺成功判据
   - 典型内容包括：
     - 计划里显式加入 verification/testing
     - retry 前做 constraint ignorance precheck
     - 为 RST 相关修复建立正式 test plan

3. **编译后的提示卡经验**
   - 已经出现的 card 类型主要是：
     - `PlanHintCard`
     - `RetryHintCard`
     - `ClosureGuardCard`
   - 当前最有代表性的 family 包括：
     - `plan_hint__...__reuse_confirmed_repro_path`
     - `repair_pattern__...__add_precheck_for_constraint_ignorance_before_retry`
     - `closure_guard__...__the_subproblem_consumed_effort_without_producing_a_verifiable_local_improvement`

这意味着当前同题记忆系统抽出来的“经验内容”，并不是代码语义层面的 bug invariant，而主要是：

- 失败后如何收敛
- 计划里如何补验证
- 什么时候该停止继续发散

### 6.2 记忆注入是真实发生的，而且强度不低

`WithMem` 各 attempt 的 `jsonl` 日志统计如下：

| Attempt | memory_injected | memory_hint_buffered | proactive_trigger |
|---|---:|---:|---:|
| 01 | 1 | 0 | 83 |
| 02 | 5 | 3 | 91 |
| 03 | 5 | 4 | 72 |
| 04 | 6 | 5 | 77 |
| 05 | 4 | 3 | 61 |
| 06 | 5 | 5 | 83 |
| 07 | 6 | 5 | 85 |
| 08 | 0 | 0 | 0 |
| 09 | 8 | 7 | 75 |
| 10 | 7 | 6 | 77 |

这说明：

- `WithMem` 不是“偶尔插一条提示”
- 它是持续、多轮地介入了 planning/retry 流程
- 尤其在后期 attempt（09、10），注入频率明显更高

如果把注入内容本身再往下拆，当前真正被塞回 agent 的经验主要也是三类：

1. **风险规避类**
   - `patch_risk__official_eval_unresolved__avoid_repeat_failed_strategy`
   - `negative_strategy__official_eval_unresolved__avoid_repeat_failed_strategy`
   - `validation_gap__missing_validation__avoid_repeat_failed_strategy`

2. **计划/验证纪律类**
   - 多条 `repair_pattern__...verification...`
   - 多条 `repair_pattern__...test_plan...`
   - `failure_card:evaluation_unresolved:reproduce_the_failing_path_with_target_validation_before_next_patch`

3. **成功路径复用类**
   - `attempt_summary:astropy__astropy-14182`
   - `plan_hint__astropy_astropy_14182__reuse_confirmed_repro_path`

其中第三类最关键，因为它是最接近“同题经验复用”目标的内容；但从这次结果看，它出现得还不够早，也不够强。

### 6.3 注入时机：当前几乎都在 plan_generated 阶段发生

按 `memory_hint_buffered` 事件看，`attempt_02` 到 `attempt_10` 的 buffer source event 基本都是：

- `plan_generated`

也就是说，当前同题记忆注入的默认主时机并不是：

- action 执行后
- error 出现后
- submit 前单独重写策略

而是：

> **每轮 plan 生成之后，由外部工具检索结果把经验先 buffer，再由 hook 选择性注入。**

这一点很重要，因为它说明当前 AgentMem 的主作用点更偏：

- planning discipline
- retry planning
- pre-action steering

而不是：

- action-level correction
- low-level edit-time steering

### 6.4 时机判定：触发条件主要来自文件访问和过度探索

同题 `WithMem` 里，注入时机不是纯随机的，主要由这些 trigger 判定：

1. **早期定位触发**
   - `first_file_access:rst.py`
   - `first_file_access:fixedwidth.py`
   - `first_file_access:test_rst.py`
   - `first_file_access:test_fixedwidth.py`
   - `first_file_access:reproduce_error.py`

2. **中后期发散控制触发**
   - `over_exploration:*`
   - `before_test_run`
   - `before_submit`

这说明当前系统的时机策略是：

- 一旦 agent 开始接触核心源码/测试文件，就提前提醒
- 一旦 agent 出现过度探索倾向，就加 closure / retry / verification 类约束
- 在 test run 和 submit 前，再给一次纪律型提示

### 6.5 时机判定结果：每轮都有 gate，但 gate 其实没通过

每个有效 `WithMem` attempt 的 `jsonl` 末尾都记录了 `memory_gate_evaluation`。  
这一轮同题实验的一个非常关键的事实是：

- `external_ratio` 基本都通过
- `buffer_ratio` 基本都没通过
- `action_error_coverage` 也没通过
- `passed` 基本都是 `false`

但同时：

- `hard_fail_enabled = false`

这意味着当前策略是：

> **即使 gate 没通过，记忆对象仍然继续保留为 candidate，并继续参与后续编译/注入。**

这对后续分析很重要，因为它解释了为什么：

- 记忆系统越来越活跃
- 但收益没有同步闭合

当前不是“没有时机判定”，而是：

- 有时机判定
- 但 gate 还没有真正承担强过滤职责

### 6.6 按时间顺序看，同题记忆行为可以概括成三段

1. **attempt_01：几乎没有真正经验积累，只做了 closure 约束**
   - `memory_hint_buffered = 0`
   - `memory_injected = 1`
   - 注入内容主要是：
     - `closure_signal:over_exploration_after_key_signal`
   - 这说明第一轮更多是在“控发散”，不是在“复用旧经验”

2. **attempt_02 ~ attempt_07：开始稳定积累失败经验，并在 planning 阶段持续回灌**
   - `memory_hint_buffered` 稳定出现
   - `memory_injected` 保持在 4~6 次区间
   - 主要内容是：
     - unresolved 风险提醒
     - 缺验证提醒
     - planning 里补测试计划
     - retry 前做 precheck
     - reuse confirmed repro path

3. **attempt_09 ~ attempt_10：注入强度达到高位，最终 attempt_10 成功**
   - `attempt_09`: `memory_injected = 8`
   - `attempt_10`: `memory_injected = 7`
   - attempt_10 在第 1、2、3、4、5、19 步都能看到明确的记忆注入
   - 其中真正值得关注的是：
     - step 1 就注入了 `patch_risk + validation_gap + attempt_summary`
     - step 2 就出现了 `reuse_confirmed_repro_path`
     - step 19 出现了 `closure_signal`

这说明最终成功 attempt 不是“裸成功”，而是明确处在：

- 计划约束
- 失败复盘
- repro path 复用
- 发散控制

这四条记忆力量的共同作用之下。

### 6.7 最终成功的 attempt_10 确实吃到了关键记忆

`attempt_10` 的 `memory_injected` 明确包含这些 family：

- `patch_risk__official_eval_unresolved__avoid_repeat_failed_strategy`
- `validation_gap__missing_validation__avoid_repeat_failed_strategy`
- `attempt_summary:astropy__astropy-14182`
- 多条 `repair_pattern__...verification...`
- `plan_hint__astropy_astropy_14182__reuse_confirmed_repro_path`
- `failure_card:evaluation_unresolved:reproduce_the_failing_path_with_target_validation_before_next_patch`

这说明在最终成功前，系统至少做了三件有意义的事：

1. 提醒不要重复 unresolved 的旧策略
2. 强化“先做验证/复现，再继续改”的纪律
3. 开始尝试复用已确认的 repro path

但同样要指出一个很关键的限制：

- 这些注入多数仍然是“纪律型”和“风险规避型”
- 不是足够锋利的“成功代码不变量提示”

所以当前同题记忆系统更像是：

- 让 agent 少犯重复错误
- 让 agent 在晚期更容易收敛

还不像是：

- 在前几轮就把正确修法更早推到台前

## 7. AgentMem 当前在同题上的积极作用

虽然这次同题总结果没有赢过 `NoMem`，但当前系统已经表现出几个明确的正向作用：

### 7.1 它能持续积累问题相关经验，而不是只做一次性提示

同一实例跑到后期时，系统已经积累出：

- attempt summary
- failure card
- repair pattern
- compiler card
- subtask/edge sidecar 对象

这说明 v2.1 的长期层不是空壳。

### 7.2 它能把失败经验重新注入到后续尝试

最终成功的 `attempt_10` 不再是“裸跑”，而是带着前面失败 attempt 的约束和验证提示继续求解。

这是 AgentMem 当前最明确的积极作用：

> **它已经具备“把过去失败转成后续提示”的能力。**

### 7.3 它在后期确实有助于收敛

虽然没能让首次成功更早出现，但最终成功并不是随机撞上，而是伴随着：

- plan hint 注入
- failure card 注入
- repair pattern 注入
- repro/validation 纪律强化

因此当前更合理的表述是：

> **AgentMem 对同题的帮助，目前更偏向“晚期收敛辅助”和“避免继续盲试”，而不是“显著提前找到正确路径”。**

## 8. 当前主要问题

### 8.1 同题收益尚未建立

这是最核心的问题。  
如果只看同题 repeat 结果，当前版本还不能说：

- 正确率更高
- 首次成功更早
- 成功路径复用更强

这三个目标目前都没有成立。

### 8.2 记忆信号偏重“纪律化”，偏弱“关键代码不变量”

从实际注入的 family 看，当前记忆更强的是：

- 避免重复失败
- 强化测试/验证计划
- 限制过度探索

但偏弱的是：

- 把这个 bug 的决定性代码规律压成更短、更强、更稳定的成功卡

所以现在的记忆更像：

- 搜索纪律控制器
- retry 提示器
- validation 强化器

还不像：

- 已经真正学会该题关键修复不变量的“成功策略记忆器”

### 8.3 记忆强度上升了，但收益没有同步上升

后期 attempt 的 `memory_injected` 数量明显更多，但结果并没有形成持续成功。

这说明当前一个真实风险是：

> **记忆系统正在变“更活跃”，但还没有证明它因此变“更有效”。**

## 9. 阶段性判断

当前这轮正式验证在“同题”维度上的判断可以收敛为一句话：

> **AgentMem v2.1 已经具备真实的经验积累、经验注入和晚期收敛辅助能力，但在同题 repeat 场景里，尚未证明它能提升整体正确率、提前首次成功，或稳定复用成功路径。**

再直白一点：

- 体系已经在工作
- 价值还没有在同题指标上闭合

## 10. 建议的下一步

建议后续针对同题维度优先做三件事：

1. **压缩成功卡**
   - 不要只沉淀“避免失败”和“加强验证”
   - 要把最终成功 patch 的关键不变量压成更短、更硬的成功提示

2. **降低过强的后期纪律噪声**
   - 当前 `proactive_trigger` 和 retry/validation 类提示很多
   - 需要防止“提示越来越多，但关键成功信息不够锋利”

3. **单独验证 success-path promotion**
   - 当前最应该补的不是更多对象
   - 而是把 resolved attempt 的成功路径更稳定地 promote 成后续可复用的 card
