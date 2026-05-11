# AgentMem v2.1 单题 Repeat10 实验分析

## 1. 范围与证据

- 当前实验 run root:
  `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/with_mem/auto_selected_failedcase_runs/lite_failedcase_repeat10_withmem_v21_promptbase_20260315_121537`
- 单题实例:
  `astropy__astropy-14182`
- 实验配置:
  - `prompt_profile = prompt_base`
  - `model_config = /home/pt/SWE-bench/SWE-agent/config/deepseek.yaml`
  - `v21_enable_success_fact_hotpath = 1`
  - `v21_enable_sidecar = 1`
  - `v21_enable_subtask_projection = 1`
  - `v21_enable_card_compiler = 1`
  - `v21_enable_governance = 1`
- 对照基线:
  `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/with_mem/auto_selected_failedcase_runs/lite_failedcase_repeat10_live_20260312_150158/notes/AgentMem_repeat10_analysis_2026-03-13.md`
- 核心证据文件:
  - `metrics/attempt_summaries.json`
  - `metrics/attempt_reports/*.official_eval.json`
  - `metrics/attempt_feedback/*.feedback.json`
  - `logs/*.jsonl`
  - `persistence/graph_store/*`
  - `persistence/sidecar_store/*`

## 2. 结论先行

### 2.1 本次更新后，单题正确率有提升

对同一个实例 `astropy__astropy-14182`:

- 旧版 repeat10:
  - `2 / 10` resolved
  - resolved attempts: `2, 7`
- 当前 v2.1 repeat10:
  - `4 / 10` resolved
  - resolved attempts: `1, 4, 5, 9`
  - unresolved attempts: `2, 3, 6, 7, 10`
  - incomplete attempts: `8`

因此，在这个单题上，**官方评测成功率从 20% 提升到 40%**。

这个结论可以成立，但边界也要写清楚:

1. 这只是单题结果，不足以直接外推为全局正确率提升。
2. `attempt_01` 就已经 resolved，说明这次 run 本身的初始采样也更好；因此不能把全部提升都归因给“记忆积累”。
3. 真正能归因给 AgentMem 的，是后续 attempts 中成功路径被重新找到的频率和方式。

### 2.2 AgentMem 对 agent 思路是有帮助的，但帮助主要还在“搜索纪律”和“验证路径复用”，不是“代码级不变量固化”

本轮最重要的判断是：

- **帮助是存在的**
- **帮助类型是偏 workflow / validation / repro reuse**
- **还没有稳定升级成 bug-specific invariant transfer**

更直白一点：

1. 系统现在比之前更能把 agent 拉回“先复用已确认的 repro path，再做 targeted validation”的轨道。
2. 系统也更能抑制无意义扩散，比如 ad-hoc script 蔓延、过度探索、重复 broad patch。
3. 但系统还没有把这个 bug 的决定性代码语义稳定记成一句可复用规则，例如：
   - `RST` 需要动态 `data.start_line`
   - `separator line` 的索引必须跟 `header_rows` 联动
   - `SimpleRSTData.start_line = 3` 是需要移除或动态化的旧假设

所以当前 AgentMem 的作用是：

- **让 agent 更容易回到正确的解题路径**
- 但还**不能保证 agent 持久地“懂了这个 bug 的核心修法”**

## 3. 结果总览

### 3.1 attempt 结果表

| Attempt | Official Eval | 主要 patch 路径 | Memory 注入次数 | 判断 |
| --- | --- | --- | ---: | --- |
| 1 | resolved | `header_rows + dynamic start_line + dynamic separator index` | 1 | 首次即命中正确路径 |
| 2 | unresolved | `转发更多 __init__ 参数 + separator 修正，但缺少 dynamic start_line` | 5 | 回退到半正确路径 |
| 3 | unresolved | `header_rows + separator 修正，但缺少 dynamic start_line` | 5 | 仍未抓到决定性不变量 |
| 4 | resolved | `移除固定 start_line=3 + dynamic start_line + dynamic separator index` | 6 | 成功回到正确路径 |
| 5 | resolved | `与 4 同族，更鲁棒的 separator 搜索` | 9 | 成功路径再次复现 |
| 6 | unresolved | `separator 检测增强，但仍缺少 dynamic start_line` | 11 | workflow 更强，但修法回退 |
| 7 | unresolved | `header_rows + separator index` | 7 | 仍未固化 code invariant |
| 8 | incomplete | 无有效 prediction | 0 | 运行中断，不应过度归因到策略 |
| 9 | resolved | `dynamic start_line + dynamic separator index` | 11 | 成功路径第三次复现 |
| 10 | unresolved | `参数转发 + separator 处理` | 10 | 末轮仍有回退 |

### 3.2 与旧版对比后的核心变化

旧版最明显的问题是：

- 成功路径不 sticky
- 记忆越多，后期注入越噪
- 成功经验没有压成代码级规则

当前 v2.1 的变化是：

1. **成功次数更多**: `2 -> 4`
2. **成功路径复现次数更多**: 当前至少出现了 `attempt 1 / 4 / 5 / 9` 四次同族正确 patch
3. **负经验对象被合并得更好了**
   - 旧版 `failure_cards_v2 = 8`
   - 当前 `failure_cards_v2 = 5`
4. **出现了受控的 compiler card 层**
   - 当前 `compiler_cards_v21 = 20`
5. **出现了 sidecar 长期层**
   - `episode_ledger.jsonl = 137`
   - `subtask_instances.jsonl = 39`
   - `subtask_edges.jsonl = 39`

这说明 v2.1 不是“只把旧系统再跑一遍”。它确实改变了经验积累和经验消费的结构。

## 4. 路径探索分析

### 4.1 当前 run 的真实路径分成两大类

从 `attempt_reports/*.predictions.json` 看，当前 patch 大致分成两类：

#### 路径 A: 正确路径

共同特征：

1. `RST.__init__` 接收 `header_rows`
2. `self.data.start_line` 根据 `len(header_rows) + 2` 动态计算
3. `write()` 中 separator / position line 的索引也跟 `header_rows` 联动

这条路径出现在：

- `attempt_01`
- `attempt_04`
- `attempt_05`
- `attempt_09`

这些 attempts 都是 resolved。

#### 路径 B: 半正确路径

共同特征：

1. 认识到 `header_rows` 或 separator 行有问题
2. 但没有稳定修正 `data.start_line`
3. 因而 patch 只修了一半

这条路径出现在：

- `attempt_02`
- `attempt_03`
- `attempt_06`
- `attempt_07`
- `attempt_10`

这些 attempts 都是 unresolved。

### 4.2 这说明什么

这说明当前 AgentMem **确实帮助 agent 多次回到正确 patch family**，但并没有彻底阻止它回退到半正确 patch family。

这是比旧版更好的状态，但还不够好。

可以把当前状态概括成：

- 旧版：成功路径会出现，但很难再次回来
- 当前版：成功路径能多次回来，但还不能稳定压倒错误路径

## 5. 经验积累分析

### 5.1 当前 store 形状

来自 `persistence/graph_store/metadata.json`:

- `total_actions = 894`
- `total_abstract_experiences = 8`
- `total_attempt_summaries_v1 = 10`
- `total_failure_cards_v2 = 5`
- `total_repair_patterns_v2 = 63`
- `total_preventive_rules_v2 = 0`
- `total_compiler_cards_v21 = 20`

和旧版对比：

- `abstract_experiences`: `6 -> 8`
- `failure_cards_v2`: `8 -> 5`
- `repair_patterns_v2`: `61 -> 63`
- `compiler_cards_v21`: `0 -> 20`
- `preventive_rules_v2`: 仍然 `0`

### 5.2 正向变化

1. **失败卡数量下降**
   - 说明 merge / governance 开始起作用
   - 没再像旧版那样把每次 unresolved 都几乎原样堆叠成新负经验

2. **新增 compiler card 层**
   - 说明经验消费口开始统一化
   - 不再只能依赖旧的散乱对象直接注入

3. **新增 sidecar 长期层**
   - 有了 `success_fact -> subtask -> edge -> compiler_card` 这条结构化链

### 5.3 仍然不够好的地方

1. `preventive_rules_v2` 仍然是 `0`
   - 说明系统还没有把经验真正压缩成稳定防错规则

2. `compiler_cards_v21` 全部还是 `candidate`
   - 当前 `promotion_state = candidate` 共 `20` 张
   - 没有看到 resolved 后形成更强的 promoted card

3. 经验主体还是偏 planning / verification
   - `repair_patterns_v2` 大量内容在说：
     - 要加 verification plan
     - 要加 test plan
     - 要 reuse repro path
   - 这些是有帮助的，但还不是决定性修法

## 6. 经验注入分析

### 6.1 当前 memory injection 的总体趋势

从 `logs/*.jsonl` 抽出来的统计：

- `memory_injected = 65`
- `memory_hint_buffered = 48`
- `memory_intervention_feedback = 108`
- `memory_gate_evaluation = 9`

按 attempt 看，后半段注入强度明显提高：

- attempt 1: `1`
- attempt 2: `5`
- attempt 3: `5`
- attempt 4: `6`
- attempt 5: `9`
- attempt 6: `11`
- attempt 7: `7`
- attempt 9: `11`
- attempt 10: `10`

这说明记忆系统确实在“持续参与”后半段解题。

### 6.2 当前最常注入的 family

高频 family 包括：

1. `closure_signal:over_exploration_after_key_signal`
2. `attempt_summary:astropy__astropy-14182`
3. `patch_risk__official_eval_unresolved__avoid_repeat_failed_strategy`
4. `failure_card:evaluation_unresolved:reproduce_the_failing_path_with_target_validation_before_next_patch`
5. `plan_hint__astropy_astropy_14182__reuse_confirmed_repro_path`
6. 一系列 verification / planning 导向的 `repair_pattern`

### 6.3 这些注入里，真正有帮助的是什么

当前最明显的正向帮助有三类：

#### 1. 路径收敛帮助

典型 hint:

- `reuse_confirmed_repro_path`
- `stop expanding ... move to minimal fix and targeted validation`
- `limit ad-hoc reproduction scripts`

这类提示会把 agent 从“继续开新脚本/新方向”拉回到已知失败路径和最小修补。

#### 2. 验证纪律帮助

典型 hint:

- 加明确 test/verification plan
- 先跑 targeted validation 再提交
- 避免没有验证的 broad patch

这类提示虽然不直接告诉 agent 怎么改 `rst.py`，但确实帮助它围绕目标测试收敛。

#### 3. 失败路径回避帮助

典型 hint:

- `avoid_repeat_failed_strategy`
- `reproduce_the_failing_path_with_target_validation_before_next_patch`

这类提示降低了 agent 一直沿失败 patch family 重复下去的概率。

### 6.4 当前注入的局限

当前最主要的局限是：

- **注入的东西还是太多 workflow 语言，太少 code invariant 语言**

例如当前 compiler card 中能看到：

- `reuse_confirmed_repro_path`
- `closure guard`
- 一堆“增强 planning 的 verification 约束”

但几乎看不到：

- `dynamic data.start_line`
- `separator index = len(header_rows)`
- `移除固定 start_line = 3`

也就是说，记忆在帮 agent“怎么做题”，但还没稳定帮 agent“这个题到底怎么修”。

## 7. 路径复用分析

### 7.1 成功路径复用确实比旧版更明显

旧版文档的核心判断是：

- 成功路径出现过
- 但后面 retrieval 变得更 noisy
- 没有把成功 patch family 稳定留住

当前 v2.1 的情况更好：

1. 正确 patch family 出现了四次，不是两次
2. 后续 resolved attempts 明显复用了“最小修补 + targeted validation”这条路线
3. `plan_hint__reuse_confirmed_repro_path` 已进入高频 family

这说明路径复用能力确实增强了。

### 7.2 但复用还不是“代码级复用”

当前系统复用的主要是：

- repro path
- validation discipline
- minimal-fix strategy

而不是：

- 这个 bug 的最终语义规则

因此它表现为：

- 成功路径更常回来
- 但每次回来还是要靠 agent 再推一遍代码推理

## 8. Success Fact / Sidecar / Projection 的实际表现

### 8.1 有效之处

当前 sidecar 已经真实产生了：

- `episode_ledger.jsonl = 137`
- `subtask_instances.jsonl = 39`
- `subtask_edges.jsonl = 39`
- `compiler_cards.jsonl = 36`

这证明 v2.1 不是“空架构”，长期层已经开始工作。

### 8.2 当前缺口

#### 1. success fact 热路径覆盖还不稳定

`episode_ledger.jsonl` 的分布非常不均匀：

- `attempt-01 = 117`
- `attempt-05 = 13`
- 其他多数 attempts 只有 `1`

这说明 hotpath success fact capture 还没稳定覆盖所有 attempts。

这不是分析层猜测，而是事实层的明确缺口。

#### 2. projected subtask 还太粗

`subtask_instances.jsonl` 的分布：

- `localize_fix = 9`
- `unknown = 9`
- `reproduce_issue = 9`
- `target_validation = 8`
- `broad_regression_check = 4`

这说明 projector 已经能抽出大致阶段，但粒度还偏粗，而且很多子任务还停留在 `unknown`。

#### 3. compiler card 还没有被 resolved feedback 真正“升格”

`compiler_cards_v21.json` 中：

- `promotion_state = candidate` for all `20`

这意味着 compiler 层虽然已经参与注入，但治理层还没有把 resolved 结果变成更强的 promoted 策略。

## 9. 当前 AgentMem 的积极作用

如果只问“当前系统有什么积极作用”，我的结论是：

### 9.1 它现在已经是一个有效的搜索纪律控制器

它能明显帮助 agent：

1. 少走 broad patch
2. 少做 ad-hoc script 膨胀
3. 更快回到 minimal fix
4. 更强调目标测试和 targeted validation

### 9.2 它开始具备成功路径复用能力

不是完全稳定，但相较旧版已经明显更强：

1. 成功 patch family 重复出现四次
2. 高频 hints 里已经有 `reuse_confirmed_repro_path`
3. 失败卡和 closure hints 能把 agent 从坏路径上拉回来

### 9.3 它让经验消费更受控了

`compiler_card + governance + sidecar` 的引入，至少带来三个正效果：

1. 失败对象没有像旧版那样继续爆炸堆叠
2. 注入入口开始统一
3. 经验对象开始有 evidence level 和 candidate 状态

## 10. 当前仍然没有解决的问题

### 10.1 最关键问题: 还没学会“代码级决定性不变量”

当前 store 虽然出现了 `header_rows`、`RST writer functionality`、`fixed_width_header_rows` 等词，
但几乎没有把下面这条真正规则稳定抽出来：

- `data.start_line` 需要跟 `header_rows` 同步动态变化

这就是为什么当前系统能帮助成功路径复现，但还会不断回退到“只修 separator、不修 start_line”的半正确 patch。

### 10.2 compiler 里还没有 bug-specific 卡片

当前 compiler card 几乎全是：

- planning hint
- retry hint
- closure guard

但没有形成像下面这样的 card：

- `BugInvariantCard: RST header_rows requires dynamic start_line + dynamic separator line`

### 10.3 official eval 的信用没有真正转成“强成功策略”

虽然 feedback 已写回，但从结果看：

- compiler cards 仍是 `candidate`
- 没看到 resolved attempts 产出更高等级的成功型 card

这会限制成功路径的长期粘性。

### 10.4 success fact 事实层还不完整

目前热路径 success fact 记录明显偏斜，说明：

- fact plane 已经工作
- 但还没有打透

如果事实层本身不稳定，后续 projector / edge / compiler 的上游质量也会受限。

## 11. 对“是否提升了正确率”和“是否帮助了解题思路”的最终判断

### 11.1 是否提升了正确率

**结论：在这个单题上，有提升。**

- 旧版: `2 / 10`
- 当前: `4 / 10`

但这是**局部证据**，不是全局结论。

### 11.2 是否帮助了解题思路

**结论：有帮助，而且帮助是实质性的。**

帮助主要体现在：

1. 帮 agent 收敛到更小的 patch 范围
2. 帮 agent 复用已确认的 repro / validation path
3. 帮 agent 避免重复 broad / interface-expanding 错误策略
4. 帮 agent 多次回到正确 patch family

### 11.3 帮助到什么程度

当前帮助程度可以定义为：

- **已经能改善搜索与重试质量**
- **已经能提升单题成功率**
- **但还没稳定到“学会这个 bug 的语义规则”**

## 12. 我对当前 AgentMem v2.1 的判断

### 12.1 这是一次真实进步

这次更新不是“只把架构变复杂了”。

从单题 repeat10 的结果看，它至少实现了三件旧版没有明显做到的事：

1. 成功率翻倍
2. 成功路径复用增强
3. 失败经验治理变得更克制

### 12.2 但当前阶段更像“更强的 search controller”，还不是“真正学会 bug invariant 的 memory system”

如果要一句话评价当前版本：

> AgentMem v2.1 现在已经能正向影响 agent 的路径探索和重试策略，但它主要学会的是如何更 disciplined 地解题，而不是如何把这个题的决定性代码规律固化成可迁移记忆。

## 13. 下一步最值得做的改进

基于本次实验，我认为最值得继续推进的不是再加新对象，而是把下面三件事补强：

### 13.1 把 resolved patch family 编译成 bug-specific compiler card

目标不是再加更多 planning hint，而是增加类似：

- `BugInvariantCard`
- `SuccessPathCard`

内容要能直接表达：

- `dynamic data.start_line`
- `separator index follows header_rows`

### 13.2 修热路径 success fact 覆盖问题

先把 `episode_ledger` 的覆盖稳定化，不然 sidecar 上层结论会偏。

### 13.3 让 official eval 真正推动 successful card promotion

当前全是 `candidate` 不够。

需要让 resolved attempts 把少数高价值卡片真正升格，否则成功路径永远只是“偶尔回来”，不会“越来越粘”。

## 14. 最终结论

本次单题实验给出的最稳结论是：

1. **AgentMem v2.1 对这个实例的官方正确率有提升。**
2. **这种提升不是纯随机，因为成功 patch family 被重复找到四次。**
3. **当前系统最有效的作用，是改进搜索纪律、验证纪律和成功路径复用。**
4. **当前系统还没有把这个 bug 的代码级不变量稳定记住，因此成功仍然不够 sticky。**
5. **v2.1 是一次真实进步，但还不是最终形态。**

