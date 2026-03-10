# 在线 Stop / Deprioritize 机制设计说明

## 1. 文档目的

本文档回答四个问题：

1. 为什么当前 AgentMem 需要引入在线 `stop / deprioritize` 机制。
2. 这个机制的完整设计是什么。
3. 它为什么在当前代码框架内可行。
4. 它为什么虽然有风险，但仍然比“只靠提示注入”更可靠。

本文档不是代码施工清单，而是一个架构与工程说明文档。目标不是把系统做得更复杂，而是把当前已经暴露出来的“过度探索、注入无效、轨迹失控”问题用最小代价收敛掉。

---

## 2. 背景与动机

### 2.1 当前系统的真实问题

阶段 6 的单实例冒烟测试已经证明三件事：

1. 经验系统可以在线注入提示。
2. 经验系统可以在 `timeout / incomplete` 后回流负经验。
3. 仅靠“向模型提示应该停止”并不能让 agent 真的停止。

也就是说，当前系统的问题已经不再是“能不能提取经验”或“能不能注入经验”，而是：

- agent 在拿到关键事实之后仍然持续扩展搜索空间；
- Tool A 返回的低价值 `workflow_step` / `planning_loop` 家族仍然长期干扰决策；
- closure 类经验虽然被注入了，但模型可以忽略；
- 结果是 step 持续增长、脚本数量持续增长、token 持续增长，而 patch 并没有更快形成。

### 2.2 当前 closure 提示为什么不够

当前做法本质上是：

- 识别到 `over_exploration`
- 生成一条 `closure_signal`
- 把这条信号当成普通 memory hint 注入给模型

这个做法的问题是：

1. 它只是建议，不是控制。
2. 它与其他普通 hint 平级，缺乏运行时优先权。
3. 模型即使“看到了”，也可能继续自由生成偏航动作。
4. 它不会改变后续检索排序，也不会改变动作空间。

所以它不具备真正的“止损”能力。

### 2.3 为什么必须做运行时控制

如果一个系统已经观察到：

- 关键修复线索已经出现；
- 相似探索已经重复发生；
- 新增探索没有带来新的结构性信息；

那么继续把“是否停止”完全交给主模型，是一种坏 taste。

原因很简单：

- 这不是语言理解问题；
- 这是运行时状态控制问题；
- 应该由系统侧显式表达，而不是继续赌模型自觉。

因此，引入在线 `stop / deprioritize` 机制的动机是：

> 把“已经不值得继续探索”的判断，从后验经验总结，前移为运行时约束。

---

## 3. 设计目标与非目标

### 3.1 设计目标

本机制要达到以下目标：

1. 当 agent 已经进入“过度探索”状态时，减少低价值提示继续影响它。
2. 在不大改 SWE-agent 主流程的前提下，尽量收紧动作空间。
3. 将“closure”从普通提示升级为运行时控制状态。
4. 尽量复用当前已有的 hook、memory retrieval、feedback 链路。
5. 保持实现简洁，不引入新的重型调度器或第二套状态机。

### 3.2 非目标

本机制**不**试图做以下事情：

1. 不试图预测最终 patch 是否一定正确。
2. 不试图完全替代模型的自主探索。
3. 不试图一次性做成硬性“自动停止器”。
4. 不引入新的数据库、队列或外部服务。

---

## 4. 核心思想

这个机制不是“让模型更聪明”，而是“让系统更有边界感”。

完整机制分为三层：

1. **检测层（Detection）**  
   判断当前是否出现“过度探索”的证据。

2. **降权层（Deprioritize）**  
   一旦进入 closure 状态，就降低低价值记忆和低价值策略的可见性。

3. **软控制层（Soft Stop）**  
   在 closure 状态下，对某些典型偏航动作给出系统级约束，必要时阻止执行。

三层关系如下：

```text
step / action / observation
    -> RuntimeGuardState 更新
    -> 触发 closure_active
    -> retrieval 降权
    -> 注入 runtime guard
    -> 必要时软阻断动作
```

---

## 5. 为什么这个机制可行

### 5.1 我们已经拥有大部分必需信号

当前系统并不是从零开始。现有代码已经能提供以下运行时信号：

1. `step_index`
2. `first_file_access`
3. `over_exploration` trigger
4. ad-hoc script 名称
5. action 文本
6. observation 文本
7. `memory_injected`
8. `experience_rw_map`
9. `official_eval_feedback`

这些信号足够支撑一个规则型运行时 guard，不需要额外上 LLM 去做在线判定。

### 5.2 这个问题本质上适合规则，不适合再交给 LLM

“是否过度探索”不是一个需要高层语义推理的问题。  
它本质上是以下几类行为模式的组合：

- 已知关键修复线索后仍然创建新的 ad-hoc script
- 已经反复验证但没有 patch
- 继续读无关文件
- 继续执行广泛搜索

这类问题非常适合用规则判定，因为：

1. 可解释
2. 可测试
3. 可回滚
4. 不依赖额外模型推理成本

### 5.3 这个机制可以分层上线，风险可控

这个机制不是一上来就做“硬停机”，而是分阶段：

1. 先做 `deprioritize`
2. 再做 `soft stop`
3. 最后才做 `hard gate`

因此它的可行性不在于“第一次就必须完美”，而在于：

- 每一层都是独立可测的；
- 即使只上线前两层，也已经能减少明显的轨迹浪费；
- 不会立刻破坏主求解链路。

---

## 6. 完整方案

### 6.1 新增运行时状态：RuntimeGuardState

建议在 hook 侧维护一个极小的运行时状态对象：

```text
RuntimeGuardState
  closure_active: bool
  over_exploration_score: float
  key_signal_seen: bool
  validation_success_seen: bool
  steps_since_key_signal: int
  ad_hoc_script_count: int
  duplicate_repro_count: int
  blocked_action_patterns: set[str]
  deprioritized_families: set[str]
  last_key_signal_step: int | None
```

它只服务于当前单次 run，不进入长期记忆图。

### 6.2 关键概念：Key Signal

`key_signal` 指的是：

> agent 已经拿到足以进入“最小修复 + 验证”阶段的关键事实。

在当前 astropy 示例中，以下事实都属于 key signal：

1. `quiet=True` 可以让 `all_world2pix` 返回可用结果；
2. `world_to_pixel_values()` 当前路径没有传 `quiet`；
3. 问题已经能稳定复现；
4. 目标文件和目标调用点已经明确。

换句话说，一旦这些事实出现，系统就不该继续把“广泛探索”当成正常行为。

### 6.3 如何判断“过度探索”

不建议用单一阈值，而是使用积分式判断。

定义四类证据：

#### 证据 A：脚本蔓延

条件：

- 新建 `test_*.py` / `reproduce_*.py` / `debug_*.py` 数量 >= 2

加分：

- `+2.0`

原因：

- 在单问题修复过程中，持续新建 ad-hoc script 往往意味着 agent 没有进入收敛阶段。

#### 证据 B：拿到 key signal 后仍然扩展范围

条件：

- `key_signal_seen = true`
- 且之后又出现：
  - 打开新模块
  - 查找无关函数
  - 跳到与目标 patch 不直接相关的文件

加分：

- `+2.0`

#### 证据 C：验证循环无新进展

条件：

- 连续进行多次验证
- 没有新的 changed files
- 没有新的 patch
- 没有新的 key signal

加分：

- `+1.5`

#### 证据 D：关键线索后步数持续增长

条件：

- `step_count - last_key_signal_step > N`

推荐初始阈值：

- `N = 8`

加分：

- `+1.0`

#### closure 判定

当：

```text
over_exploration_score >= 3.0
```

则：

```text
closure_active = true
```

这个判定的好处是：

- 不是一次误判就触发；
- 多个弱信号叠加才能进入 closure；
- 行为上更稳健。

### 6.4 在线 Deprioritize

当 `closure_active = true` 时，不立刻停机，先做检索层降权。

#### 需要降权的 family

1. `workflow_step`
2. `planning_loop`
3. `belief_tip`

#### 需要提权的 family

1. `closure_signal`
2. `validation_gap`
3. `patch_risk`
4. `negative_strategy`
5. `failure_recovery`

#### 目标效果

不是让 agent 一定停，而是让它后续“更难继续被低价值 workflow 提示带偏”。

### 6.5 在线 Soft Stop

当 `closure_active = true` 时，再叠加一条系统级运行时约束：

```text
Runtime Guard:
- do not create new ad-hoc scripts
- do not inspect unrelated modules
- either validate current minimal fix or stop
```

这个提示不应当走普通 memory hint 预算，而应当作为独立的系统 guard 注入。

原因：

- 普通 hint 与其他建议是并列的；
- runtime guard 应该是“当前运行状态约束”。

### 6.6 软阻断（可选）

这是下一阶段，不建议第一版就做硬。

如果 `closure_active = true` 且下一步 action 命中以下模式：

1. `create test_*.py`
2. `create reproduce_*.py`
3. 大范围 grep 无关模块
4. 查看与目标文件无关的新模块

则不执行该动作，返回一条本地 observation：

```text
Blocked by runtime guard:
closure is active; validate current fix or terminate.
```

这一步风险较高，但效果最强。

---

## 7. 为什么用户会觉得这个机制“不可靠”

这个担心是对的。它的不可靠性主要来自三类风险。

### 7.1 风险一：误判过度探索

有些 case 本来就需要多轮探索，如果太早激活 closure，会截断正常求解。

### 7.2 风险二：影响行为但不保证改善结果

即使把 workflow 压下去，也不代表模型就会更快找到正确 patch。

### 7.3 风险三：系统控制和模型自由度冲突

如果做成硬阻断，可能把少量仍然有价值的后续探索也一起杀掉。

---

## 8. 为什么它仍然值得做

因为当前真实问题已经不是“探索不够”，而是“探索过头”。

从阶段 6 的 smoke 看：

1. agent 已经拿到关键事实；
2. 仍然持续扩展文件和验证脚本；
3. token 和 step 持续增长；
4. 最终以 timeout 结束。

在这种情况下，不做运行时收敛控制，等于默认接受以下结果：

- 低价值探索继续吞掉预算；
- closure 经验变成“看起来有用但实际不起作用”的装饰品；
- 经验系统只能事后总结，不能在线止损。

所以这个机制的价值不在于“保证正确”，而在于：

> 把明显错误的轨迹模式更早截断，把预算留给真正可能解决问题的路径。

---

## 9. 最小可行实现（推荐）

为了降低风险，建议只做下面三步：

### 第一步：Deprioritize

实现：

- `closure_active=true` 后
- 检索层直接压低 `workflow_step/planning_loop/belief_tip`

优点：

- 风险低
- 容易测试
- 不破坏主决策流程

### 第二步：Runtime Guard Message

实现：

- `closure_active=true` 后
- 注入独立的 runtime guard message

优点：

- 比普通 memory hint 更强
- 不需要直接阻断动作

### 第三步：禁止新增 ad-hoc script

实现：

- `closure_active=true` 后
- 阻止继续创建新的 `test_*.py` / `reproduce_*.py`

优点：

- 对当前最明显的噪声行为直接有效
- 作用面小，风险可控

---

## 10. 为什么这个 MVP 可行

### 10.1 已有日志和信号已足够

我们已经能记录：

- step index
- 文件访问
- trigger
- memory injected
- read_ids
- script 名称
- timeout/incomplete feedback

因此 MVP 不依赖新基础设施。

### 10.2 已有代码位置很清晰

可以直接利用现有模块：

- `bridge_hook.py`
  - 检测脚本蔓延
  - 更新 closure 状态
  - 注入 runtime guard
  - 可选阻断特定动作

- `memory_agent.py`
  - 根据 closure 状态调整 family 排序

- `evaluation_feedback.py`
  - 把 timeout/incomplete 回流成负经验

### 10.3 可以逐层验证

这个机制不需要全量 benchmark 才知道有没有效果。  
单实例 smoke 就能看出来：

1. closure 是否触发；
2. workflow 是否降权；
3. ad-hoc script 是否减少；
4. step 是否下降；
5. timeout 前是否更容易形成 patch。

---

## 11. 测试与验收建议

### 11.1 单实例 smoke 验收

同一 instance 前后对比：

1. `memory_injected.selected_family_ids`
2. `read_ids`
3. `step_count`
4. `ad_hoc_script_count`
5. `candidate_count_before_filter`

### 11.2 最关键的通过标准

不是 solved，而是以下四条至少命中三条：

1. `workflow_step` 不再在 closure 后持续主导 `read_ids`
2. ad-hoc script 数量下降
3. 总 step 数下降
4. timeout 后能稳定回流成负经验

### 11.3 回归保护

必须验证：

- 在没有 `key_signal` 的 case 中，不应过早触发 closure
- 在正常需要多步探索的 case 中，不应过早 block

---

## 12. 结论

用户觉得这个机制“不可靠”，这个判断是合理的。

如果把它理解成：

> “加一条提示，让模型自己意识到该停了”

那它确实不可靠。

但如果把它重新定义成：

> “在运行时识别明显的过度探索状态，然后动态降低垃圾策略的可见性，并约束最典型的偏航动作”

那它就变成了一个：

- 小而硬
- 可解释
- 可测试
- 可逐步上线

的工程机制。

它的价值不在于保证 solved，而在于：

1. 降低无意义探索成本；
2. 把 closure 从装饰性经验变成有效控制信号；
3. 为后续 resolved rate 提升创造更干净的轨迹基础。

---

## 13. 推荐的下一步

建议按以下顺序施工：

1. `closure_active` 后检索层屏蔽/强降权 `workflow_step/planning_loop`
2. 加独立 `runtime_guard_message`
3. `closure_active` 后禁止新增 `test_*.py / reproduce_*.py`
4. 如果前 3 步效果仍不够，再考虑硬性 action gate

这个顺序的好处是：

- 改动最小
- 风险最低
- 能最快验证是否真的有帮助

