# SWE-agent 外部工具 A/B 集成实施计划（可直接指导代码编写）

## 1. 目标与边界

### 1.1 目标
在 SWE-agent 中增加两个外部工具触发点：
1. **工具 A**：每次 Agent 完成“本步计划产出”（即得到 thought + action）时调用一次。
2. **工具 B**：每次 Agent 在“执行命令后出现错误”时调用一次。

### 1.2 本阶段范围（POC）
- 不设计 A/B 的业务逻辑。
- A/B 先通过 `print`/日志证明已被调用。
- 保证即使 A/B 调用失败，也不影响主流程（非阻塞、失败降级）。

### 1.3 非目标
- 不改变模型推理策略。
- 不实现复杂告警系统、消息队列或远程 RPC。
- 不改动评测逻辑。

---

## 2. 现状与注入点（基于当前代码）

### 2.1 “计划完成”触发点（A）
`DefaultAgent.forward()` 在解析完模型输出后会触发：
- 文件：`SWE-agent/sweagent/agent/agents.py`
- 位置：`step.thought, step.action = self.tools.parse_actions(output)` 之后，已有 `self._chook.on_actions_generated(step=step)`

这就是“每步计划已形成”的最佳注入点。

### 2.2 “命令报错”触发点（B）
命令执行/动作执行错误主要在：
- `DefaultAgent.handle_action()` 调用 `_env.communicate(...)`
- `DefaultAgent.forward_with_handling()` 对异常分支做重试或退出

其中与“执行命令报错”直接相关的典型分支：
- `BashIncorrectSyntaxError`
- `CommandTimeoutError`
- `_BlockedActionError`
- `SwerexException` / `RuntimeError`（执行期错误）

当前 Hook 只有 `on_action_executed`，缺少统一错误回调，因此需要扩展 Hook 接口。

---

## 3. 设计决策（推荐实现）

### 3.1 采用 Agent Hook 扩展，不直接硬编码业务
新增一个专门的 Agent Hook（例如 `ExternalToolsAgentHook`），把调用 A/B 的逻辑隔离在 Hook 层，避免污染核心推理代码。

### 3.2 新增错误事件 Hook
在 `AbstractAgentHook` 与 `CombinedAgentHook` 中新增：
- `on_action_error(...)`

由 `DefaultAgent.forward_with_handling()` 在相关异常分支中触发，保证 B 可以稳定收到“命令报错事件”。

### 3.3 外部命令通过 subprocess 调用
A/B 都用 `subprocess.run(...)` 调用本地命令，支持超时与失败降级：
- 超时：例如 2 秒
- 失败：记录 warning，不抛出到主流程

---

## 4. 代码改动计划（按文件）

## 4.1 扩展 Hook 接口
### 文件
- `SWE-agent/sweagent/agent/hooks/abstract.py`

### 变更
1. 在 `AbstractAgentHook` 新增方法签名：
   - `on_action_error(self, *, step: StepOutput, error_type: str, error_message: str): ...`
2. 在 `CombinedAgentHook` 中实现分发：
   - 遍历 `self.hooks` 调用各 hook 的 `on_action_error(...)`

### 验收
- 现有 hook 不实现该方法时不报错（默认空实现）。

---

## 4.2 新增外部工具 Hook 实现
### 文件（新增）
- `SWE-agent/sweagent/agent/hooks/external_tools.py`

### 结构建议
新增类：`ExternalToolsAgentHook(AbstractAgentHook)`

核心字段：
- `tool_a_cmd: str | None`
- `tool_b_cmd: str | None`
- `timeout_sec: float = 2.0`

核心方法：
1. `_safe_call_external(cmd: str, payload: dict) -> None`
   - `subprocess.run(..., shell=True, timeout=timeout_sec, check=False)`
   - payload 通过环境变量注入（如 `SWE_EXT_EVENT_JSON`）或拼接参数
   - 异常仅 log，不 raise
2. `on_actions_generated(...)`
   - 调工具 A
   - payload 至少包含：`event=plan_generated`, `thought`, `action`
3. `on_action_error(...)`
   - 调工具 B
   - payload 至少包含：`event=action_error`, `error_type`, `error_message`, `action`

### POC 打印建议
A/B 脚本先实现：
- 输出固定前缀（如 `[TOOL_A_CALLED]` / `[TOOL_B_CALLED]`）
- 输出时间戳和关键字段

---

## 4.3 在 Agent 错误路径触发 on_action_error
### 文件
- `SWE-agent/sweagent/agent/agents.py`

### 变更
在 `forward_with_handling()` 中，对“命令相关错误”分支调用：
- `self._chook.on_action_error(step=step, error_type=..., error_message=...)`

建议落点：
1. 在 `handle_error_with_retry(...)` 内部统一触发一次（适用于重试类错误）
2. 在 `handle_error_with_autosubmission(...)` 内部统一触发一次（适用于退出类错误）

并确保 `step` 使用 `getattr(exception, "step", StepOutput())`，避免空对象。

### 推荐错误类型映射
- `FormatError` -> `format_error`
- `_BlockedActionError` -> `blocked_action`
- `BashIncorrectSyntaxError` -> `bash_syntax_error`
- `CommandTimeoutError` -> `command_timeout`
- `SwerexException` -> `environment_error`
- `RuntimeError` -> `runtime_error`

---

## 4.4 挂载 ExternalToolsAgentHook（run / run-batch）
### 文件
- `SWE-agent/sweagent/run/run_single.py`
- `SWE-agent/sweagent/run/run_batch.py`

### 方案（POC 推荐：环境变量启用）
通过环境变量控制是否启用，不先改大规模配置 schema：
- `SWE_AGENT_EXT_TOOL_A_CMD`
- `SWE_AGENT_EXT_TOOL_B_CMD`
- `SWE_AGENT_EXT_TOOL_TIMEOUT_SEC`（可选）

在创建 agent 后、运行前：
- 若 A/B 任一变量存在，则 `agent.add_hook(ExternalToolsAgentHook(...))`

### 后续可升级
再把上述参数正式并入 `RunSingleConfig/RunBatchConfig` 或 `AgentConfig`。

---

## 4.5 增加最小文档
### 文件
- `SWE-agent/docs/` 下新增一页（例如 `docs/usage/external_hooks.md`）
- 或更新 `docs/usage/adding_custom_tools.md`

### 内容
- 如何配置 A/B 命令
- 示例脚本
- 日志中如何确认调用成功

---

## 5. 开发顺序（可直接执行）

1. 改 `hooks/abstract.py` 增加 `on_action_error`。
2. 新增 `hooks/external_tools.py`，实现 `ExternalToolsAgentHook`。
3. 改 `agents.py` 在错误分支调用 `_chook.on_action_error(...)`。
4. 改 `run_single.py` / `run_batch.py`，按环境变量自动挂载新 hook。
5. 写最小文档。
6. 本地验证（见第 6 节）。

---

## 6. 验证计划（POC）

## 6.1 准备两个外部脚本
例如：
- `/tmp/tool_a.sh`
- `/tmp/tool_b.sh`

脚本内容仅打印收到的事件与参数，并写入文件（如 `/tmp/sweagent_ext_hooks.log`）。

## 6.2 设置环境变量
- `export SWE_AGENT_EXT_TOOL_A_CMD="/tmp/tool_a.sh"`
- `export SWE_AGENT_EXT_TOOL_B_CMD="/tmp/tool_b.sh"`

## 6.3 触发 A（计划阶段）
跑一个最小 `sweagent run`（任意可执行任务）。
预期：每个 step 至少触发一次 A 日志。

## 6.4 触发 B（命令报错阶段）
让 agent 执行一个明确会失败的动作（如语法错误命令、被 block 的命令、超时命令）。
预期：对应错误分支触发 B 日志。

## 6.5 稳定性检查
- 人为让 `/tmp/tool_a.sh` 返回非零退出码。
- 预期：SWE-agent 主流程不崩溃，只记录 warning。

---

## 7. 验收标准

满足以下即通过：
1. 每步 planning 完成后，A 被调用并可在日志中看到打印。
2. 命令执行报错时，B 被调用并可在日志中看到打印。
3. A/B 失败不影响 agent 主流程推进。
4. run 与 run-batch 两种入口都可启用此能力。

---

## 8. 风险与规避

1. **风险：错误分支覆盖不全**
   - 规避：在 `handle_error_with_retry` 与 `handle_error_with_autosubmission` 两个统一入口触发 B。
2. **风险：外部命令卡死**
   - 规避：`subprocess.run` 强制超时。
3. **风险：日志噪音过高**
   - 规避：只打一行摘要日志，并可通过环境变量开关 debug。

---

## 9. 二期演进（本次不做）

1. 将 A/B 配置项并入正式 YAML 配置（非环境变量）。
2. 为 A/B payload 定义结构化 schema（JSON）。
3. 将工具调用改为异步队列，降低对 step 延迟影响。
4. 增加自动化测试（mock subprocess）覆盖各错误分支。

---

## 10. 开始前答复（按最新约束）

### 10.1 是否可行
可行。  
可以把“工具实现”完全外置在 `PDDL_work_mem/`，SWE-agent 仅保留最小“接线点（hook call）”。  
这样满足：
1. 工具可插拔（替换命令/脚本即可切换实现）  
2. 接入成本低（按手册改少量源码）  
3. 工具代码与 SWE-agent 源码解耦（全部独立在 `PDDL_work_mem`）

### 10.2 目标架构（外置优先）
- `PDDL_work_mem/tools/sweagent_ext_tools/`
  - `tool_a.py`：计划事件处理（先 print）
  - `tool_b.py`：错误事件处理（先 print）
  - `dispatcher.py`：统一读取事件 JSON 并分发到 A/B
  - `adapters/sweagent_payload.py`：payload 解析与版本兼容
  - `bin/run_tool_a.sh`、`bin/run_tool_b.sh`：可执行入口
  - `README.md`：外置工具说明
- SWE-agent 中只保留：
  - 在 planning 后触发一次外部命令
  - 在命令报错/异常路径触发一次外部命令
  - 不嵌入业务逻辑

### 10.3 执行计划（本轮）
1. **整理与回退内置逻辑边界**
   - 审查当前已改动代码，把“业务行为”从 SWE-agent 中抽薄到最小触发层。
   - 保留通用 hook 触发点；不在 SWE-agent 中写工具细节。
2. **在 `PDDL_work_mem` 新建独立工具包**
   - 创建 `sweagent_ext_tools` 目录结构与 A/B 脚本。
   - 约定输入协议：`SWE_AGENT_EXT_EVENT_JSON`。
   - A/B 先实现 `print + 文件落日志` 验证链路。
3. **产出《SWE-agent 更改手册》**
   - 文档名建议：`PDDL_work_mem/SWEAgent_External_Tools_Change_Manual.md`
   - 内容包含：
     - 需要改动的最小文件与行级落点
     - 每处改动前后示例代码
     - 环境变量约定
     - run / run-batch / run-shell 启用方式
     - 验证步骤与预期日志
4. **最小接线改造（按手册落地）**
   - 仅保留触发器：planning -> A，error -> B。
   - 调用失败不影响主流程（超时/非零退出码只 warning）。
5. **端到端验收**
   - 用 1~2 个最小实例触发：
     - 正常 planning 触发 A
     - 命令错误触发 B
   - 输出验收记录到 `PDDL_work_mem/`（日志与结论）。

### 10.4 验收标准（本轮）
1. `PDDL_work_mem` 下存在完整独立工具代码，可单独运行。  
2. SWE-agent 只做最小接线改动，不承载工具业务逻辑。  
3. 按手册执行后，A/B 均能稳定打印触发信息。  
4. 工具异常不会导致 SWE-agent 主流程中断。  
