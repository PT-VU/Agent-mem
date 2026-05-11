# AgentMem v2 升级框架设计文档

**版本**：v0.1（基于 2026-03-13 讨论稿）  
**目标读者**：研究作者、系统实现者、实验复现者  
**适用对象**：基于 SWE-agent 的跨 session 软件修复 agent 记忆系统  

---

## 0. 文档目的与背景

本文档给出一个**完整的、升级后的 AgentMem v2 框架设计**。它不是对当前系统的简单补丁，而是在保留当前 AgentMem 在线控制优势的前提下，引入**子任务级 episodic memory + 跨 session 搜索路径积累 + 运行时干预控制**的二层结构。

设计直接来自三类输入：

1. **当前 AgentMem 的真实实现链路**：当前系统已经具备 hook 接入、事件路由、延迟注入、runtime guard、run_done 后抽取、official eval 后 promote/suppress 等能力；但主链路对成功 action 的高保真记录不足，更偏向事件级建议与运行时控制。
2. **repeat-10 结果分析**：在 `astropy__astropy-14182` 上，当前系统已经能改变行为并两次解决问题，但没有把决定性代码不变量学成“可粘住”的成功路径，反而主要积累了 workflow 级 advice，导致后续重跑噪声增大、成功路径不稳定。
3. **外部相关工作**：SWE-Exp 强调 agent 是 memoryless explorer、经验应减少冗余探索；RepoMem 强调 repository history 可作为长期 memory；MemGovern 强调经验对象必须经过治理；Subtask-Level Memory 强调记忆单元必须和子任务结构对齐。上述工作共同表明：**长期经验对象建模**与**运行时注入/访问策略**必须解耦设计，且记忆粒度不能停留在整题级。  

### 0.1 设计目标

AgentMem v2 旨在同时提升两个维度：

1. **同一 instance 的跨 session 重跑收敛性**：每次尝试都尽量减少重复低价值探索，更快逼近正确解。
2. **相似子任务/环境下的经验复用能力**：把反复出现的子任务经验压缩成可检索、可注入、可转化为 skill prior 的对象，以提高稳定性和 token 效率。

### 0.2 核心结论

AgentMem v2 的定位不是“更大的经验库”，而是：

> **一个由长期 episodic search graph 与短期 runtime controller 组成的闭环记忆系统。**

- 长期层回答：**过去试过什么、哪些分支值得再走、哪些子任务模式在什么环境下高风险/高收益。**
- 短期层回答：**当前这一轮里，什么时候注入经验、注入哪一类、是否阻断当前动作、是否应该 retry/replan/closure。**

---

## 1. 当前 AgentMem 的已知优势与已知缺口

## 1.1 当前系统必须保留的优势

根据现有框架综述，当前系统已经具备以下非常有价值的能力：

1. **SWE-agent 生命周期 hook 接入**：可稳定监听 `on_actions_generated`、`on_action_error`、`on_model_query`、`on_run_done`。
2. **延迟注入机制**：经验不是检索完立刻塞入，而是缓冲到 `_pending_memory_hints`，在 `on_model_query` 前按预算、家族冷却、置信度与 runtime guard 统一选择。
3. **runtime guard**：可以在在线执行时软阻断明显低价值或重复性的动作，减少 ad-hoc 脚本扩张和过度探索。
4. **official eval gating**：经验不会在 `submitted` 时自动视为成功，而是要等官方评测回来后再决定 promote / suppress。
5. **失败后收尾学习**：`run_done` 后已经可以生成 attempt summary、abstract experience、failure card、repair pattern，并配合 RCA 做失败归因。

这些能力是 AgentMem v2 的**在线控制基底**，不能丢。

## 1.2 当前系统的主要缺口

repeat-10 分析揭示了当前系统的结构性问题：

1. **学到的是流程建议，不是代码不变量**。成功路径两次被 rediscover，但没有被沉淀成稳定可复用的 bug-specific invariant。
2. **长期记忆对象偏解释层，事实层不足**。主链路没有把每个成功 action、关键 diff、targeted test 结果、touched files 持续作为高保真证据写入。
3. **经验对象粒度偏事件级/工作流级**，而不是子任务级。导致长期记忆更像“提醒”而不是“状态-动作-结果”经验单元。
4. **成功 consolidation 不够，失败卡不断累积**。post-success retrieval 变得更 noisy，而不是更 sharp。
5. **preventive rules 只写不读**，说明当前部分对象尚未进入真正闭环。

AgentMem v2 的升级目标，就是在保留当前在线控制优势的同时，补上**子任务级 episodic memory** 的骨架与高保真证据层。

---

## 2. AgentMem v2 的总体设计原则

## 2.1 原则一：记忆不是“保存过去”，而是“压缩过去搜索成本”

跨 session 记忆的本质，不是回放历史文本，而是把过去探索的代价压缩成能改变未来决策的先验。记忆必须至少做到以下一项：

- 缩小未来搜索空间；
- 提高有效动作的先验概率；
- 减少在错误子空间中的停留时间；
- 提高对当前失败/异常的归因效率。

## 2.2 原则二：长期记忆与短期控制必须分层

- **长期层**负责采集、存储、归纳、打分、检索；
- **短期层**负责注入、预算、干预、收口、冷却、局部效果跟踪。

不能把控制规则直接写进长期经验对象，否则经验误判会直接污染运行时控制。

## 2.3 原则三：事实层优先于解释层

每一条经验都应包含两层：

- **事实层**：真实执行、真实环境、真实输出、真实 diff/test/file 证据；
- **解释层**：由 rule-based 或 LLM 提炼的抽象建议、归因、风险和适用条件。

解释层可以更新、重写、重抽；事实层必须尽量完整、可追溯。

## 2.4 原则四：复用单元是“子任务”，不是整题

长期复用单元应对齐到子任务（subtask）层，而不是整条 episode。子任务的边界由 planning 阶段创建并显式声明，每个子任务对应一个独立的 agent 对话 turn，以便 hook 能稳定感知其开始和结束。

## 2.5 原则五：失败必须先归因，才能记忆化

失败不能直接视为“坏路径”。必须先判断其类型：

- 计划错误（Plan Failure）
- 执行错误（Execution Failure）
- 工具策略错误（Tool Strategy Failure）
- 验证错误（Validation Failure）
- 信息型失败（Informative Failure）
- 基础设施错误（Infra Failure）

只有带类型的失败，才是可用经验。

---

## 3. 总体架构：二层闭环 + 一条信用分配主链

```text
SWE-agent
  -> Planning creates subtasks
  -> Each subtask is executed as an independent dialog turn

Hook / Runtime Controller (旧 AgentMem 优势层)
  -> observe subtask_start / subtask_update / subtask_end / action_error / model_query / run_done
  -> inject hints before model query
  -> runtime guard / cooldown / closure / retry window
  -> local intervention tracking

Long-term Episodic Search Graph (新主骨架)
  -> Episode Ledger
  -> Subtask Instance Graph
  -> Path Segment Memory
  -> Subtask Prototype Memory
  -> Retrieval / ranking / conflict analysis

Credit Assignment Layer
  -> local subtask outcome + RCA
  -> run_done extraction
  -> official eval promotion/suppression
```

### 3.1 四个核心模块

1. **Episode Ledger**：保存原始轨迹账本，作为不可丢失的事实总账。
2. **Subtask Graph**：以子任务实例为节点，以执行/重试/替代/支持关系为边，形成跨 session 的 episodic 图谱。
3. **Prototype / Skill Compiler**：从实例图谱中归纳出更可复用的原型级经验对象和 path prior。
4. **Runtime Controller**：在当前会话里按风险、时机和预算决定注入与干预。

### 3.2 为什么不是“只有知识图谱”

知识图谱只是**存储与查询基底**，不是方法本体。真正重要的是：

- 节点与边的定义；
- 子任务边界；
- 失败归因协议；
- 检索排序策略；
- 注入预算与副作用控制；
- 官方评测后的信用回写。

---

## 4. 子任务（Subtask）建模

## 4.1 子任务定义

子任务是：

> **在一定环境条件下，接受一组输入，以达成某个局部目的或产生某种期望输出的一段 action 链。**

它既不是单条 shell action，也不是整题。它是跨 session 经验积累的最小主单元。

## 4.2 子任务边界

子任务的开始和结束由 agent 在 planning 阶段显式定义，并且要求：

- 每个子任务作为独立的 agent 对话 turn；
- `subtask_start` 发生在 agent 接收并承诺某一子任务时；
- `subtask_end` 发生在 agent 给出子任务结果、进入下一子任务或触发 replanning 时；
- 若中途切换目标，应显式触发 `subtask_abort` 或 `subtask_switch`。

这样可以保证 hook 能稳定挂接，不依赖模糊启发式判断边界。

## 4.3 子任务大小的控制

子任务块大小由 LLM 决定，但通过 prompt 进行约束和可控实验。系统需要支持三种粒度模板以做对比：

1. **粗粒度**：定位、修复、验证等大块任务；
2. **中粒度**：定位-验证-编辑-复验分开；
3. **细粒度**：把一个局部验证、一个局部编辑也视作子任务。

实验中应把子任务粒度作为明确自变量。

---

## 5. 环境（Environment）建模

## 5.1 环境定义

环境是“与当前子任务运行相关的信息集合”。它不追求穷尽一切，而追求**必要、简洁、可复用**。

## 5.2 环境字段建议

环境字段最少应包括：

- repository / instance id
- 当前 commit / worktree 状态摘要
- python 版本
- 关键依赖与工具版本
- 当前可用工具集
- 当前 failing test / traceback anchors
- 当前怀疑文件集合或 touched files 摘要
- 当前规划阶段标签（locate / reproduce / edit / validate / closure）
- 当前子问题类型（subproblem_type）

## 5.3 环境签名（Environment Signature）

为避免检索时环境过拟合或过粗合并，需要构造 `env_signature`：

- 一部分为结构化字段（repo、toolchain、test anchor、subtask type）；
- 一部分为轻量文本摘要；
- 允许后续扩展为多视角 embedding。

该签名用于：

- 子任务实例相似度检索；
- path segment 匹配；
- 冲突经验的聚类和根因分析。

---

## 6. 长期记忆数据模型

## 6.1 四类长期对象

### A. Episode Ledger Item
完整 session 的原始事实账本。

### B. Subtask Instance
某一次具体子任务执行的事实与局部解释。

### C. Path Segment
常见的子任务转移片段，长度一般为 2 到 4。

### D. Subtask Prototype
从多个实例中归纳出的原型经验对象，最接近可复用 skill prior。

## 6.2 为什么要区分实例与原型

- **实例**解决跨 session 回放与信用分配；
- **原型**解决压缩、复用与 skill 化；
- 只存原型会丢证据；
- 只存实例会噪声过高、难以注入。

## 6.3 Subtask Instance Schema（建议）

每个子任务实例至少保存：

### 事实层
- `subtask_instance_id`
- `episode_id`
- `attempt_id`
- `parent_plan_id`
- `subtask_type`
- `subtask_goal`
- `subtask_inputs`
- `env_signature`
- `observed_context`
- `action_chain`
- `tool_calls`
- `touched_files`
- `patch_digest`
- `tests_run`
- `test_outputs`
- `stderr/stdout`
- `local_result_status`
- `start_state_digest`
- `end_state_digest`
- `delta_summary`

### 解释层
- `llm_summary`
- `failure_type`
- `root_cause_candidates`
- `recommended_next_steps`
- `warnings`
- `reusability_conditions`
- `information_gain_score`
- `confidence`
- `official_eval_linkage`

## 6.4 Path Segment Schema

Path segment 表示稳定的局部转移模式：

- `segment_id`
- `from_subtask_prototype`
- `to_subtask_prototype`
- `optional_middle_steps`
- `applicable_env_signatures`
- `success_rate`
- `failure_rate`
- `informative_fail_rate`
- `mean_cost_tokens`
- `mean_cost_steps`
- `downstream_success_pass_through`
- `diagnostic_utility`

## 6.5 Subtask Prototype Schema

每个原型对象建议采用双层结构：

### Index Layer
- 适用环境
- 典型输入
- 典型目标
- 触发条件
- 常见风险信号
- 相似失败锚点

### Resolution Layer
- 成功策略摘要
- 失败模式摘要
- 推荐工具顺序
- 验证建议
- stop / retry / replan 建议
- avoid_actions
- path priors

这借鉴了 MemGovern 的“检索层 / 行动层”分离思想，但适配到了 agent 自身的 episodic memory。 

---

## 7. 图谱结构设计

## 7.1 节点类型

- `Episode`
- `Plan`
- `SubtaskInstance`
- `SubtaskPrototype`
- `PathSegment`
- `Observation`
- `Patch`
- `TestOutcome`
- `FailureCard`
- `AttemptSummary`

## 7.2 边类型

- `HAS_SUBTASK`
- `INSTANCE_OF`
- `PRECEDES`
- `RETRY_OF`
- `ALTERNATIVE_TO`
- `SUPPORTED_BY`
- `BLOCKED_BY`
- `OBSERVED`
- `PRODUCED_PATCH`
- `VALIDATED_BY`
- `CAUSED_FAILURE`
- `PROMOTED_TO`

## 7.3 为什么需要 `RETRY_OF` 与 `ALTERNATIVE_TO`

这是跨 session 搜索记忆的关键：

- `RETRY_OF` 表示这次其实在重试同一路局部想法；
- `ALTERNATIVE_TO` 表示这次换了另一种局部策略。

这能让系统区分：
- “同一子任务又失败一次”
- “同一目标下尝试了不同执行方式”

## 7.4 为什么需要 `BLOCKED_BY`

当前系统的 runtime guard 和 negative strategy 经验，未来都应写入 `BLOCKED_BY` 相关视图，而不是只停留在即时规则表里。这样才能把“为什么这条路现在不建议走”回写到长期记忆层。

---

## 8. 提取（Extraction）设计

## 8.1 提取时机

### 必选时机
1. `subtask_start`
2. `subtask_end`
3. `action_error`
4. `run_done`
5. `official_eval_feedback`

### 主提取点
真正的经验提取主点是：

- **每个子任务结束时**：提取局部经验与局部结果；
- **run_done 时**：聚合为 episode/attempt 级总结；
- **official eval 后**：做最终 promote / suppress / negative write-back。

## 8.2 子任务结束时提取什么

每个子任务结束时，至少提取两层对象：

### A. 子任务事实记录（必须）
- 环境
- 输入
- 输出
- 目的
- action chain
- 工具调用
- touched files
- tests / stderr / stdout / diff
- 子任务结果

### B. 子任务经验记录（可由 LLM 生成）
- 成功/失败归因
- 是否属于执行问题、计划问题或工具策略问题
- 下次遇到类似子任务时的注意事项
- 是否建议 retry / replan / closure

## 8.3 提取谁来做

采用**同底座 LLM**：

- 失败归因协议、子任务总结、冲突经验复核，均优先使用与解题 agent 相同的底层 LLM。
- 原因：保持判断风格与语言空间一致，减少检索对象与执行模型之间的“语义不对齐”。

同时保留 rule-based 预处理：
- taxonomy tagging
- failure signature generation
- env signature extraction
- touched files / test anchors / patch stats extraction

## 8.4 信息型失败的特殊处理

如果某次子任务失败，但显著缩小了问题空间或提供了高价值诊断信息，则标记为 `Informative Failure`，而不是普通失败。它不应直接降低该子任务原型的优先级，而应提升其 `diagnostic_utility`。

---

## 9. 失败归因协议

## 9.1 五类主失败类型

1. **Plan Failure**：这个子任务本来就不该被启动，方向错或被误用。
2. **Execution Failure**：子任务目标合理，但本次执行没做好。
3. **Tool Strategy Failure**：工具选型、参数、验证流程、脚本策略不对。
4. **Validation Failure**：局部修复可能有价值，但验证闭环不完整或验证目标不对。
5. **Informative Failure**：虽然没成功，但显著提高了诊断信息量。
6. **Infra Failure**：容器、环境、依赖、评测基建等外部故障。

## 9.2 失败归因流程

```text
subtask_end with failure
  -> local recheck
  -> fetch similar subtask memories
  -> RCA / LLM analysis over current + historical evidence
  -> classify failure type
  -> if Execution/Tool Strategy: prefer local retry guidance
  -> if Plan Failure: write branch-level failure and startup cautions
  -> if Informative Failure: mark as diagnostic asset
```

## 9.3 冲突经验处理

若同一子任务原型既有成功经验又有失败经验，则不直接简单平均，而是触发**冲突经验分析**：

- 使用 LLM 对过往历史做额外根因分析；
- 判断冲突来自计划层误用，还是行动层实现差异；
- 若是计划层误用，则在原型经验中追加“何时不该启动该子任务”的注意事项；
- 若是执行层差异，则增加 tool / validation / retry guidance，而不是否定整个子任务原型。

---

## 10. 检索（Retrieval）设计

## 10.1 检索目标

检索不是为了“找到最像的文本”，而是为了：

- 找到当前子任务最相关的成功/失败实例；
- 找到当前路径最相关的 path segment；
- 找到需要避开的高风险原型；
- 找到建议 retry、replan、closure 的先验。

## 10.2 检索入口

### 计划层入口
在 planning 生成子任务序列时触发，用于评估：
- 哪些 path segment 在类似环境下高失败率/高信息增益/高成功率；
- 是否存在经常被误用的子任务原型；
- 当前计划是否重复进入历史低价值分支。

### 执行层入口
在 `subtask_start` 与 `subtask_failure_recheck` 时触发，用于：
- 调出相似子任务实例的成功/失败经验；
- 给出局部 retry/replan 提示；
- 为 runtime controller 提供风险信号。

## 10.3 检索特征

检索应融合多种特征：

- `env_signature` 相似度
- `subtask_type` / `subproblem_type`
- `goal_similarity`
- `failure_signature`
- `touched_files` overlap
- `test anchor` overlap
- `strategy_label` / `tool usage pattern`
- 图关系（前驱/后继/path segment）
- 官方评测确认后的置信度

## 10.4 e-greedy / path exploration policy

在**计划层**引入受控探索：

- 当某路径失败次数多且探索次数多时，降低其优先级；
- 但保留小概率重新探索该路径，避免过早锁死；
- 该概率是超参数，并必须在实验中明确控制；
- 降权不仅看失败次数，还要看：
  - 信息增益
  - downstream success pass-through
  - 是否为必要前置动作

因此，AgentMem v2 的“探索-利用”不是粗糙的“多失败就少走”，而是**风险、收益、诊断价值共同决定的 path prior**。

---

## 11. 注入（Injection）与运行时控制设计

## 11.1 注入原则

经验注入应该发生在**决策点**，而不是全局开头一次性完成。注入太早会被遗忘，太晚会来不及纠偏。

## 11.2 三类注入时机

### A. 计划层注入（轻量）
在子任务计划生成前后注入：
- path segment 风险/收益摘要
- 常见误用提醒
- 建议优先的子任务序列

### B. 子任务开始注入（轻量到中等）
在 `subtask_start` 时，根据风险与相似度决定是否注入：
- 相似子任务的成功/失败摘要
- 启动该子任务的注意事项
- 推荐工具/验证顺序

### C. 子任务失败复核注入（强）
在 `subtask_failure_recheck` 时注入：
- 相似失败的根因分析
- 本地 retry 建议
- 判断是否应升级为 plan failure / replan

## 11.3 注入预算与过度干扰控制

不是每个子任务都强注入。注入策略分三级：

- **默认不注入**：低风险、标准计划内执行；
- **弱注入**：计划内但高风险或高历史失败率的子任务；
- **强注入**：计划外行为、冲突经验、失败复核、即将提交/收口。

## 11.4 注入对象

注入的不是原始记忆全文，而是**编译后的摘要对象**：

- 计划摘要卡
- 子任务风险卡
- retry/replan 建议卡
- avoid_actions 列表
- 路径优先级提示

这些对象应来自 Memory Compiler，而非原始图谱节点直接串接。

## 11.5 Runtime Controller 的职责

保留并升级当前 AgentMem 运行时控制面：

- `_pending_memory_hints`
- family cooldown
- `_closure_active`
- `_active_subproblem_type`
- `_active_strategy_label`
- `_blocked_action_patterns`
- intervention window
- circuit breaker / stale fallback

但它们的上游数据源改为：

- 当前系统已有的 attempt summary / failure card / repair pattern
- 新增的 subtask/path/prototype 级摘要对象

## 11.6 Runtime guard 的定位

runtime guard 不属于长期 memory 本体，而属于：

> **memory-informed controller**

它的收益必须和长期检索层解耦做消融，以避免把全部提升误归因给“memory”。

---

## 12. Memory Compiler：从实例图谱到可注入对象

## 12.1 为什么需要 Compiler

原始图谱节点太重、太碎、太多噪声，不适合直接注入。需要一层 compiler 负责：

- 聚合多条实例
- 选择最相关证据
- 生成低 token、强行动性的摘要
- 给每张摘要附带置信度、适用条件与冲突标记

## 12.2 Compiler 输出类型

1. `PlanHintCard`
2. `SubtaskRiskCard`
3. `RetryHintCard`
4. `ReplanHintCard`
5. `PathPriorCard`
6. `ClosureGuardCard`

## 12.3 输出模板（示意）

### `SubtaskRiskCard`
- 当前子任务原型
- 适用环境签名
- 历史成功/失败概况
- 常见误用条件
- 推荐先做什么
- 不建议做什么
- 是否先本地 retry / 还是直接 replan

### `PathPriorCard`
- 当前计划对应 path segment 的历史统计
- 高失败分支
- 高信息增益分支
- 建议优先级
- e-greedy 重试概率

---

## 13. 信用分配（Credit Assignment）

## 13.1 局部信用分配

每个子任务结束时，要判断：

- 是否达到子任务目标；
- 是否属于计划错误或执行错误；
- 是否提供了高信息增益；
- 是否应该进入本地 retry；
- 是否应写入 negative pattern 或 caution。

## 13.2 全局信用分配

`run_done` 之后进行 episode/attempt 聚合；`official_eval_feedback` 之后进行最终 promote/suppress。

### promote 条件
- 官方评测确认为 resolved
- 或者该对象在多个 resolved attempts 中反复出现且证据稳定

### suppress 条件
- 官方评测 unresolved / incomplete
- 被判定为 template polluted / direct_success_flow polluted
- 与更多高置信 evidence 冲突

## 13.3 为什么要保留 official eval gating

当前 repeat-10 分析已经说明：如果把 submitted 或局部 success-like flow 过早抽象为成功经验，会污染长期记忆。官方评测仍然是 AgentMem v2 最关键的最终信用源之一。

---

## 14. 图谱污染控制（暂定设计，后续细化）

> 注：按当前讨论要求，本节先作为设计占位与风险提示，后续单独展开。

### 14.1 污染来源
- 伪成功（局部成功但全局无益）
- 伪失败（局部失败但信息增益高）
- LLM 幻觉式抽象
- 冲突经验未分层分析
- 计划级误用与执行级失败被混写
- 直接把运行时控制规则固化为长期经验

### 14.2 初步控制手段
- 事实层优先保存
- 解释层可重抽
- candidate / promoted 双层状态
- 官方评测后再升格
- 冲突经验走单独 LLM RCA
- 防模板污染标记

---

## 15. 与当前 AgentMem 的融合方案

## 15.1 保留的部分

完全保留并复用当前以下能力：

1. hook 接入层
2. dispatcher / adapter 编排链
3. `on_model_query` 延迟注入点
4. runtime guard / cooldown / closure
5. run_done 收尾学习
6. official_eval_feedback promote / suppress
7. 当前的 attempt summary / failure card / repair pattern 作为过渡期对象

## 15.2 新增的部分

1. `subtask_start / subtask_end / subtask_abort / subtask_recheck` 事件
2. Episode Ledger
3. Subtask Instance Graph
4. Path Segment Memory
5. Subtask Prototype Memory
6. Memory Compiler
7. 计划层 path prior 检索
8. 冲突经验 LLM 分析

## 15.3 对旧对象的重定位

- `attempt_summary_v1`：保留，作为当前实例/最近一轮的强摘要对象；
- `failure_card_v2`：保留，但在未来应更多绑定到 subtask/prototype/path misuse；
- `repair_pattern_v2`：保留，逐步演进为 prototype resolution layer 的组成部分；
- `preventive_rule_v2`：升级为 prototype 级 caution / startup notes，并纳入读取闭环；
- `runtime guard`：从“经验的一部分”改写为“经验驱动控制器”。

## 15.4 为什么不是推倒重来

因为当前系统已经证明：
- 会改变 agent 行为；
- 会在 query 前注入；
- 会通过 official eval 做迟延信用分配。

新框架不是替代这些能力，而是让它们有一个更扎实的长期记忆骨架。

---

## 16. 实现路线（建议分阶段）

## Phase 0：观测与数据对齐
- 补全子任务生命周期事件
- 保证每个子任务作为独立 agent turn
- 补齐事实层字段：diff、tests、touched files、tool usage、state digest

## Phase 1：Subtask Instance Graph
- 写入 subtask instance
- 建立 `PRECEDES / RETRY_OF / ALTERNATIVE_TO`
- 完成局部失败归因 taxonomy

## Phase 2：Path Segment + Prototype
- 从实例图谱中抽 path segment
- 聚类形成 subtask prototype
- 引入双层对象：index/resolution

## Phase 3：Compiler + 注入重构
- 让 `on_model_query` 不再只读旧 hint 对象，也读新 compiler cards
- 计划层增加 path prior 注入
- 子任务失败复核增加强注入

## Phase 4：污染控制与冲突分析
- candidate/promoted 状态机
- 冲突经验 RCA
- preventive rule 真正进入读取闭环

## Phase 5：skill prior 演化
- 从 prototype 进一步压缩出更稳定的 skill / tool / workflow prior
- 评估 token 降低与稳定性提升

---

## 17. 预期收益

## 17.1 对当前系统的直接收益

1. 让同一 instance 的成功路径更“粘住”，不再只学到 workflow checklist。
2. 把失败卡从“泛化提醒”升级为“带环境和子任务边界的失败经验”。
3. 降低 post-success retrieval 噪声。
4. 让 preventive rule 从只写不读变为可复用 caution。

## 17.2 对研究问题的收益

1. 更严格地定义了跨 session 搜索记忆。
2. 把“记忆单元”“提取点”“注入点”“信用源”全部显式化。
3. 为同题重跑与跨题子任务复用提供统一框架。
4. 为后续论文中的 ablation、误差分析、失败归因提供良好骨架。

---

## 18. 主要风险与开放问题

1. 子任务粒度太粗或太细都会影响效果，需要做对比实验。
2. 计划层 path prior 若设计不当，可能过度抑制探索。
3. LLM 归因若不受事实层约束，容易制造伪因果解释。
4. 图谱对象过多时，compiler 的压缩和排序质量将成为瓶颈。
5. 冲突经验如果不做计划层/执行层分离，可能导致 prototype 误判。
6. 运行时控制收益必须与长期 memory 收益解耦评估。

---

## 19. 推荐的论文式表述

如果用于后续论文，可将 AgentMem v2 表述为：

> **A two-layer memory framework for SWE agents that combines cross-session episodic search graphs with runtime intervention control.**

更具体地：

- 长期层积累子任务级探索路径与环境绑定经验；
- 短期层在 planning、subtask start、failure recheck、closure 等关键决策点进行渐进式注入和动作控制；
- 信用分配依赖局部归因与官方评测反馈，避免伪成功污染长期记忆。

---

## 20. 文档结论

AgentMem v2 的关键升级，不在于“再加更多经验对象”，而在于：

1. 把记忆单位从事件级/流程级升级为**子任务级 episodic 单元**；
2. 把跨 session 重跑定义为**路径探索与信用积累问题**；
3. 把当前 AgentMem 的在线控制优势保留下来，作为**记忆驱动的 runtime controller**；
4. 通过事实层、解释层、控制层分离，降低长期图谱污染与方法归因混乱的风险。

这份设计既能解释你当前系统为什么“已经有用但还不稳定”，也给出了一个更系统、更可实验、更适合论文化的升级方向。
