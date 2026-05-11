# 多 Agent 架构升级实施计划书

**基准版本：** `sweagent_external_tools_v2_2026-04-25`（phase9-v2）  
**目标：** 在不改变编排器和 Docker 环境的前提下，以模块化方式落地 T1-A、T1-B、T1-C 三个 Tier-1 方案  
**日期：** 2026-05-11  
**实施策略：** 每个方案独立成一个可开关的功能模块，用环境变量控制启停，保持与 phase9-v2 行为完全向后兼容

---

## 零、当前架构速查（接入点地图）

```
bridge_hook.py                  ← 核心 Hook，所有事件入口
  on_model_query()              ← 每次 LLM 调用前触发
    _v2_decide_strategy()       ← 策略决策（VERBATIM_REUSE / EXPLORE / fresh）
    _select_hints_for_injection() ← 从 pending buffer 选出 hint
    [注入 hint 到 messages]
  on_actions_generated()        ← agent 生成 action 后触发
    _v2_check_consistency_gate()  ← PatchConsistencyGate（hash 比对）
  on_action_executed()          ← action 执行完、观察返回后触发
  on_run_done()                 ← 一次 attempt 结束

  _buffer_memory_hints()        ← Tool A 响应 → 解析 → 存入 _pending_memory_hints
                                   ↑ T1-A 的改写在此之后、注入之前执行

agent_mem_main.py               ← Tool A 外部进程入口
agent_mem/retrieval/memory_agent.py   ← MemoryAgent：从 GraphStore 检索卡片
agent_mem/storage/graph_store.py      ← 持久化 KV + 图结构
agent_mem/processing/llm_extractor.py ← LLMExperienceExtractor（已有 LLM call 封装）
agent_mem/processing/evaluation_feedback.py ← 写入 BugInvariantCard / BugAntiPatternCard
```

---

## 一、T1-A：Memory Reformulation Agent（记忆重构 Agent）

### 1.1 目标

在 `_buffer_memory_hints()` 完成（原始卡片进入 `_pending_memory_hints`）之后、`_select_hints_for_injection()` 执行之前，用一次 LLM API 调用将通用 hint 文本改写为"与当前 agent 执行状态对齐"的个性化 hint。

**直接针对的失败类型：** sympy-13551 型——BugInvariantCard 内容正确，但 agent 在探索阶段读到修复阶段细节，误判方向。

---

### 1.2 新增文件

**`agent_mem/processing/reformulation_agent.py`**

```python
class ReformulationAgent:
    """
    接收：当前轨迹摘要（最近 N 步的 action+observation） + 原始 hint 条目列表
    输出：改写后的 hint 文本（就地替换 item["hint"]）
    LLM 调用：同 LLMExperienceExtractor.from_env() 的底层封装，可复用现有 API key 配置
    """

    def reformat(
        self,
        hints: list[dict],         # _pending_memory_hints 的当前内容
        trajectory_summary: str,   # 最近 5 步 (action, observation) 的紧凑摘要
        step_phase: str,           # "explore" | "localized" | "fixing" | "pre_submit"
    ) -> list[dict]: ...
```

**Prompt 模板（内嵌在文件中）：**

```
你是一个记忆重构助手。
当前 agent 的执行阶段：{step_phase}
最近 5 步摘要：
{trajectory_summary}

以下是从记忆库检索出的历史经验卡片（原始文本）：
{raw_hints}

请将每条 hint 改写为"与当前执行阶段最相关"的形式：
- 如果当前在探索阶段：突出目标文件/函数的定位信息，省略 diff 细节
- 如果已定位（localized）：突出具体修改方式
- 如果正在修复（fixing）：突出参数签名和关键行
- 如果即将提交（pre_submit）：突出与 BugInvariantCard 的对齐检查点
输出 JSON 数组，格式：[{"original_id": "...", "rewritten_hint": "..."}]
```

---

### 1.3 接入点（bridge_hook.py 的修改）

**修改位置：** `on_model_query()` 内部，`_buffer_memory_hints()` 调用结束之后，`_select_hints_for_injection()` 调用之前。

**新增代码块（约 30 行）：**

```python
# T1-A：记忆重构 Agent（由环境变量控制开关）
if self._t1a_enabled and self._pending_memory_hints:
    summary = self._build_trajectory_summary(window=5)
    phase = self._infer_step_phase()
    self._pending_memory_hints = self._reformulation_agent.reformat(
        list(self._pending_memory_hints), summary, phase
    )
```

**新增辅助方法：**

```python
def _build_trajectory_summary(self, window: int = 5) -> str:
    """从 self._trajectory_window（新增的滑动窗口 deque）取最近 window 步"""
    ...

def _infer_step_phase(self) -> str:
    """根据 _step_index、_seen_files、_is_code_edit_action 历史推断当前阶段"""
    # explore：step < 10 且无代码编辑记录
    # localized：有文件定位但无编辑
    # fixing：已有编辑动作
    # pre_submit：最近有 submit 动作或 step > 35
    ...
```

---

### 1.4 轨迹窗口维护（bridge_hook.py）

在 `on_action_executed()` 中追加：

```python
# T1-A 依赖：维护滑动轨迹窗口
self._trajectory_window.append({
    "step": self._step_index,
    "action": step.action[:300],
    "observation": str(step.observation)[:400],
})
```

`__init__` 中初始化：`self._trajectory_window: deque = deque(maxlen=5)`

---

### 1.5 开关与配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SWE_AGENT_T1A_ENABLED` | `false` | 是否启用 Reformulation Agent |
| `SWE_AGENT_T1A_TIMEOUT_SEC` | `6.0` | LLM 调用超时，纳入 Watchdog overhead 计算 |
| `SWE_AGENT_T1A_MODEL` | 同 LLMExperienceExtractor 的 MODEL_NAME | 可单独指定用更便宜的模型 |

**Fallback：** LLM 调用失败（超时/异常）时，直接使用原始 hint 文本，不阻塞主流程。

---

### 1.6 测试方案

**新增测试文件：** `agent_mem/tests/test_t1a_reformulation.py`

- `test_reformat_explore_phase`：探索阶段时，改写后 hint 不包含完整 diff
- `test_reformat_fixing_phase`：修复阶段时，改写后 hint 突出参数签名
- `test_fallback_on_llm_error`：LLM 超时时，返回原始 hint 不报错
- `test_disabled_by_env`：`T1A_ENABLED=false` 时，不调用 LLM

---

## 二、T1-B：Async Interim Memory Mining（实时中间记忆写入）

### 2.1 目标

在 attempt 内部满足特定条件时，将当前已发现的"bug 定位信息"**立即异步写入**一个 `in_progress_cache`（独立于主 GraphStore），供同实例的后续 attempt 或并行 attempt 在启动时读取，跳过重复探索。

---

### 2.2 触发条件（任一满足）

在 `on_action_executed()` 中检测：

| 条件 | 检测逻辑 |
|------|---------|
| 连续 3 步 observation 中出现 `文件路径:行号` 模式 | 正则 `r'([a-zA-Z_/]+\.py):(\d+)'`，计数器 `_localization_hits` |
| agent 首次成功运行目标测试（observation 含 "passed"） | `_first_test_pass` flag |
| `_is_code_edit_action()` 首次触发 | `_first_edit_done` flag |

---

### 2.3 新增文件

**`agent_mem/storage/interim_cache.py`**

```python
class InterimCache:
    """
    文件系统 JSON 缓存，路径：{graph_store_dir}/interim/{instance_id}.json
    线程安全：用 filelock 保证并发读写（同实例多 attempt 场景）
    生命周期：attempt 结束后不清除（供后续 attempt 读取）；整个 instance 解决后自动归档
    """

    def write_interim_card(
        self,
        instance_id: str,
        attempt_id: str,
        card_type: str,                   # "InterimLocalizationCard" | "InterimProgressCard"
        localization: dict,               # {file, function, line_range, confidence}
        source_step: int,
    ) -> None: ...

    def read_interim_cards(self, instance_id: str) -> list[dict]: ...

    def archive(self, instance_id: str) -> None: ...
```

---

### 2.4 接入点（bridge_hook.py 修改）

**`on_action_executed()` 追加（约 20 行）：**

```python
# T1-B：实时中间记忆写入
if self._t1b_enabled:
    self._t1b_check_and_write_interim(step)
```

**新增方法 `_t1b_check_and_write_interim()`（约 60 行）：**

```python
def _t1b_check_and_write_interim(self, step: StepOutput) -> None:
    obs = str(step.observation)
    # 检查定位模式
    matches = re.findall(r'([a-zA-Z_][a-zA-Z0-9_/]+\.py):(\d+)', obs)
    if matches:
        self._t1b_localization_hits += 1
    else:
        self._t1b_localization_hits = 0

    triggered = (
        self._t1b_localization_hits >= 3
        or (not self._t1b_first_pass_written and "passed" in obs.lower())
        or (not self._t1b_first_edit_written and self._is_code_edit_action(step.action))
    )
    if not triggered:
        return

    # 非阻塞写入（用 threading.Thread）
    import threading
    t = threading.Thread(
        target=self._t1b_write_interim_async,
        args=(matches, step),
        daemon=True,
    )
    t.start()
    # 不等待，不阻塞 Watchdog
```

**Tool A 端扩展：** `agent_mem_main.py` 新增事件类型 `"interim_card_write"` 处理分支，调用 `InterimCache.write_interim_card()`。

**读取时机：** 在 `on_init()` 中，Tool A 响应的初始查询里额外附加 `InterimCache.read_interim_cards(instance_id)` 的内容，作为 hint 注入到第一次 `on_model_query()`。

---

### 2.5 开关与配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SWE_AGENT_T1B_ENABLED` | `false` | 是否启用实时中间记忆写入 |
| `SWE_AGENT_T1B_LOCALIZE_THRESHOLD` | `3` | 连续多少步有定位模式触发写入 |
| `SWE_AGENT_T1B_CACHE_DIR` | `{graph_store_dir}/interim` | 缓存目录 |

**Fallback：** 写入失败时仅记录日志，不影响主 agent。

---

### 2.6 与 GraphStore 的隔离原则

- `InterimCache` 使用独立 JSON 文件，不写入 `graph_store.py` 管理的 SQLite/文件
- 读取时通过一个专门的 hint item type（`"type": "interim_localization"`）注入，`_hint_bucket()` 将其归入 `"general"` 桶（最低优先级），不干扰已验证的 `semantic` 桶卡片

---

### 2.7 测试方案

**新增测试文件：** `agent_mem/tests/test_t1b_interim_cache.py`

- `test_write_and_read_interim_card`：写入后读取内容一致
- `test_concurrent_write_safety`：两个线程并发写入同一 instance_id 不冲突
- `test_trigger_conditions`：三个触发条件各自单独满足时均能触发
- `test_isolation_from_graph_store`：写入 InterimCache 不影响 GraphStore 内容

---

## 三、T1-C：Pre-submit Critic Agent（提交前语义审查 Agent）

### 3.1 目标

在 `_v2_check_consistency_gate()`（hash 比对）之后追加一次 LLM 语义审查，捕获"patch 结构对但细节错"的情况。仅在有有效 `BugInvariantCard` 时触发，无卡直接放行。

**直接针对的失败类型：** astropy-12057 型——`other_class` vs `other_uncert` 参数名错误，hash 比对无法检测。

---

### 3.2 新增文件

**`agent_mem/processing/critic_agent.py`**

```python
@dataclass
class CriticVerdict:
    semantic_match_with_invariant: float    # 0.0 - 1.0
    semantic_match_with_anti_pattern: float # 0.0 - 1.0（越低越好）
    verdict: str                            # "approve" | "revise" | "reject"
    revision_hint: str                      # 给主 agent 的修改建议
    reasoning: str                          # 调试用

class CriticAgent:
    """
    输入：
      - patch_diff: str（完整 patch 文本）
      - bug_description: str（原始 issue）
      - invariant_card: dict（BugInvariantCard）
      - anti_pattern_cards: list[dict]（BugAntiPatternCard 列表）
      - recent_test_outputs: list[str]（最近 3 次测试输出）
    输出：CriticVerdict
    """

    def critique(self, ...) -> CriticVerdict: ...
```

**Prompt 设计：**

```
你是一个 patch 语义审查员。

Bug 描述：{bug_description}

已知正确修复模式（BugInvariantCard）：
  目标文件：{invariant.file}，函数：{invariant.function}
  关键参数签名：{invariant.param_signature}
  关键修改行：{invariant.key_lines}

已知失败模式（BugAntiPatternCard，若有）：
  {anti_patterns_summary}

当前 patch：
{patch_diff}

最近测试输出：
{test_outputs}

请评判：
1. 当前 patch 是否在语义上对齐了 BugInvariantCard？（打分 0-1）
2. 当前 patch 是否重蹈了已知失败模式？（打分 0-1，越低越好）
3. 最终裁定：approve / revise / reject
4. 若 revise/reject，给出一句精确的修改建议

输出严格 JSON：
{"semantic_match_with_invariant": 0.x, "semantic_match_with_anti_pattern": 0.x,
 "verdict": "...", "revision_hint": "...", "reasoning": "..."}
```

---

### 3.3 接入点（bridge_hook.py 修改）

**修改位置：** `on_actions_generated()` 内部，`_v2_check_consistency_gate()` 调用之后。

**新增代码块（约 40 行）：**

```python
# T1-C：Pre-submit Critic Agent
if self._t1c_enabled and self._is_patch_submission(step.action):
    if decision == "allow" and self._v2_active_invariants:
        critic_verdict = self._t1c_run_critic(step)
        if critic_verdict.verdict == "revise":
            # 将 revision_hint 作为高优先级 hint 注入下一次 on_model_query
            self._enqueue_system_hint(
                hint=f"[Critic Review] {critic_verdict.revision_hint}",
                family_id="critic_revision",
                priority="semantic",
            )
        elif critic_verdict.verdict == "reject":
            # 触发 force_reuse：从 BugInvariantCard 构造提交
            decision = "force_reuse"
            self._v2_apply_gate_decision(step, "force_reuse")
```

**新增方法 `_t1c_run_critic()`（约 50 行）：**

```python
def _t1c_run_critic(self, step: StepOutput) -> "CriticVerdict":
    patch_text = self._v2_extract_current_patch_text(step.action)
    best_invariant = self._v2_pick_best_invariant()
    recent_tests = list(self._t1c_recent_test_outputs)[-3:]  # 滑动窗口

    try:
        verdict = self._critic_agent.critique(
            patch_diff=patch_text,
            bug_description=self._instance_id,
            invariant_card=best_invariant,
            anti_pattern_cards=list(self._v2_active_anti_patterns),
            recent_test_outputs=recent_tests,
        )
    except Exception:
        # Critic 不可用 → 直接 approve fallback
        verdict = CriticVerdict(
            semantic_match_with_invariant=1.0,
            semantic_match_with_anti_pattern=0.0,
            verdict="approve",
            revision_hint="",
            reasoning="critic_unavailable_fallback",
        )
    return verdict
```

---

### 3.4 测试输出窗口维护（bridge_hook.py）

在 `on_action_executed()` 中，识别测试相关 observation 并追加到 `_t1c_recent_test_outputs`：

```python
# T1-C 依赖：维护最近测试输出窗口
if any(kw in obs.lower() for kw in ("passed", "failed", "error", "assert")):
    self._t1c_recent_test_outputs.append(obs[:600])
```

`__init__` 中初始化：`self._t1c_recent_test_outputs: deque = deque(maxlen=3)`

---

### 3.5 防止无限改写循环

- `revise` 裁定最多触发 **1 次**：注入 revision_hint 后，设置 `_t1c_revision_pending = True`，下一次 submit 时 Critic 直接返回 `approve`
- `reject` 触发后进入 `force_reuse`，后续提交走 BugInvariant 直接构造，不再调用 Critic
- 超时（默认 10s）直接 `approve`

---

### 3.6 开关与配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SWE_AGENT_T1C_ENABLED` | `false` | 是否启用 Pre-submit Critic |
| `SWE_AGENT_T1C_TIMEOUT_SEC` | `10.0` | Critic LLM 调用超时 |
| `SWE_AGENT_T1C_REVISE_THRESHOLD` | `0.4` | invariant 匹配分低于此值才触发 revise |
| `SWE_AGENT_T1C_REJECT_THRESHOLD` | `0.8` | anti-pattern 匹配分高于此值触发 reject |
| `SWE_AGENT_T1C_MODEL` | 同 LLMExperienceExtractor | 可单独指定 |

---

### 3.7 测试方案

**新增测试文件：** `agent_mem/tests/test_t1c_critic_agent.py`

- `test_approve_on_matching_invariant`：patch 匹配 invariant → approve
- `test_revise_on_param_mismatch`：参数名不符 → revise + 正确建议
- `test_reject_on_anti_pattern_match`：命中失败模式 → reject → force_reuse
- `test_approve_fallback_on_timeout`：LLM 超时 → approve，不阻塞
- `test_no_infinite_revise`：revise 后再次提交直接 approve

---

## 四、整体落地顺序与改动量汇总

### 4.1 建议实施顺序

```
Week 1：T1-A（最低风险，纯新增，不修改任何现有逻辑）
  → 新建 reformulation_agent.py
  → bridge_hook.py 追加 ~60 行（_trajectory_window + _build_trajectory_summary + _infer_step_phase + T1-A 调用块）
  → 新建 test_t1a_reformulation.py

Week 2：T1-C（接入点清晰，直接扩展现有 PatchConsistencyGate 流程）
  → 新建 critic_agent.py
  → bridge_hook.py 追加 ~80 行（_t1c_run_critic + _t1c_recent_test_outputs 维护 + Critic 调用块）
  → 新建 test_t1c_critic_agent.py

Week 3：T1-B（涉及并发 + 新存储层，复杂度最高）
  → 新建 interim_cache.py（含 filelock 并发写入）
  → bridge_hook.py 追加 ~80 行（_t1b_check_and_write_interim + 非阻塞线程调用）
  → agent_mem_main.py 追加 interim_card_write 事件处理
  → on_init() 补充 InterimCache 读取逻辑
  → 新建 test_t1b_interim_cache.py
```

---

### 4.2 改动文件汇总

| 文件 | 操作 | 估算改动行数 |
|------|------|------------|
| `bridge_hook.py` | 修改（纯追加，不改现有逻辑） | +220 行 |
| `agent_mem/processing/reformulation_agent.py` | 新建 | ~150 行 |
| `agent_mem/processing/critic_agent.py` | 新建 | ~180 行 |
| `agent_mem/storage/interim_cache.py` | 新建 | ~120 行 |
| `agent_mem_main.py` | 修改（追加 interim 事件分支） | +30 行 |
| `agent_mem/tests/test_t1a_reformulation.py` | 新建 | ~80 行 |
| `agent_mem/tests/test_t1c_critic_agent.py` | 新建 | ~100 行 |
| `agent_mem/tests/test_t1b_interim_cache.py` | 新建 | ~80 行 |

**总计：** 3 个新模块 + 2 个现有文件的追加修改 + 3 个测试文件

---

### 4.3 向后兼容保证

- 所有三个模块的环境变量默认值均为 `false`，不启用时代码分支完全不执行
- `bridge_hook.py` 的改动全部以"追加"形式实现，不修改任何现有函数的逻辑分支
- T1-C 的 Critic 调用发生在现有 `_v2_check_consistency_gate()` 之后，gate 的原始行为不变
- 新增文件对现有 import 体系无影响（均用 try/except 防止导入失败）

---

### 4.4 Overhead 评估（纳入 Watchdog）

| 模块 | 额外 Overhead | 发生时机 | Watchdog 影响 |
|------|-------------|---------|--------------|
| T1-A Reformulation | ≤6s/次 | 每次 on_model_query | 纳入计时，超时 fallback |
| T1-B Interim Write | ~0s（非阻塞线程） | on_action_executed 触发时 | 不阻塞 Watchdog |
| T1-C Critic | ≤10s/次 | 仅在 submit 时触发 | 纳入计时，超时 approve |

---

## 五、实验设计建议

### 5.1 对照实验设置

```
Control：phase9-v2 原版（T1-A/B/C 均关闭）
T1-A only：SWE_AGENT_T1A_ENABLED=true
T1-C only：SWE_AGENT_T1C_ENABLED=true
T1-A + T1-C：两者同时启用（预期协同效果最好）
T1-B only：SWE_AGENT_T1B_ENABLED=true（需多 attempt 场景才能体现）
All T1：三者同时启用
```

### 5.2 重点观测指标

| 指标 | 观测方式 | 目标 |
|------|---------|------|
| post-success 段 resolved 命中率 | `v2_reuse_explore_decision` + 结果对比 | T1-A+C ≥ 65% |
| 同签名失败重复提交次数 | `v2_patch_consistency_gate` 日志 | T1-B ≤ 1次/instance |
| Critic revise/reject 命中率 | `t1c_critic_verdict` 日志 | 关注 revise→最终 resolve 的转化 |
| 平均步数节省 | 轨迹长度对比 | T1-A（探索阶段）-20%，T1-B -30% |

### 5.3 回退策略

- 任一模块出现连续 3 次超时 → 自动禁用该模块（同 circuit_breaker 逻辑，复用 `_is_circuit_open()`）
- 回退时在 `append_json_log` 中记录 `"event": "t1x_auto_disabled"` 供事后分析

---

## 六、与 phase9-v2 核心模块的关系图

```
phase9-v2 核心流程：
  _buffer_memory_hints()
       ↓
  [T1-A 改写：可选]          ← 新增，纯 before-hook
       ↓
  _select_hints_for_injection()
       ↓
  on_model_query() → 注入 hints
       ↓
  on_actions_generated()
       ↓
  _v2_check_consistency_gate()（hash 比对）
       ↓
  [T1-C Critic：可选]        ← 新增，纯 after-hook
       ↓
  _v2_apply_gate_decision()
       ↓
  on_action_executed()
       ↓
  [T1-B 触发检测：可选]      ← 新增，非阻塞异步
       ↓
  on_run_done()
```

三个 T1 方案均以"插入"而非"替换"的方式接入，不改变 phase9-v2 的主干数据流。
