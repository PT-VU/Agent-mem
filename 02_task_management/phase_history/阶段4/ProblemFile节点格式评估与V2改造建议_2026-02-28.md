# ProblemFile 节点格式评估与 V2 改造建议（阶段4）

日期：2026-02-28  
范围：`PDDL_work_mem/source_code/sweagent_external_tools/agent_mem`  
目标：评估当前 ProblemFile 作为事实图节点信息的适配性，并给出可直接指导开发的改造方案。

---

## 1. 结论（先给判断）

当前 `ProblemFile` 结构**总体可用但不够“实验可解释 + 失败可学习 + 工程可演化”**。  
可以概括为：
1. 用于“基础记忆检索”已足够。
2. 用于“精细归因、失败模式学习、跨实验对比”信息密度不足。
3. 不建议推翻重做，应采用 **V2 增量升级 + 向后兼容迁移**。

建议：阶段4执行 `ProblemFile v2`，优先补齐可追踪字段与失败语义字段，保持旧数据可读。

---

## 2. 当前格式适配度评估

评估对象：
- `agent_mem/core/problem_file.py`
- `agent_mem/processing/action_logger.py`
- `agent_mem/processing/kg_writer.py`
- `agent_mem/integration/sweagent_adapter.py`

### 2.1 已满足（优点）
1. **核心主键完整**：`action_id`、`task_id`、`timestamp`。
2. **证据指针机制正确**：stdout/stderr/diff/tests/ui 均可用 pointer 管理，避免大文本塞节点。
3. **结果语义有基础覆盖**：`outcome` + `failure_signature` + `env_signature`。
4. **检索向量位已预留**：多视角 embedding 字段已存在。
5. **可序列化与回放链路打通**：`to_dict/from_dict` + GraphStore 持久化可用。

### 2.2 不足（关键问题）
1. **追踪上下文不足**
- 节点本体缺少一等字段：`instance_id`、`run_id`、`agent_name`、`source_event`、`step_index`。
- 这些信息目前散落在 `metadata` 和外部事件日志，导致跨实验归因困难。

2. **动作语义表达偏弱**
- `intent_text` 有，但缺少标准化 `action_text`（原始动作命令）与 `action_family`。
- 对“同意图不同命令”“同命令不同参数”难做稳定检索。

3. **失败语义粒度不足**
- `failure_signature` 的生成策略较粗（`error/exception/failure` 级别）。
- 缺少 `error_stage`、`is_timeout`、`exit_code`、`nonzero_exit` 等工程上关键失败标签。

4. **测试与补丁信号缺失**
- 缺少节点级 `patch_stats`（files_changed/added/deleted）。
- 缺少 `test_stats`（tests_run/passed/failed/fail_to_pass/pass_to_pass）。
- 导致 failure card、回退分析、成本评估需要回读大量外部日志。

5. **执行时延与成本信号缺失**
- 缺少 `duration_ms`、`tool_latency_ms`、`token_cost`（若可得）。
- 难以支持“降低时间与 token”的目标优化。

6. **Schema 演化能力弱**
- 当前无 `schema_version` 字段，后续迁移成本会升高。

7. **代码结构风险：重复模型定义**
- 另有 `agent_mem/models/problem_file.py` 的旧版重复定义，虽然当前基本未被主链使用，但会增加认知负担与误用风险。

8. **类型一致性细节问题**
- `ActionLogger._set_epistemic_tags` 传入字符串而非 `EpistemicTag` 枚举；虽可运行，但不够严格。

---

## 3. 是否需要改？答案与原则

答案：**需要改，但应做增量改而非重构重写。**

原则：
1. 维持 `ProblemFile` 作为节点原子，不把大文本塞进节点。
2. 新增字段优先“高价值、低侵入、可默认值回填”。
3. 先补可观测和失败学习字段，再做高级抽象字段。
4. 保证旧 JSON 能被 `from_dict` 正常读取。

---

## 4. ProblemFile V2 字段建议（按优先级）

## 4.1 P0（阶段4必须）

### A. 追踪字段（归因必需）
- `schema_version: str`（建议 `"2.0"`）
- `instance_id: str | None`
- `run_id: str | None`
- `agent_name: str | None`
- `source_event: str | None`（`plan_generated` / `action_error` / `action_success` / `run_done`）
- `step_index: int | None`

价值：把“实验归因链”从外部日志回拉到节点层。

### B. 动作表达字段（检索必需）
- `action_text: str`（原始动作命令或工具调用文本）
- `action_family: str | None`（如 `bash`/`str_replace`/`pytest`）

价值：减少仅靠 `intent_text` 检索带来的语义漂移。

### C. 失败结构化字段（失败学习必需）
- 在 `failure_signature` 中补：
  - `error_stage`（planning/execution/test/submission）
  - `exit_code`（若有）
  - `is_timeout`（bool）
  - `is_command_nonzero`（bool）

价值：支持 failure card 自动抽取与策略分型。

## 4.2 P1（建议阶段4完成）

### D. 补丁与测试摘要字段
- `patch_stats`:
  - `files_changed`
  - `lines_added`
  - `lines_deleted`
- `test_stats`:
  - `tests_run`
  - `tests_passed`
  - `tests_failed`
  - `fail_to_pass_failed`
  - `pass_to_pass_failed`

价值：不依赖外部 report 即可在节点层做回退诊断。

### E. 执行质量字段
- `execution_stats`:
  - `duration_ms`
  - `tool_latency_ms`
  - `retry_count`

价值：支撑“降低时间/成本”的优化目标。

## 4.3 P2（可延期）

### F. 约束/验证桥接字段（面向后续 PDDL/validator）
- `validator_signals`:
  - `constraint_violations`
  - `preference_hits`

价值：为后续“可验证经验约束”提供数据桥。

---

## 5. 建议的 V2 最小 JSON 形态（示例）

```json
{
  "schema_version": "2.0",
  "action_id": "...",
  "task_id": "...",
  "instance_id": "django__django-11797",
  "run_id": "exp02_first50_withmem",
  "agent_name": "main",
  "source_event": "action_error",
  "step_index": 42,
  "timestamp": "...",
  "action_type": "tool_call",
  "action_family": "bash",
  "intent_text": "Run targeted tests after patch",
  "action_text": "pytest tests/lookup/test_x.py -q",
  "inputs": {},
  "tool_calls": [],
  "outcome": "fail",
  "failure_signature": {
    "error_type": "AssertionError",
    "error_tokens": ["assert", "failed"],
    "error_stage": "test",
    "exit_code": 1,
    "is_timeout": false,
    "is_command_nonzero": true
  },
  "patch_stats": {
    "files_changed": 1,
    "lines_added": 7,
    "lines_deleted": 2
  },
  "test_stats": {
    "tests_run": 3,
    "tests_passed": 2,
    "tests_failed": 1
  }
}
```

---

## 6. 改造影响面（开发者视角）

涉及文件建议：
1. `agent_mem/core/problem_file.py`
2. `agent_mem/processing/action_logger.py`
3. `agent_mem/integration/sweagent_adapter.py`
4. `agent_mem/processing/kg_writer.py`
5. `agent_mem/tests/test_core.py`
6. `source_code/sweagent_external_tools/test_integration.py`

### 6.1 对检索的直接收益
- 可按 `source_event + error_stage + action_family` 精准筛选候选。
- 可把“失败后修复”经验从泛化建议提升到可执行建议。

### 6.2 对实验分析的直接收益
- 节点层可直接统计“注入后 N 步变化”。
- `only_no` 回退样本可以自动抽取共性错误模式。

---

## 7. 向后兼容与迁移计划

## 7.1 兼容策略
1. `from_dict` 采用“缺字段默认值”策略，兼容 v1 历史数据。
2. 新字段默认 `None` 或空结构，不阻断旧数据加载。
3. 持久化写入时统一写 `schema_version`。

## 7.2 迁移步骤（建议）
1. 先改数据类与序列化。
2. 再改 ActionLogger 填充新字段。
3. 再改 Adapter 透传 event 数据（instance/run/step）。
4. 最后改检索与统计使用新字段。

---

## 8. 非目标（本次不建议做）

1. 不把原始 stdout/stderr/diff 正文放入 ProblemFile 节点。
2. 不一次性引入复杂多模态 schema。
3. 不在阶段4做“全量历史数据回写重算 embedding”。

---

## 9. 最终建议

`ProblemFile` 作为节点格式的方向是正确的，但要从“可记录”升级到“可归因、可学习、可比较”。  
阶段4推荐执行 **V2 增量升级**：
1. 先补追踪与失败结构化字段（P0）。
2. 再补 patch/test/execution 摘要（P1）。
3. 保持向后兼容，避免影响现有实验资产。

这会显著提高 AgentMem 在下一轮对照实验中的可解释性和优化效率。
