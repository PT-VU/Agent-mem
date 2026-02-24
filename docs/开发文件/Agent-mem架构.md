- # Training-free 工作经验记忆模块：面向 SWE 与 GUI Agent 的可检索、可结构化、可验证架构（V1.0）

  > 目标：在不进行模型训练（training-free）的前提下，为 LLM Agent 增加“面向工作经验”的长期记忆能力。系统从历史 action 轨迹中提取可复用经验（含成功流程与失败修复），并在**规划阶段**与**执行阶段**进行注入，同时将高置信经验**编译为可验证约束/偏好**（PDDL3 + validator），以提升长流程任务（SWE/GUI）的成功率、降低高错动作的一次失败率并抑制级联失败。

  ---

  ## 1. 总体目标与设计原则

  ### 1.1 总体目标（What）
  构建一个“工作经验记忆模块（Work-Experience Memory, WEM）”，实现：

  - **可检索（Retrievable）**：跨任务、跨会话复用经验（多视角 embedding + 分层检索目标）。
  - **可结构化（Structured）**：用知识图谱表达轨迹结构，区分“成功流程”和“失败-重试”。
  - **可验证（Verifiable）**：保留证据坐标（evidence refs）可回放；将成熟经验编译为 PDDL3 约束/偏好，配合 validator 做 fail-fast。
  - **可演化（Evolving）**：异步进行根因归因、剪枝提炼、统计更新；通过信念图（belief graph）实现“可推翻、可冲突共存、可固化”的经验演化。

  ### 1.2 关键原则（How）
  1. **Training-free**：不更新模型参数，只做信息提取、压缩、组织、检索与验证。
  2. **事实/信念分离（Epistemic separation）**：事实图存证据（可验证观测）；信念图存推断（可错结论）并可更新/冲突消解。
  3. **双经验视角**：宏观流程经验 vs 微观易错点经验（通过两类边显式建模）。
  4. **异步经验累积**：经验提取与根因分析可延迟执行（类似人类复盘），不阻塞在线执行。
  5. **证据可追责**：Memory Agent 的建议必须返回证据坐标（不一定返回原文），便于失败回溯与再提炼。

  ---

  ## 2. 系统全景：两条主链路 + 三层护栏

  ### 2.1 两条主链路
  1) **经验抽取链路（Action history → Structured experience）**
  - 轨迹采集与归档（problem file + KG）
  - 异步根因归因（RCA）
  - 剪枝与提炼（distillation）
  - 经验编译（belief / constraints）

  2) **经验使用链路（Structured experience → Planning/Execution gain）**
  - 范式 A：Planning-time 经验注入（流程模板与预防性检查）
  - 范式 B：Execution-time 出错回忆（失败-修复模式与局部纠错）
  - 可选：constraint-based fail-fast（候选 plan/action 过滤/排序）

  ### 2.2 三层护栏（从软到硬）
  1. **KG 检索→生成提示（soft guidance）**
  2. **PDDL3 preferences→候选排序（soft control）**
  3. **PDDL3 constraints + validator→强约束过滤（hard control / fail-fast）**

  ---

  ## 3. 核心数据结构：Problem File、事实图（Observation KG）、信念图（Belief Graph）

  ### 3.1 Problem File：Action 级经验原子
  每一步 action 都封装为一个 **Problem File**，并写入事实图节点。Problem file 采用“结构化字段（可还原）+ 摘要/embedding（可检索）”分层存储。

  #### 3.1.1 Problem File 字段（建议 schema）
  - `action_id`: string（全局唯一）
  - `task_id`: string（本次任务唯一）
  - `timestamp`: int/ISO
  - `action_type`: enum（tool_call / code_edit / run_test / gui_click / gui_type / web_nav / …）
  - `intent_text`: string（执行者意图层：本步目的/策略角色）
  - `inputs`: object（参数、prompt片段摘要、所需上下文摘要）
  - `tool_calls`: list（命令/工具调用、参数）
  - `stdout_ref`: pointer（证据坐标）
  - `stderr_ref`: pointer（证据坐标）
  - `exception_stack_ref`: pointer（证据坐标）
  - `touched_files`: list（文件集合）
  - `diff_summary_ref`: pointer（证据坐标）
  - `tests_ref`: pointer（测试输出证据）
  - `ui_state_ref`: pointer（GUI：截图/可访问树/元素树坐标）
  - `outcome`: enum（success / fail / unknown）
  - `failure_signature`: object（归一化错误签名：错误类型cluster、关键token等）
  - `env_signature`: object（环境签名：版本/关键env var存在性/路径哈希/容器/代理等）
  - `evidence_index`: list[pointer]（该节点所有可追溯证据坐标集合）
  - `embeddings`: dict（多视角embedding，见 4.2）
  - `epistemic_tags`: dict（字段标注为 EVIDENCE / INFERENCE）

  > 注：`intent_text` 是对 action 边界模糊问题的关键补丁：检索既能按“策略模式”找经验，也能按“具体报错/命令/文件范围”找经验。

  ---

  ### 3.2 事实图 Observation KG：以 Action 为节点、任务为树/子图
  - **节点**：每个 action 的 problem file
  - **每次任务执行**：图上的一棵树/有向结构（含主链与重试分支）
  - **跨任务**：多个不连通子图（任务孤岛）共存于同一图数据库空间（便于统计与检索）

  #### 3.2.1 边类型（最小集合 + 可扩展）
  1) `success_next`：action_i → action_{i+1}
  - 表示成功推进流程的主链（流程经验载体）

  2) `fail_retry`：fail_action → retry_action
  - 表示局部失败后的修复重试链（易错点经验载体）

  > 允许后续扩展：如 `depends_on`, `alternatives`, `verifies`, `undoes`, `blocks` 等。

  ---

  ### 3.3 信念图 Belief Graph：可推翻、可更新的经验法则与总结
  信念图用于存储“从事实图推断出的经验”，避免把推断当事实永久固化。

  #### 3.3.1 两层信念节点（推荐）
  1) **Attempt Belief（任务尝试级）**
  - 节点对应一次任务尝试（事实图中的一棵树/子图）
  - 内容：整体策略总结、失败因果链摘要、关键转折点、归因结果（带概率）、可复用流程要点
  - 用途：复盘解释、全局模板总结、对比多次尝试

  2) **Atomic Belief（原子经验法则级）**
  - 形式：IF (条件签名) THEN (建议/禁止/必须) BECAUSE (证据引用)
  - 用途：跨任务迁移、冲突消解、编译为 PDDL3 preference/constraint

  #### 3.3.2 Atomic Belief 字段（建议 schema）
  - `belief_id`
  - `type`: enum
    - `workflow`（流程模板/预防）
    - `pitfall`（易错点修复）
    - `env_adaptation`（环境适配规律）
  - `condition_signature`: object
    - `env_cluster`（环境簇/签名）
    - `repo/toolchain`（语言/框架/构建工具）
    - `action_type/intent_pattern`
    - `file_scope_pattern`
    - `error_signature`（可选）
  - `rule`: object
    - `trigger`: WHEN/IF
    - `recommend`: DO（插入动作、参数模板、验证步骤）
    - `avoid`: NOT DO（禁止动作、互斥动作）
    - `redundant`: DO-NOT-REPEAT（有一个就不必做另一个）
  - `stats`: object（统计学证据）
    - `support_n`
    - `success_with`, `success_without`
    - `uplift`
    - `uncertainty`（CI或Bayesian posterior）
    - `recent_window_metrics`
  - `confidence`: float（综合置信）
  - `evidence_refs`: list[pointer]（指向事实图节点/证据坐标）
  - `attribution_refs`: list（RCA输出引用，作为可错信念）
  - `status`: enum（active / deprecated / promoted_to_preference / promoted_to_constraint）
  - `last_updated`

  ---

  ## 4. 经验抽取链路（Action → 事实图 → 根因归因 → 提炼 → 信念/约束）

  ### 4.1 轨迹采集与归档（在线）
  在线执行中：
  1. 每个 action 生成 problem file
  2. 写入事实图节点
  3. 根据 outcome 写入边：
     - 成功：连接 `success_next`
     - 失败且重试：连接 `fail_retry`
  4. 写入多视角 embedding（见 4.2）

  ---

  ### 4.2 多视角 Embedding 体系（支持分层检索）
  为降低“语言表述不相似导致漏召回”的问题，embedding 不是单一向量，而是多视角：
  - `emb_task_sem`: 任务语义摘要向量
  - `emb_file_scope`: 文件范围/模块向量
  - `emb_error_sig`: 报错签名向量
  - `emb_tool_output`: 工具输出摘要向量
  - `emb_diff_summary`: diff摘要向量
  - `emb_intent`: intent_text 向量
  - GUI 额外：
    - `emb_ui_state`: 截图/元素树多模态向量（至少保留可访问树/截图hash + 向量）

  > 检索时显式选择“检索粒度与视角”：task-level vs action-level；planning vs execution 场景使用不同权重。

  ---

  ### 4.3 异步根因归因（RCA Agent）：模仿 2509.25370 的“最小根因集合 + 传播链”范式
  #### 4.3.1 动机
  长任务失败往往是早期错误的级联传播（cascade）。仅记录“最后一步报错”会导致经验学习偏差。RCA 目标是从轨迹中找出 **能解释下游失败的最小根因集合**，并产出可执行的纠正反馈。

  #### 4.3.2 输入/输出
  - 输入：
    - 某次任务的事实图子图（主链 + retry分支）
    - 每个节点的 evidence 坐标（stdout/stderr/test/diff/ui等）
  - 输出（对每个失败终点/失败分支）：
    - `root_cause_nodes`: list[action_id]（最小集合）
    - `propagation_chain`: list[action_id]（根因→失败终点的传播链）
    - `error_module`: enum（memory/reflection/planning/action/system）
    - `error_type`: string（可扩展细分类：SWE/GU专项）
    - `corrective_actions`: list（修复动作模板 + 参数）
    - `preventive_checks`: list（规划阶段应插入的检查/验证动作）
    - `confidence`: float（可由LLM自评 + 后续统计校准）
    - `evidence_refs`: list[pointer]

  > RCA 输出写入信念图（Attempt Belief & Atomic Belief seeds），而不是改写事实图。

  ---

  ### 4.4 剪枝与提炼（Pruning & Distillation）
  目标：把“冗余探索/重复试错”剪掉，保留可复用经验骨架。

  #### 4.4.1 基于 RCA 的结构化剪枝（推荐）
  - 保留：
    1) 成功主链中的关键转折点 + 必要验证节点
    2) 失败分支的 root_cause_nodes + propagation_chain
    3) fail_retry 周围的“失败→修复→结果”最短路径
  - 删除/降权：
    - 根因之后、对修复无新增信息的重复尝试
    - 与当前根因无关的旁支探索

  输出：
  - `success_skeleton_subgraph`
  - `failure_repair_subgraph`
  - `distilled_task_summary`（用于 task-level embedding）

  ---

  ### 4.5 环境适配经验（Env-adaptation Beliefs）：统计规律的提取与固化
  你希望系统能在不同工作环境中迅速学到“适配流程”（例如 action A 前先检查 env）。实现为：

  #### 4.5.1 环境签名（env_signature）与环境簇（env_cluster）
  - env_signature 从 problem file 的 evidence 层抽取并规范化：
    - 工具链版本、关键env var是否存在、PATH片段hash、容器/代理、工作目录等
  - env_cluster：对 env_signature 聚类或规则化分桶（用于条件化泛化）

  #### 4.5.2 候选规律生成（两种并行）
  1) **不变式/近似不变式发现**
  - 在“成功样本集合”中寻找几乎总成立的检查动作/环境条件（如“成功前必有version check”）

  2) **提升效应检验（uplift / association test）**
  - 对候选检查动作 X：
    - 比较相似条件下 `P(success | do X)` vs `P(success | not X)`
    - 计算 uplift + 不确定性（CI/贝叶斯）
  - 将“根因传播严重度”作为加权项：高严重度根因优先固化为约束/偏好

  #### 4.5.3 输出为 Atomic Belief（env_adaptation）
  - Rule 示例：
    - IF env_cluster=E1 AND action_type=run_test THEN DO check_env_vars BEFORE run_test
    - evidence_refs 指向支持该规律的历史 action 节点集合
  - stats 用于后续硬/软约束量化（见 7）

  ---

  ## 5. 经验使用链路：两种注入范式 + 证据坐标返回

  ### 5.1 范式 A：Planning-time 经验注入（流程经验 + 预防性经验）
  触发：Agent 进入规划阶段（生成 plan 或候选 action 序列）

  流程：
  1) **Query Rewriting（由 Memory Agent 生成可检索 query）**
  - 输入：用户指令 + 当前上下文摘要 + env_signature + 目标文件范围推断
  - 输出：结构化 query（任务级 + 关键约束）

  2) **Task-level 检索**
  - 目标：检索“相似任务”的成功 skeleton + 高置信 workflow/env beliefs
  - 使用多视角 embedding（任务语义/文件范围/工具栈）

  3) **子图提取**
  - 从检索结果中提取：
    - `success_next` 主链骨架 + 关键验证节点
    - 相关 env_adaptation belief（例如应插入的检查）

  4) **LLM 精炼整合**
  - 输出：`planning_tips`（流程模板、验证步骤、注意事项）
  - 必须附：`evidence_refs`（指向经验来源坐标）

  5) **注入到规划上下文**
  - 作为提示/约束影响 plan 生成（软指导）
  - 同时为 PDDL3 preferences/constraints 提供候选（见 7）

  预期收益：
  - 规划更贴近历史成功模板
  - 更早引入验证动作，抑制级联失败
  - 针对环境变动，自动加入“低成本检查动作”

  ---

  ### 5.2 范式 B：Execution-time 出错回忆（易错点经验 + 修复建议）
  触发：执行中遇到报错/异常返回/未达预期状态

  流程：
  1) **构造检索 query**
  - 输入：当前 error_signature + 当前 problem file（intent + tool call + env_signature）
  - 输出：action-level query（聚焦错误模式与修复）

  2) **Action-level 检索**
  - 优先检索 `fail_retry` 结构附近的相似失败-修复模式
  - 更偏重 error_sig / tool_output / intent 的向量

  3) **生成修复建议**
  - 输出：`next_step_fix`（下一步可执行动作）
  - 附带：
    - `evidence_refs`（坐标）
    - `expected_outcome`（期望验证信号，如“测试应通过/错误应消失”）
    - 可选：`validator_check`（执行前可做的fail-fast检查）

  4) **注入并执行**
  - 原 agent 根据建议执行
  - 若失败：回传失败 → Memory Agent 通过 evidence 坐标回放原文再分析并更新信念

  预期收益：
  - 显著提高高错动作一次通过率
  - 减少重复试错与无效探索

  ---

  ## 6. Memory Agent：一个可评估的“记忆智能体”服务

  ### 6.1 Memory Agent 的职责（必须可测）
  1) **Query Rewriting**：将自然语言任务描述改写成结构化可检索 query
  2) **Subgraph Selection**：从 KG 中选择最有用的经验子图（而非简单 top-k 节点）
  3) **Experience Distillation**：压缩为可执行建议/流程tips/约束候选
  4) **Evidence Referencing**：返回证据坐标，支持回放与追责
  5) **Belief Update**：异步更新信念统计与状态（promote/deprecate）

  ### 6.2 Memory Agent 输出规范（强制）
  所有输出必须包含：
  - `recommendations`
  - `evidence_refs`（坐标列表）
  - `confidence`
  - `assumptions`（可选，便于审计）
  - `failure_mode_if_wrong`（可选，便于诊断）

  ---

  ## 7. 经验编译：从 Belief 到 PDDL3 Preferences / Constraints + Validator（fail-fast）

  ### 7.1 定位
  PDDL3 不用于求解最优计划，而用于表达：
  - 轨迹偏好（preferences）：排序候选 action/plan
  - 轨迹硬约束（constraints）：过滤明显无效或高风险方案（fail-fast）

  ### 7.2 经验固化规则（从统计到 hard/soft）
  对每条 Atomic Belief 维护统计量：
  - `support_n`
  - `uplift`
  - `uncertainty`（置信下界）
  - `severity`（可选：根因传播严重度加权）

  固化策略（示例）：
  - Promote to **preference**：
    - support ≥ N_min AND uplift > 0 AND CI_lower > 0
  - Promote to **constraint**：
    - support ≥ N_hard AND (failure_without is high) AND check_cost is low
    - 或：root-cause severity 加权后风险极高

  ### 7.3 Validator（候选过滤）
  - 输入：候选动作/短程计划 + 约束集
  - 输出：valid/invalid + 违反项解释（附 evidence refs / belief id）

  ---

  ## 8. 防膨胀与迁移：遗忘与技能固化

  ### 8.1 遗忘（forgetting）按“任务子图”粒度
  触发条件（示例）：
  - 子图 age > threshold
  - 且子图内所有节点在最近窗口均未被访问/检索命中（access < threshold）

  动作：
  - 归档/删除该任务子图（事实图）
  - 信念图保留抽象后的 Atomic Beliefs（若仍被命中）

  ### 8.2 技能固化（Skill Document）
  当某条经验稳定且显著（如成功率≥85%，支持样本充足）：
  - 将其抽象为标准化 skill 文档（执行手册）
  - 从图谱迁出以减少占用
  - skill 文档作为高层知识源供 Agent 调用

  ---

  ## 9. 评测与可复现性（论文与实现必须覆盖）

  ### 9.1 SWE 指标（建议）
  - Task success rate（SWE-bench/自建任务集）
  - Fix success rate（N步内修复成功）
  - Wasted actions reduction（无效动作减少）
  - Cascade failure rate（级联失败减少，基于 RCA propagation_span）
  - Retrieval precision/recall@k（命中“最终有用经验”比例）
  - Constraint violation rate（被 fail-fast 拦截比例 + 拦截后成功率变化）

  ### 9.2 GUI 指标（建议）
  - Action success rate / completion rate
  - Recovery rate from common GUI failures（定位/焦点/加载态）
  - Steps to completion
  - Coverage/bug-finding（若做测试类任务）
  - 多模态检索命中率（UI state 相似检索质量）

  ### 9.3 Ablation（必须）
  - 无记忆 vs 仅向量检索 vs 加 KG 结构 vs 加 RCA vs 加 belief 统计 vs 加 PDDL validator
  - planning-only vs execution-only vs 二者结合
  - evidence-only 注入 vs inference-only 注入 vs 分离策略

  ---

  ## 10. 实现模块清单（工程落地）

  ### 10.1 在线模块（执行时）
  - `ActionLogger`：生成 problem file + evidence pointers
  - `KGWriter`：写节点/边 + embeddings
  - `Retriever`：分层检索（task/action，multi-view）
  - `MemoryAgentService`：提供 query rewrite / subgraph select / distill
  - `Injector`：planning/execution 注入器
  - `Validator`：约束/偏好检查（fail-fast）

  ### 10.2 异步模块（任务结束后）
  - `RCAAgent`：最小根因集合 + 传播链（模仿 2509.25370）
  - `PrunerDistiller`：生成 skeleton subgraph
  - `BeliefUpdater`：生成/更新 attempt & atomic beliefs + 统计
  - `Compiler`：belief → preferences/constraints
  - `ForgettingManager`：子图级遗忘/归档
  - `SkillPromoter`：经验固化为 skill 文档

  ---

  ## 11. 关键设计决策总结（写作要点）

  - **两类边（success_next / fail_retry）**：显式拆分流程经验与易错点经验，分别服务 planning 与 execution。
  - **事实图 vs 信念图**：证据可验证、推断可推翻，避免错误经验固化。
  - **异步 RCA + 传播链**：避免只学“最后一步报错”，用最小根因解释级联失败，支撑剪枝与约束权重化。
  - **统计化 env-adaptation beliefs**：让 agent 在新环境中通过多次执行迅速学到“低成本检查动作”的流程适配规律。
  - **证据坐标返回**：保证可追责与复盘；失败可回放 evidence 原文再提炼。
  - **PDDL3 + validator**：定位为 guardrail（排序+过滤），而非完整 classical planning 求解。

  ---

  ## 12. 最小可行版本（MVP）建议（便于快速实现与写论文）

  MVP 必须包含：
  1) problem file + evidence pointers + 多视角 embedding
  2) 事实图（两类边）+ 分层检索（task/action）
  3) execution-time fail_retry 回忆修复（带 evidence refs）
  4) 异步 RCA（至少能给 root_cause_nodes + 修复建议）并写入 belief graph
  5) belief 统计（support/uplift）+ 简单 promote 规则（soft preference）

  可选增强（后续版本）：
  - GUI 多模态 emb_ui_state
  - PDDL3 constraints + validator fail-fast
  - 技能固化与遗忘策略
  - 冲突消解（条件化版本化 belief）

  ---
