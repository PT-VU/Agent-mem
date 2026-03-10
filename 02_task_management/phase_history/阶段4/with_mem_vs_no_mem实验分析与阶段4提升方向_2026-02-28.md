# with_mem vs no_mem 实验分析与阶段4提升方向（2026-02-28）

## 1. 分析范围与数据来源
本文件汇总当前项目中最可比的一组对照实验：
- 实验组：`with_mem`
- 对照组：`no_mem`
- 数据集：`SWE-bench_Lite test first50`
- 评测口径：官方评测 + 轨迹诊断 + 实例级差异

主要证据文件：
1. `PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/notes/official_eval_comparison_first50_unlimited.json`
2. `PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/notes/official_eval_instance_diff.json`
3. `PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/notes/divergence_report_first50.json`
4. `PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/no_mem/metrics/metrics_experiment01_first50_nomem_unlimited.json`
5. `PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/with_mem/metrics/metrics_experiment02_first50_withmem_unlimited.json`

---

## 2. 总体结论（先看结论）

### 2.1 结果层
- no_mem solved rate：`32/50 = 64%`
- with_mem solved rate：`34/50 = 68%`
- 绝对提升：`+4%`（多解出 2 个实例）
- 相对提升：`+6.25%`

结论：**with_mem 已经带来稳定正收益，但幅度仍属于“小幅提升”。**

### 2.2 过程层
with_mem 相比 no_mem 出现以下改进：
- `tool_failed_actions`: `91 -> 66`（下降 `27.47%`）
- `instances_with_tool_failures`: `31 -> 26`（下降 `16.13%`）
- `total_cost`: `6.094 -> 5.792`（下降 `4.96%`）
- `mean_steps`: `104.30 -> 103.96`（基本持平，略降）

结论：**AgentMem 当前更像“降低过程摩擦与无效操作”的能力增强器，而不是“大幅减少推理步数”的加速器。**

---

## 3. 实例级差异：记忆到底帮助了什么

### 3.1 with_mem 独有成功（7个）
- `astropy__astropy-14365`
- `django__django-11815`
- `django__django-11964`
- `django__django-12308`
- `django__django-12908`
- `django__django-13028`
- `django__django-13220`

### 3.2 no_mem 独有成功（5个）
- `astropy__astropy-14182`
- `django__django-11797`
- `django__django-11848`
- `django__django-12113`
- `django__django-12470`

### 3.3 轨迹分歧特征
`divergence_report` 显示：
- improved instances: `22`
- regressed instances: `27`
- equal: `1`
- 平均步数差（no - with）: `+0.34`

典型正向样本：
- `django__django-13028`：with_mem 少 `68` 步，失败信号少 `30`

典型负向样本：
- `django__django-12113`：with_mem 多 `34` 步，失败信号多 `17`

解读：
1. 记忆有时能显著减少绕路（个别实例收益很大）。
2. 但也存在被“弱相关提示”干扰导致的回退实例。
3. 当前净收益为正，但稳定性不足。

---

## 4. 当前 AgentMem 在发挥作用的机制（基于结果反推）

结合指标变化，可以确认当前最有效的是：
1. **减少工具层失败**（文件不存在、重复创建、无效替换等）
2. **减少部分实例的探索绕路**（尤其在中期决策分叉点）
3. **降低总体成本**（虽然步数不明显下降，但动作质量提升）

也就是说，目前 AgentMem 的主要贡献是：
- “少犯低级错误”
- “更快进入有效修改区间”
而不是：
- “显著缩短全部任务推理链路”

---

## 5. 为什么提升只有 +4%（核心原因）

### 5.1 可观测性缺口：实验日志未完整记录记忆事件
在本次 first50 对照中：
- `event_log_files=[]`
- `memory event_counts={}`

这会导致：
1. 无法精确归因“哪条记忆在何步生效”。
2. 难以做高质量的策略迭代（只能看结果，难看机制）。

### 5.2 经验质量缺口：记忆内容仍偏泛化
当前不少提示更像流程提醒，不够“任务特异+可执行+可验证”。
直接后果：
- 对简单任务有帮助
- 对复杂失败模式帮助不足

### 5.3 失败经验沉淀不足
目前系统更擅长沉淀“成功流程”，但对失败轨迹的结构化提取不够强。
这会导致：
- 已知失败模式重复出现
- with_mem 仍可能在少数实例里回退

### 5.4 注入策略仍偏早期和单次
若仅在早期注入，后续“测试失败-修复-再验证”的关键节点缺少针对性干预。

---

## 6. 阶段4可执行提升方向（建议按优先级推进）

## 6.1 P0：补齐可观测性（先保证能解释）
目标：让每次记忆干预可审计、可复盘、可量化。

要做：
1. 固化 with_mem/no_mem 统一事件落盘策略，避免 `event_log_files=[]`。
2. 强制记录链路：
   - `trigger`
   - `selected_memory_ids`
   - `injection_step`
   - `post_injection_N_steps_outcome`
3. 新增在线指标：
   - `hint_accept_rate`
   - `post_injection_recovery_rate`
   - `regression_after_injection_rate`

预期收益：先解决“为什么提升/为什么退化”不可解释问题。

## 6.2 P0：补齐真实证据 embedding（去占位）
目标：提高检索相关性，减少“泛化建议”。

要做：
1. 在 KGWriter 中接入真实 `stdout/stderr/diff` 证据文本。
2. 避免空摘要或占位摘要进入 embedding。

预期收益：提升记忆命中质量，减少误导性提示。

## 6.3 P1：失败经验卡体系化
目标：把失败样本转成高价值可复用资产。

要做：
1. 对 unresolved 样本自动抽取 failure card：
   - 失败测试签名
   - 失败上下文
   - 触发该失败的动作链
   - 候选修复策略与验证命令
2. 优先覆盖 `only_no` 这类 with_mem 回退样本。

预期收益：降低回退实例数量，提升 with_mem 稳定性。

## 6.4 P1：注入策略从“单次提示”升级到“节点化干预”
目标：在关键时间点精准干预。

建议触发点：
1. 首次测试失败后
2. 连续两次错误后
3. 提交前检查阶段

预期收益：提升复杂问题后半程修复效率。

## 6.5 P2：检索分型升级
目标：减少“用 planning 解决所有问题”的错配。

建议 query_type 最少拆分为：
- `planning`
- `error_recovery`
- `test_failure_fix`
- `regression_guard`

预期收益：提高建议针对性，降低错误注入概率。

---

## 7. 阶段4验收建议（针对 with_mem 对照）

### 7.1 硬门槛
1. 事件链路完整可追溯（不得再出现对照实验 memory 事件全空）。
2. with_mem 路径无关键占位 embedding 逻辑。
3. 测试基线可稳定复现。

### 7.2 改进门槛（至少满足2项）
1. solved rate 相比 no_mem 持续提升。
2. `tool_failed_actions` 持续下降。
3. `total_cost` 或 `mean_steps` 至少一项稳定下降。
4. `only_no` 数量下降。

---

## 8. 一句话总结
当前 with_mem 已经证明“有用”，但还没证明“足够强”；阶段4的关键不再是“有没有记忆”，而是“记忆是否可解释、可验证、可稳定提效”。
