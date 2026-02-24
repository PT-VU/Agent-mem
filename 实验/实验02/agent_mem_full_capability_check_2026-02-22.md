# Agent-mem 完全可用性测试（2026-02-22）

## 1) 测试范围
- 是否“满血版可用”
- 嵌入模型是否接入运行主链路
- 知识图谱构建是否可用
- 知识图谱检索是否可用（真实 Hook 运行模式）

## 2) 环境与进程状态
- 已按要求暂停带记忆全量实验进程（`run_lite_windowed_with_mem.sh`）
- 测试目录：
  - `PDDL_work_mem/实验/实验02/healthcheck_20260222_004624`
  - `PDDL_work_mem/实验/实验02/full_capability_check_20260222_004819`

## 3) 测试结果
### 3.1 嵌入模型安装/加载
- `SWE-agent/.venv` 中 `sentence_transformers` 可导入
- 可成功加载模型 `all-MiniLM-L6-v2`
- 向量维度 `384`

结论：**模型包可用**。

### 3.2 嵌入模型是否接入 Agent-mem 主链路
- 当前主链路（`SWEAgentAdapter -> KGWriter -> EmbeddingGenerator`）使用 `agent_mem/processing/kg_writer.py`
- 该 `EmbeddingGenerator` 为随机向量占位实现（`_generate_random_embedding`）
- 运行时实例也确认 `adapter.kg_writer.embedding_generator` 为该占位类

结论：**未满血接入**（当前不是 sentence-transformers 驱动的真实 embedding）。

### 3.3 知识图谱构建
- Tool A/B 注入后，落盘文件存在：
  - `observation_kg.json`
  - `belief_graph.json`
  - `metadata.json`
- 样例中动作节点可写入，且 embedding 字段维度为 384

结论：**KG 构建可用**。

### 3.4 知识图谱检索（真实 Hook 模式）
测试方式：连续 3 次独立进程调用 `run_tool_b.sh`（与 SWE-agent hook 实际调用方式一致），共用同一 storage。

结果：
- 3 次返回均为：`repair_suggestions=0`、`confidence=0.0`
- 每次 `task_id` 都是新值
- KG 中形成的是多个单动作 task（`kg_task_count=3, kg_action_count=3`）

结论：**检索链路“可调用但在真实 hook 运行模式下基本不产出有效建议”**，当前不可视为满血可用。

## 4) 质量门禁（项目既定命令）
- `pytest PDDL_work_mem/tools/sweagent_ext_tools/agent_mem/tests -q` -> `12 passed`
- `pytest PDDL_work_mem/tools/sweagent_ext_tools/tests -q` -> `2 skipped`
  - skip 原因：缺少可选依赖 `swerex/sweagent`

## 5) 总结结论
- 嵌入模型包：可用
- KG 构建：可用
- KG 检索：代码能力存在，但真实 hook 运行形态下效果不可用（建议为空）
- 综合判断：**当前 Agent-mem 不是“满血版可用”，属于“部分可用（数据写入可用，检索收益未打通）”**
