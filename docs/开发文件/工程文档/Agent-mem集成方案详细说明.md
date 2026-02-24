# Agent-mem集成方案详细说明

## 1. 集成目标与原则

### 1.1 集成目标
1. **最小侵入**：对SWEAgent进行最小化改造
2. **可插拔**：通过配置开关启用/禁用Agent-mem
3. **向后兼容**：不影响现有功能，支持平滑回滚
4. **性能可控**：不影响Agent主流程性能

### 1.2 设计原则
1. **Hook-based架构**：利用SWEAgent现有的hook系统
2. **异步处理**：耗时操作异步执行，不阻塞主流程
3. **降级处理**：Agent-mem故障时自动降级，不影响主流程
4. **配置驱动**：所有集成行为通过配置文件控制

## 2. 集成架构

### 2.1 整体集成架构
```
┌─────────────────────────────────────────────────────────┐
│                    SWEAgent 主进程                        │
│  ┌───────────────────────────────────────────────────┐  │
│  │              Agent-mem 集成层                      │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────┐  │  │
│  │  │ Memory Hook │  │ 轻量客户端  │  │ 本地缓存  │  │  │
│  │  └─────────────┘  └─────────────┘  └──────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
│                    │              │                     │
│                    ▼              ▼                     │
│          ┌─────────────────────────────────────┐       │
│          │        Agent-mem 服务进程            │       │
│          │  ┌─────────┬─────────┬─────────┐    │       │
│          │  │ 存储    │ 检索    │ 处理    │    │       │
│          │  │ 系统    │ 系统    │ 链路    │    │       │
│          │  └─────────┴─────────┴─────────┘    │       │
│          └─────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

### 2.2 集成模式
1. **嵌入式模式**：Agent-mem作为库直接集成到SWEAgent进程
2. **服务模式**：Agent-mem作为独立服务，通过gRPC/REST通信
3. **混合模式**：轻量组件嵌入式，重型组件服务化

## 3. SWEAgent改造点

### 3.1 Hook系统扩展

#### 3.1.1 新增Hook事件
在现有hook系统基础上新增以下事件：

```python
# 文件：SWE-agent/sweagent/agent/hooks/abstract.py

class AbstractAgentHook:
    # 现有方法...

    # 新增方法
    def on_action_logged(self, *, step: StepOutput, action_data: dict):
        """Action被记录时调用（每步执行后）"""
        pass

    def on_planning_start(self, *, task_description: str, context: dict):
        """规划开始时调用"""
        pass

    def on_execution_error(self, *, step: StepOutput, error_type: str,
                          error_message: str, error_details: dict):
        """执行错误时调用"""
        pass

    def on_task_complete(self, *, task_result: dict):
        """任务完成时调用"""
        pass
```

#### 3.1.2 扩展CombinedAgentHook
```python
# 文件：SWE-agent/sweagent/agent/hooks/combined.py

class CombinedAgentHook(AbstractAgentHook):
    # 现有代码...

    def on_action_logged(self, *, step, action_data):
        for hook in self.hooks:
            hook.on_action_logged(step=step, action_data=action_data)

    def on_planning_start(self, *, task_description, context):
        for hook in self.hooks:
            hook.on_planning_start(task_description=task_description, context=context)

    def on_execution_error(self, *, step, error_type, error_message, error_details):
        for hook in self.hooks:
            hook.on_execution_error(
                step=step,
                error_type=error_type,
                error_message=error_message,
                error_details=error_details
            )

    def on_task_complete(self, *, task_result):
        for hook in self.hooks:
            hook.on_task_complete(task_result=task_result)
```

### 3.2 Agent代码改造

#### 3.2.1 在DefaultAgent中添加Hook调用
```python
# 文件：SWE-agent/sweagent/agent/agents.py

class DefaultAgent:
    # 现有代码...

    def forward(self, state):
        # 现有代码...

        # 在生成action后调用on_action_logged
        step.thought, step.action = self.tools.parse_actions(output)

        # 调用现有hook
        self._chook.on_actions_generated(step=step)

        # 新增：记录action数据
        action_data = self._prepare_action_data(step, state)
        self._chook.on_action_logged(step=step, action_data=action_data)

        return step

    def _prepare_action_data(self, step, state):
        """准备action数据"""
        return {
            "thought": step.thought,
            "action": step.action,
            "state": {
                "observation": state.observation,
                "info": state.info
            },
            "timestamp": datetime.now().isoformat()
        }

    def forward_with_handling(self, state):
        # 现有代码...

        try:
            step = self.forward(state)
            # 执行action...
        except Exception as e:
            # 错误处理...

            # 新增：调用on_execution_error
            error_details = {
                "exception_type": type(e).__name__,
                "traceback": traceback.format_exc(),
                "step": getattr(e, "step", step)
            }
            self._chook.on_execution_error(
                step=step,
                error_type=self._classify_error(e),
                error_message=str(e),
                error_details=error_details
            )

            # 继续现有错误处理...

    def _classify_error(self, error):
        """错误分类"""
        error_mapping = {
            "FormatError": "format_error",
            "_BlockedActionError": "blocked_action",
            "BashIncorrectSyntaxError": "bash_syntax_error",
            "CommandTimeoutError": "command_timeout",
            "SwerexException": "environment_error",
            "RuntimeError": "runtime_error"
        }
        return error_mapping.get(type(error).__name__, "unknown_error")
```

#### 3.2.2 在handle_action中添加错误处理
```python
# 文件：SWE-agent/sweagent/agent/agents.py

class DefaultAgent:
    # 现有代码...

    def handle_action(self, step, state):
        # 现有代码...

        # 执行命令
        obs, _, _, info = self._env.step(action)

        # 新增：检查命令退出码
        if hasattr(self._env, "last_exit_code") and self._env.last_exit_code != 0:
            # 非零退出码视为错误
            self._chook.on_execution_error(
                step=step,
                error_type="command_nonzero_exit",
                error_message=f"Command exited with code {self._env.last_exit_code}",
                error_details={
                    "exit_code": self._env.last_exit_code,
                    "command": action,
                    "output": obs
                }
            )

        return obs, info
```

### 3.3 环境对象改造

#### 3.3.1 添加last_exit_code属性
```python
# 文件：SWE-agent/sweagent/environment/swe_env.py

class SWEEnv:
    def __init__(self, *args, **kwargs):
        # 现有代码...
        self.last_exit_code: Optional[int] = None

    def communicate(self, *args, **kwargs):
        # 现有代码...

        # 在执行命令后记录退出码
        r = self.runtime.communicate(
            input=input_str,
            timeout=timeout,
            **kwargs,
        )

        # 新增：记录退出码
        self.last_exit_code = r.exit_code

        return r
```

### 3.4 运行入口改造

#### 3.4.1 添加Agent-mem Hook加载
```python
# 文件：SWE-agent/sweagent/run/run_single.py

def run_single(config: RunSingleConfig):
    # 现有代码...

    # 创建agent后
    agent = create_agent(config.agent_config, env)

    # 新增：加载Agent-mem Hook
    if should_load_agent_mem(config):
        agent_mem_hook = create_agent_mem_hook(config)
        agent.add_hook(agent_mem_hook)

    # 继续现有代码...

def should_load_agent_mem(config):
    """检查是否应该加载Agent-mem"""
    # 检查环境变量
    if os.getenv("AGENT_MEM_ENABLED", "false").lower() == "true":
        return True

    # 检查配置文件
    if hasattr(config, "agent_mem") and config.agent_mem.get("enabled", False):
        return True

    return False

def create_agent_mem_hook(config):
    """创建Agent-mem Hook"""
    from agent_mem.integration import SWEAgentMemoryHook

    hook_config = {}
    if hasattr(config, "agent_mem"):
        hook_config = config.agent_mem

    return SWEAgentMemoryHook(config=hook_config)
```

#### 3.4.2 批量运行支持
```python
# 文件：SWE-agent/sweagent/run/run_batch.py

def run_batch(config: RunBatchConfig):
    # 现有代码...

    # 在每个任务开始时
    for task in tasks:
        # 创建agent...

        # 新增：加载Agent-mem Hook
        if should_load_agent_mem(config):
            agent_mem_hook = create_agent_mem_hook(config)
            agent.add_hook(agent_mem_hook)

        # 继续现有代码...
```

## 4. Agent-mem Hook实现

### 4.1 SWEAgentMemoryHook实现
```python
# 文件：agent_mem/integration/sweagent_hook.py

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

from sweagent.agent.hooks.abstract import AbstractAgentHook
from sweagent.types import StepOutput

from ..client import AgentMemClient
from ..config import AgentMemConfig

logger = logging.getLogger(__name__)

@dataclass
class HookConfig:
    """Hook配置"""
    enabled: bool = True
    mode: str = "embedded"  # embedded, service
    service_url: Optional[str] = None
    cache_size: int = 100
    timeout_seconds: float = 2.0

class SWEAgentMemoryHook(AbstractAgentHook):
    """SWEAgent记忆Hook"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = self._parse_config(config)
        self.client: Optional[AgentMemClient] = None
        self._cache = {}
        self._initialized = False

    def _parse_config(self, config) -> HookConfig:
        """解析配置"""
        if config is None:
            config = {}

        return HookConfig(
            enabled=config.get("enabled", True),
            mode=config.get("mode", "embedded"),
            service_url=config.get("service_url"),
            cache_size=config.get("cache_size", 100),
            timeout_seconds=config.get("timeout_seconds", 2.0)
        )

    def on_init(self, *, agent):
        """Hook初始化"""
        if not self.config.enabled:
            logger.info("Agent-mem hook disabled")
            return

        try:
            # 创建Agent-mem客户端
            agent_mem_config = AgentMemConfig(
                mode=self.config.mode,
                service_url=self.config.service_url
            )
            self.client = AgentMemClient(agent_mem_config)

            if self.client.connect():
                logger.info("Agent-mem hook initialized successfully")
                self._initialized = True
            else:
                logger.warning("Failed to connect to Agent-mem")
                self.client = None

        except Exception as e:
            logger.error(f"Failed to initialize Agent-mem hook: {e}")
            self.client = None

    def on_action_logged(self, *, step: StepOutput, action_data: dict):
        """记录action"""
        if not self._initialized or not self.client:
            return

        try:
            # 准备Problem File数据
            pf_data = self._prepare_problem_file(step, action_data)

            # 异步记录action（不阻塞主流程）
            self._run_async(self.client.log_action, pf_data)

        except Exception as e:
            logger.warning(f"Failed to log action: {e}")

    def on_planning_start(self, *, task_description: str, context: dict):
        """规划开始"""
        if not self._initialized or not self.client:
            return None

        # 检查缓存
        cache_key = f"planning:{task_description}:{hash(str(context))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # 获取规划建议
            tips = self.client.get_planning_tips(
                task_description=task_description,
                context=context
            )

            if tips:
                # 缓存结果
                self._cache[cache_key] = tips
                if len(self._cache) > self.config.cache_size:
                    # 清理旧缓存
                    self._cache.pop(next(iter(self._cache)))

                return tips

        except Exception as e:
            logger.warning(f"Failed to get planning tips: {e}")

        return None

    def on_execution_error(self, *, step: StepOutput, error_type: str,
                          error_message: str, error_details: dict):
        """执行错误"""
        if not self._initialized or not self.client:
            return None

        # 检查缓存
        cache_key = f"error:{error_type}:{error_message}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # 准备错误上下文
            error_context = {
                "error_type": error_type,
                "error_message": error_message,
                "error_details": error_details,
                "current_action": {
                    "thought": step.thought,
                    "action": step.action
                }
            }

            # 获取修复建议
            fixes = self.client.get_fix_suggestions(
                error_info=error_context,
                context=error_details.get("context", {})
            )

            if fixes:
                # 缓存结果
                self._cache[cache_key] = fixes
                if len(self._cache) > self.config.cache_size:
                    self._cache.pop(next(iter(self._cache)))

                return fixes

        except Exception as e:
            logger.warning(f"Failed to get fix suggestions: {e}")

        return None

    def on_task_complete(self, *, task_result: dict):
        """任务完成"""
        if not self._initialized or not self.client:
            return

        try:
            # 异步处理任务完成事件
            self._run_async(self._process_task_completion, task_result)

        except Exception as e:
            logger.warning(f"Failed to process task completion: {e}")

    def _prepare_problem_file(self, step: StepOutput, action_data: dict) -> dict:
        """准备Problem File数据"""
        return {
            "action_type": self._infer_action_type(step.action),
            "intent_text": step.thought,
            "inputs": action_data,
            "tool_calls": self._extract_tool_calls(step.action),
            "outcome": "unknown",  # 将在执行后更新
            "timestamp": action_data.get("timestamp")
        }

    def _infer_action_type(self, action: str) -> str:
        """推断action类型"""
        if action.startswith("edit"):
            return "code_edit"
        elif action.startswith("run"):
            return "run_test"
        elif "bash" in action.lower():
            return "tool_call"
        else:
            return "unknown"

    def _extract_tool_calls(self, action: str) -> list:
        """提取工具调用"""
        # 简化实现，实际需要解析action字符串
        return [{"command": action.strip()}]

    def _run_async(self, func, *args, **kwargs):
        """异步执行函数"""
        import threading
        thread = threading.Thread(
            target=self._safe_execute,
            args=(func,) + args,
            kwargs=kwargs,
            daemon=True
        )
        thread.start()

    def _safe_execute(self, func, *args, **kwargs):
        """安全执行函数"""
        try:
            func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Async execution failed: {e}")

    def _process_task_completion(self, task_result: dict):
        """处理任务完成"""
        # 这里可以触发异步处理，如RCA分析、信念更新等
        pass
```

## 5. 配置方案

### 5.1 环境变量配置
```bash
# 启用Agent-mem
export AGENT_MEM_ENABLED=true

# 运行模式
export AGENT_MEM_MODE=embedded  # embedded, service

# 服务模式配置
export AGENT_MEM_SERVICE_URL=http://localhost:8080

# 性能配置
export AGENT_MEM_CACHE_SIZE=100
export AGENT_MEM_TIMEOUT_SECONDS=2.0

# 存储配置
export AGENT_MEM_STORAGE_PATH=./agent_mem_data

# 日志配置
export AGENT_MEM_LOG_LEVEL=INFO
```

### 5.2 配置文件集成
```yaml
# SWE-agent配置文件扩展
agent_config:
  # 现有配置...

  # Agent-mem配置
  agent_mem:
    enabled: true
    mode: "embedded"  # embedded, service, hybrid

    # 嵌入式模式配置
    embedded:
      storage_path: "./agent_mem_data"
      cache_size: 100

    # 服务模式配置
    service:
      url: "http://localhost:8080"
      timeout_seconds: 2.0

    # 检索配置
    retrieval:
      task_level_k: 5
      action_level_k: 10

    # 处理配置
    processing:
      rca_enabled: true
      async_processing: true

    # 日志配置
    logging:
      level: "INFO"
      file: "./agent_mem.log"
```

### 5.3 命令行参数
```bash
# 启用Agent-mem
sweagent run --config config.yaml --agent-mem-enabled

# 指定配置
sweagent run --config config.yaml --agent-mem-config ./agent_mem_config.yaml

# 禁用Agent-mem
sweagent run --config config.yaml --no-agent-mem
```

## 6. 部署方案

### 6.1 嵌入式部署（推荐用于MVP）
```
SWEAgent进程
├── agent_mem/                    # Agent-mem库
│   ├── __init__.py
│   ├── client.py                 # 轻量客户端
│   ├── integration/              # 集成代码
│   │   ├── sweagent_hook.py
│   │   └── __init__.py
│   └── storage/                  # 本地存储
│       ├── local_storage.py
│       └── vector_db.py
├── agent_mem_data/               # 数据目录
│   ├── kg/                       # 知识图谱
│   ├── vectors/                  # 向量存储
│   └── evidence/                 # 证据文件
└── agent_mem.log                 # 日志文件
```

### 6.2 服务化部署
```
# Agent-mem服务
agent_mem_service/
├── server.py                     # gRPC/REST服务
├── core/                         # 核心逻辑
│   ├── memory_agent.py
│   ├── retriever.py
│   └── processor.py
├── storage/                      # 存储后端
│   ├── neo4j_client.py
│   ├── faiss_client.py
│   └── s3_client.py
└── Dockerfile

# SWEAgent客户端
sweagent/
├── agent_mem_client.py           # 轻量客户端
└── integration/
    └── sweagent_hook.py          # Hook实现
```

### 6.3 Docker部署
```dockerfile
# Agent-mem服务Dockerfile
FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install -r requirements.txt

# 复制代码
COPY . .

# 启动服务
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8080"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  agent-mem:
    build: ./agent_mem_service
    ports:
      - "8080:8080"
    volumes:
      - ./agent_mem_data:/data
    environment:
      - AGENT_MEM_STORAGE_PATH=/data
      - AGENT_MEM_LOG_LEVEL=INFO

  sweagent:
    build: ./sweagent
    depends_on:
      - agent-mem
    environment:
      - AGENT_MEM_ENABLED=true
      - AGENT_MEM_MODE=service
      - AGENT_MEM_SERVICE_URL=http://agent-mem:8080
```

## 7. 测试方案

### 7.1 单元测试
```python
# 测试Hook集成
def test_sweagent_memory_hook():
    hook = SWEAgentMemoryHook({"enabled": True})

    # 测试初始化
    mock_agent = Mock()
    hook.on_init(agent=mock_agent)
    assert hook._initialized == True

    # 测试action记录
    step = Mock()
    step.thought = "Fix bug"
    step.action = "edit file.py"
    action_data = {"timestamp": "2024-01-01T00:00:00"}

    hook.on_action_logged(step=step, action_data=action_data)

    # 测试错误处理
    error_details = {"context": {}}
    fixes = hook.on_execution_error(
        step=step,
        error_type="syntax_error",
        error_message="Invalid syntax",
        error_details=error_details
    )

    assert fixes is not None
```

### 7.2 集成测试
```python
# 端到端集成测试
def test_agent_mem_integration():
    # 启动SWEAgent with Agent-mem
    config = RunSingleConfig(
        agent_config={
            "agent_mem": {
                "enabled": True,
                "mode": "embedded"
            }
        }
    )

    # 运行测试任务
    result = run_single(config)

    # 验证Agent-mem功能
    assert os.path.exists("./agent_mem_data")  # 数据目录存在
    assert result["success"] == True  # 任务成功

    # 验证经验记录
    storage = LocalStorage("./agent_mem_data")
    experiences = storage.list_experiences()
    assert len(experiences) > 0
```

### 7.3 性能测试
```python
# 性能测试
def test_agent_mem_performance():
    # 测试Hook对性能的影响
    start_time = time.time()

    # 运行不带Agent-mem
    config_no_mem = RunSingleConfig()
    result_no_mem = run_single(config_no_mem)
    time_no_mem = time.time() - start_time

    # 运行带Agent-mem
    start_time = time.time()
    config_with_mem = RunSingleConfig(
        agent_config={"agent_mem": {"enabled": True}}
    )
    result_with_mem = run_single(config_with_mem)
    time_with_mem = time.time() - start_time

    # 性能差异应在可接受范围内
    performance_overhead = (time_with_mem - time_no_mem) / time_no_mem
    assert performance_overhead < 0.1  # 不超过10%的性能开销
```

## 8. 故障排查与监控

### 8.1 监控指标
```python
# 监控指标收集
class AgentMemMetrics:
    def __init__(self):
        self.metrics = {
            "actions_logged": 0,
            "planning_queries": 0,
            "error_queries": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
            "avg_response_time": 0.0
        }

    def record_action_logged(self):
        self.metrics["actions_logged"] += 1

    def record_query(self, query_type, response_time, cache_hit=False):
        if query_type == "planning":
            self.metrics["planning_queries"] += 1
        elif query_type == "error":
            self.metrics["error_queries"] += 1

        if cache_hit:
            self.metrics["cache_hits"] += 1
        else:
            self.metrics["cache_misses"] += 1

        # 更新平均响应时间
        total_queries = self.metrics["planning_queries"] + self.metrics["error_queries"]
        self.metrics["avg_response_time"] = (
            (self.metrics["avg_response_time"] * (total_queries - 1) + response_time)
            / total_queries
        )
```

### 8.2 日志配置
```python
# 详细日志配置
import logging

def setup_detailed_logging():
    logger = logging.getLogger("agent_mem")

    # 文件日志
    file_handler = logging.FileHandler("agent_mem_detailed.log")
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)

    # 控制台日志
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.setLevel(logging.DEBUG)

    return logger
```

### 8.3 故障排查指南
```
常见问题：
1. Agent-mem未初始化
   - 检查AGENT_MEM_ENABLED环境变量
   - 检查配置文件中的agent_mem.enabled
   - 查看日志中的初始化错误

2. 性能问题
   - 检查缓存大小配置
   - 检查异步处理是否启用
   - 监控响应时间指标

3. 存储问题
   - 检查存储路径权限
   - 检查磁盘空间
   - 验证数据完整性

4. 网络问题（服务模式）
   - 检查服务URL可达性
   - 检查防火墙设置
   - 验证网络延迟
```

## 9. 升级与迁移

### 9.1 版本兼容性
- **v1.0 (MVP)**：基础经验记录和检索
- **v1.1**：添加RCA分析和信念系统
- **v1.2**：添加PDDL3编译和验证
- **v2.0**：服务化架构和多Agent支持

### 9.2 数据迁移
```python
# 数据迁移工具
class DataMigrator:
    def migrate_v1_to_v2(self, v1_data_path, v2_data_path):
        """从v1迁移到v2"""
        # 读取v1数据
        v1_data = self._load_v1_data(v1_data_path)

        # 转换数据格式
        v2_data = self._convert_to_v2_format(v1_data)

        # 保存v2数据
        self._save_v2_data(v2_data, v2_data_path)

        # 验证迁移
        self._validate_migration(v1_data, v2_data)
```

### 9.3 回滚方案
1. **配置回滚**：将agent_mem.enabled设为false
2. **代码回滚**：使用git回退到之前版本
3. **数据备份**：定期备份Agent-mem数据
4. **A/B测试**：新旧版本并行运行，逐步切换

## 10. 安全考虑

### 10.1 数据安全
- **加密存储**：敏感数据加密存储
- **访问控制**：基于角色的访问控制
- **数据脱敏**：日志和监控数据脱敏

### 10.2 网络安全（服务模式）
- **TLS加密**：服务通信使用TLS
- **认证授权**：客户端认证和授权
- **速率限制**：防止滥用

### 10.3 隐私保护
- **数据最小化**：只收集必要数据
- **用户同意**：明确的数据使用同意
- **数据删除**：支持数据删除请求

---

**文档版本**: 1.0
**最后更新**: 2026-02-16
**维护者**: 代码工程师Agent