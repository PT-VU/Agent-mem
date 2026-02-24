# SWE-agent 接入外部可插拔工具 更改手册

本手册目标：只对 SWE-agent 做最小改动，让其可加载外部 Hook；Tool A / Tool B 的业务代码全部放在 `PDDL_work_mem/`。

## 1. 设计原则
- SWE-agent 内只保留“接线能力”，不内置 Tool A/Tool B 业务逻辑。
- 外部工具可替换：只改环境变量或替换外部目录代码即可。
- 主流程健壮：外部工具失败不会让 agent 崩溃。

## 2. 外部工具代码位置
- `PDDL_work_mem/tools/sweagent_ext_tools/bridge_hook.py`
- `PDDL_work_mem/tools/sweagent_ext_tools/dispatcher.py`
- `PDDL_work_mem/tools/sweagent_ext_tools/tools/tool_a.py`
- `PDDL_work_mem/tools/sweagent_ext_tools/tools/tool_b.py`
- `PDDL_work_mem/tools/sweagent_ext_tools/bin/run_tool_a.sh`
- `PDDL_work_mem/tools/sweagent_ext_tools/bin/run_tool_b.sh`

## 3. SWE-agent 最小改动清单

### 3.1 增加 Hook 事件：`on_action_error`
文件：
- `SWE-agent/sweagent/agent/hooks/abstract.py`

改动点：
1. 在 `AbstractAgentHook` 增加：
```python
def on_action_error(self, *, step: StepOutput, error_type: str, error_message: str): ...
```
2. 在 `CombinedAgentHook` 增加同名分发方法，循环调用所有子 hook。

目的：
- 为“命令执行报错/异常”提供统一扩展点。

### 3.2 在 Agent 错误路径触发 `on_action_error`
文件：
- `SWE-agent/sweagent/agent/agents.py`

改动点：
1. 在 `forward_with_handling()` 中，重试类错误和退出类错误都调用：
```python
self._chook.on_action_error(step=step, error_type=..., error_message=...)
```
2. 在 `handle_action()` 执行命令后，当命令 exit code 非 0 时触发：
```python
self._chook.on_action_error(
    step=step,
    error_type="command_nonzero_exit",
    error_message=f"Command exited with code {self._env.last_exit_code}",
)
```

目的：
- 让 Tool B 不仅能处理异常抛出，也能处理“命令返回非零”的常见报错。

### 3.3 在环境对象保存最近一次命令退出码
文件：
- `SWE-agent/sweagent/environment/swe_env.py`

改动点：
1. 在 `SWEEnv.__init__` 添加：
```python
self.last_exit_code: int | None = None
```
2. 在 `communicate()` 调用 runtime 后记录：
```python
self.last_exit_code = r.exit_code
```

目的：
- 给 `agents.py` 提供非零退出码判断依据。

### 3.4 增加“外部 Hook 加载器”（通用，不含工具业务）
文件：
- `SWE-agent/sweagent/agent/hooks/plugin_loader.py`（新增）

能力：
- 从环境变量动态加载外部 hook 类并挂到 agent 上。

关键环境变量：
- `SWE_AGENT_EXTERNAL_HOOK_CLASS`：`<module.path>:<ClassName>`
- `SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH`：额外 import 路径（可选）
- `SWE_AGENT_EXTERNAL_HOOK_KWARGS_JSON`：hook 初始化参数 JSON（可选）

### 3.5 在运行入口挂载外部 Hook
文件：
- `SWE-agent/sweagent/run/run_single.py`
- `SWE-agent/sweagent/run/run_batch.py`
- `SWE-agent/sweagent/run/run_shell.py`

改动点：
1. 导入 `add_external_agent_hook_from_env`
2. 在 agent 创建后立即调用该函数

目的：
- 无需改 YAML schema，直接通过环境变量启用可插拔 Hook。

## 4. 启用方式（当前目录结构）

在运行 `sweagent` 前设置：

```bash
export SWE_AGENT_EXTERNAL_HOOK_CLASS="PDDL_work_mem.sweagent_ext_tools.bridge_hook:ExternalToolBridgeHook"
export SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH="/home/pt/SWE-bench"
export SWE_AGENT_EXT_TOOL_A_CMD="/home/pt/SWE-bench/PDDL_work_mem/tools/sweagent_ext_tools/bin/run_tool_a.sh"
export SWE_AGENT_EXT_TOOL_B_CMD="/home/pt/SWE-bench/PDDL_work_mem/tools/sweagent_ext_tools/bin/run_tool_b.sh"
export SWE_AGENT_EXT_TOOL_TIMEOUT_SEC="2.0"
export SWE_AGENT_EXT_TOOLS_LOG_FILE="/tmp/sweagent_ext_tools.log"
```

可选：`SWE_AGENT_EXTERNAL_HOOK_KWARGS_JSON`
```bash
export SWE_AGENT_EXTERNAL_HOOK_KWARGS_JSON='{"timeout_sec": 3.0}'
```

## 5. 验证步骤

### 5.0 一键脚本（推荐入口）
```bash
bash /home/pt/SWE-bench/PDDL_work_mem/tools/sweagent_ext_tools/bin/start_with_external_tools.sh --smoke-test
```

或直接包裹任意 SWE-agent 命令：
```bash
bash /home/pt/SWE-bench/PDDL_work_mem/tools/sweagent_ext_tools/bin/start_with_external_tools.sh \
  sweagent run-batch --config config/default.yaml ...
```

### 5.1 单独验证 Tool A/B 脚本
```bash
export SWE_AGENT_EXT_EVENT_JSON='{"event":"plan_generated","action":"ls"}'
bash /home/pt/SWE-bench/PDDL_work_mem/tools/sweagent_ext_tools/bin/run_tool_a.sh

export SWE_AGENT_EXT_EVENT_JSON='{"event":"action_error","error_type":"runtime_error"}'
bash /home/pt/SWE-bench/PDDL_work_mem/tools/sweagent_ext_tools/bin/run_tool_b.sh
```

预期：
- 控制台打印 `[Tool A]` / `[Tool B]`
- `/tmp/sweagent_ext_tools.log` 出现对应 JSON 行

### 5.2 在 SWE-agent 运行中验证
运行任意 `sweagent run` 或 `run-batch`：
- 每次动作生成后触发 Tool A
- 命令报错/异常时触发 Tool B

### 5.3 自动 smoke test 覆盖内容
`--smoke-test` 会自动验证：
- planning 触发 Tool A
- 异常路径触发 Tool B（`environment_error`）
- 非零退出码触发 Tool B（`command_nonzero_exit`）

## 6. 故障排查
- `ModuleNotFoundError`：检查 `SWE_AGENT_EXTERNAL_HOOK_PYTHONPATH` 是否包含 `/home/pt/SWE-bench`
- 外部脚本未执行：检查 `SWE_AGENT_EXT_TOOL_A_CMD/B_CMD` 路径可执行权限
- 外部工具超时：调大 `SWE_AGENT_EXT_TOOL_TIMEOUT_SEC`
- 主流程不应中断：即使 A/B 失败，SWE-agent 只应记录 warning
