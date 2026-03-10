# Agent-mem 接入 SWE-agent 差异评估（更新于 2026-02-22）

## A. 已对齐到 MVP 可用（本轮完成）
1. Hook 跨进程任务连续性与生命周期收口
- 已实现：`active_tasks.json` 持久化 + `run_done` 清理。
- 证据：`PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/integration/sweagent_adapter.py`，`PDDL_work_mem/tools/sweagent_ext_tools/bridge_hook.py`。

2. 主链路 embedding 正式接入
- 已实现：`KGWriter` 支持 `sentence-transformers`，不可用时 deterministic fallback。
- 证据：`PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/processing/kg_writer.py`。

3. `search_experience()` 正式返回逻辑
- 已实现：返回 `results/recommendations/belief_hints/assumptions/failure_mode_if_wrong`，含 evidence refs。
- 证据：`PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/integration/sweagent_adapter.py:417`。

4. embedding 相似检索从占位改为可用
- 已实现：`ObservationKG.find_similar_actions()` 加权余弦相似；`GraphStore.find_similar_actions()` embedding-first + lexical fallback。
- 证据：`PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/core/observation_kg.py:232`，`PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/storage/graph_store.py:235`。

5. belief 更新闭环从占位改为可用
- 已实现：`run_done` 触发 `MemoryAgent.update_beliefs()`，创建 attempt belief + upsert atomic belief + 统计更新。
- 证据：`PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/retrieval/memory_agent.py:545`，`PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/integration/sweagent_adapter.py:255`。

## B. 仍与目标架构有差距（下一阶段）
1. PDDL guardrail（preference/constraint 编译 + validator）未落地
- 影响：还不能做“软偏好排序 + 硬约束 fail-fast”的完整研究链。

2. RCA 异步复盘未接入主执行闭环
- 影响：根因传播链还未形成自动反馈到 belief 的完整通路。

3. GUI 多模态记忆（`emb_ui_state`）未落地
- 影响：OSWorld/GUI 方向仍缺少同等能力。

4. 高并发写入锁未加在 `active_tasks.json`
- 影响：极端并行下有小概率任务映射竞争。

## C. 当前可直接支持的实验能力
- no-mem vs with-mem 对照可跑。
- with-mem 能输出：
  - repair suggestion 递增效果（随历史累积）
  - task-level belief update 结果
  - formal search results with evidence refs
- 运行证据：`PDDL_work_mem/实验/实验02/mvp_alignment_recheck_20260222_011055/mvp_alignment_summary.json`
