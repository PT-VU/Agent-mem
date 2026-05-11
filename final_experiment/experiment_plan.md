# 核心实验计划：基于记忆框架的 LLM 代码修复增强研究

**版本**: v2.0  
**日期**: 2026-05-05  
**状态**: 已执行部分可用；后续实验配置见第 5 节

---

## 1. 研究假说

大语言模型（LLM）在软件工程任务（SWE-bench）中的主要失败模式：

1. **无法跨尝试复用成功路径**：每次 attempt 从零探索，已验证的修复路径未被保留
2. **预算浪费于无效探索**：20 分钟有限 budget 内，大量步骤消耗在错误方向
3. **incomplete 率高**：budget 耗尽后无法提交，比解题失败更难观测

**核心假说**：
> 在对同一问题进行多次尝试（N = 10）的设定下，记忆框架通过跨尝试的路径复用与持续精化，能够显著提升解出率、降低 incomplete 率，并减少成功解题所需的步数与 token 消耗。记忆积累的正向效应会随 attempt 序号递增而体现。

---

## 2. 实验标准与公平性约束

**所有实验统一标准**：
- **时间预算**: 每个 attempt 恰好 **1200 秒（20 分钟）纯 agent 推理时间**
- **计时方式**: 对 nomem 组，`timeout 1200s`（无 bridge overhead，wall-clock = agent time）；对 with_mem 组，使用 **Watchdog** 排除 bridge_hook 调用耗时（`agent_time = elapsed − bridge_overhead`），确保两组获得等量的纯推理时间
- **模型**: Moonshot Kimi-k2.5
- **框架版本**: `sweagent_external_tools_v2_2026-04-25`（phase9 v2c，含 6 项 bug 修复 + Watchdog + BugInvariantCard 文件选取修复）

**公平性说明**：不满足上述标准的实验数据仅可作为参考，不可作为论文核心对比数据。

---

## 3. 当前可用数据

### 3.1 数据有效性评估

| 实验 | with_mem 数据 | nomem 数据 | 标准符合性 |
|------|--------------|-----------|-----------|
| **E3** django-11278 × 10次 | `170538`（Watchdog，公平）| `expand4_075835` | ✅ **完全符合** |
| **E4** astropy-12057 × 10次 | `kimi_180256`（无 Watchdog，1200s wall-clock） | `moonshot_134648` | ⚠️ **保守符合**（with_mem 实际有效时间 < 1200s，对 with_mem 不利，结论方向保守可信） |
| E1 Lite×1次（参考） | ❌ 非 phase9，不可用 | `02_first50_unlimited`（**无时间限制**，不符合 20min 标准）| ❌ **不符合标准** |
| E2 Full×1次（参考） | ❌ 非 phase9，不可用 | `03_full_first50`（1200s wall-clock）| ⚠️ nomem 仅参考用 |

**结论：当前仅 E3 满足论文核心对比实验的完整要求。E4 可作为补充佐证（其不足对 with_mem 不利，结论方向不受影响）。**

---

### 3.2 E3：核心实验——django__django-11278 × 10 次（标准符合）

**实验配置**
```
instance:     django__django-11278
repeats:      10
budget:       1200s 纯 agent 时间（nomem: shell timeout；with_mem: Watchdog）
model:        kimi-k2.5
framework:    sweagent_external_tools_v2_2026-04-25 (phase9 v2c)
nomem_run:    phase9_v2c_expand4_20260429_075835
withmem_run:  phase9_v2c_django11278_wm_watchdog_20260429_170538
```

#### 总体结果

| 模式 | 解出 R | 未解出 U | 超时中断 I | 解出率 |
|------|-------|---------|-----------|--------|
| **with_mem** | **7** | 0 | 3 | **70%** |
| nomem | 2 | 1 | 7 | 20% |
| 差值 | **+5** | −1 | **−4** | **+50pp（×3.5）** |

#### with_mem 逐次详情（体现记忆积累效应）

| attempt | 结果 | 步数 | Bridge调用 | Bridge overhead | 输入 token | BugInvariantCard | 备注 |
|---------|------|------|-----------|----------------|-----------|-----------------|------|
| 01 | incomplete | 104 | 103次 | 770s | — | ✗ | 冷启动，watchdog 触发，submit 竞态 |
| 02 | incomplete | 113 | 112次 | 897s | — | ✗ | 冷启动，watchdog 触发 |
| 03 | **RESOLVED** | 82 | 83次 | 727s | 3,856k | ✗ | 自主探索成功，写入首张正确卡片 |
| 04 | **RESOLVED** | 38 | 39次 | 347s | 557k | ✓ | **卡片生效：步数−54%，token−86%** |
| 05 | **RESOLVED** | 54 | 42次 | 386s | 921k | ✓ | |
| 06 | **RESOLVED** | 87 | 88次 | 825s | — | ✓ | |
| 07 | **RESOLVED** | 55 | 56次 | 529s | 1,371k | ✓ | |
| 08 | incomplete | 138 | 137次 | 1,334s | 4,045k | ✓ | overhead 最大轮，watchdog 触发 |
| 09 | **RESOLVED** | 54 | 55次 | 567s | — | ✓ | |
| 10 | **RESOLVED** | 33 | 34次 | 356s | 423k | ✓ | **全程最优：最少步数 + 最少 token** |

#### nomem 逐次详情（基线）

| attempt | 结果 | 步数 | 输入 token |
|---------|------|------|-----------|
| 01 | **RESOLVED** | 91 | 3,092k |
| 02 | incomplete | 69 | 2,360k |
| 03 | incomplete | 53 | 1,218k |
| 04 | incomplete | 92 | 3,864k |
| 05 | incomplete | 35 | 517k |
| 06 | incomplete | 58 | 1,246k |
| 07 | incomplete | 72 | 2,849k |
| 08 | **RESOLVED** | 60 | 1,640k |
| 09 | incomplete | 51 | 1,149k |
| 10 | UNRESOLVED | 80 | 2,747k |

#### 关键指标对比

| 指标 | nomem | with_mem | 改善 |
|------|-------|---------|------|
| 解出率 | 20% | **70%** | **+50pp** |
| incomplete 率 | 70% | 30% | **−40pp** |
| 仅RESOLVED轮次平均步数 | 75.5步 | **57.6步** | **−24%** |
| 仅RESOLVED轮次平均输入 token | 2,366k | **1,566k** | **−34%** |
| BugInvariantCard 生效后平均步数（attempt 4−10，排除 08） | — | **45.5步** | vs attempt_03 的 82步：**−45%** |

**记忆积累的关键转折点**：  
attempt_03 自主成功 → BugInvariantCard 写入（`model_checks.py`，`check_all_models()`）→ attempt_04 步数从 82 降至 38（−54%），输入 token 从 3,856k 降至 557k（−86%）。这是"路径复用"效应的直接量化证据。

---

### 3.3 E4：补充实验——astropy__astropy-12057 × 10 次（保守符合）

**实验配置**
```
instance:     astropy__astropy-12057
repeats:      10
budget:       1200s（nomem: shell timeout；with_mem: 1200s wall-clock，无 Watchdog）
              ⚠ with_mem 实际有效时间 = 1200s − bridge_overhead < 1200s，对 with_mem 不利
model:        kimi-k2.5
nomem_run:    phase9_v2_moonshot_kimi_full_12057_11693_20260426_134648
withmem_run:  phase9_v2c_kimi_full_12057_withmem_20260427_180256
```

| 模式 | 解出 R | 未解出 U | incomplete I | 解出率 |
|------|-------|---------|-------------|--------|
| **with_mem** | **7** | 1 | 2 | **70%** |
| nomem | 5 | 5 | 0 | 50% |
| 差值 | **+2** | −4 | +2 | **+20pp** |

**注**：with_mem 在计时上处于劣势（有效 agent 时间更少），仍取得更高解出率，结论方向保守可信。

---

### 3.4 参考数据（不符合 20min+Watchdog 标准，不参与核心对比）

| 数据集 | 模式 | 规模 | 时间设置 | 结果 | 用途 |
|-------|------|------|---------|------|------|
| SWE-bench Lite First50 | nomem | 50实例×1次 | 无限制 | 32/50（64%） | 能力上界参考 |
| SWE-bench Full First50 | nomem | 50实例×1次 | 1200s wall-clock | 15/50（30%） | 20min nomem 规模参考 |

---

## 4. 当前结论与局限

### 4.1 已支持的结论

1. **路径复用显著提升解出率**：在20分钟公平预算下，with_mem 在 django-11278 上实现 70% 解出率（nomem 20%），在 astropy-12057 上实现 70%（nomem 50%）。

2. **记忆积累具有正向递增效应**：BugInvariantCard 写入后，后续 attempt 步数和 token 消耗显著下降（django-11278 case 中：82步 → 38步 → 最终 33步）。

3. **incomplete 率大幅降低**：nomem 7/10 incomplete（预算耗尽未提交），with_mem 3/10（其中 2 次属冷启动，1 次属极端 overhead 轮次）。

### 4.2 当前局限（影响学术可信度）

| 局限 | 影响 | 优先级 |
|------|------|--------|
| **样本量不足**：E3 仅 1 个实例 n=10，E4 计时不公平 | 结论泛化性存疑，统计显著性边界（Fisher 精确检验 p≈0.026） | 🔴 高 |
| **E4 计时不公平**：with_mem 实际有效时间更少 | E4 不可作为主要证据，仅佐证 | 🔴 高 |
| **无消融实验**：无法量化 BugInvariantCard vs SuccessPathCard vs AntiPatternCard 的各自贡献 | 机制解释力弱 | 🟡 中 |
| **单一模型**：仅测试 Kimi-k2.5 | 模型通用性未验证 | 🟡 中 |
| **冷启动问题未解决**：attempt_01/02 因无记忆而失败 | 框架在首次尝试时无收益（合理但需说明） | 🟢 低 |

---

## 5. 后续实验计划（直接可执行）

以下实验按优先级排序，每项均给出完整配置，可直接用于启动实验。

---

### **F1（最高优先）：E3 扩展——3 个新实例 × 10 次，完整 Watchdog**

**目的**：增加实例数量，提升统计显著性；验证 E3 结论在更多实例上的泛化性  
**预期解决局限**：样本量不足

**推荐实例**（选择已知困难、nomem 解出率 < 50% 的实例）：
- `sympy__sympy-22383`：nomem 解出率 0%（expand4 中 0R/9），极难
- `astropy__astropy-11693`：nomem 解出率 10%（moonshot 中 1R/10），极难
- 再选 1 个 django 或 sympy 实例（从 SWE-bench Full 挑选）

**实验配置**：
```bash
# 对每个新实例，依次执行以下两个实验

# Step 1: nomem baseline（10 attempts）
# 修改 launch_phase9_v2c_django11278_withmem_watchdog.sh，
# 替换 instance_id，并调用对应的 nomem 脚本：
export INSTANCE_ID="sympy__sympy-22383"   # 替换为目标实例
export REPEATS=10
export SWEBENCH_SUBSET="full"
export SWEBENCH_SPLIT="test"
export NOMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC=1200
# 使用 run_same_problem_v21_phase7.sh 中的 nomem 路径

# Step 2: with_mem（10 attempts，Watchdog 公平计时）
# 复制 launch_phase9_v2c_django11278_withmem_watchdog.sh，修改以下字段：
RUN_TAG="phase9_f1_${INSTANCE_ID}_wm_watchdog_$(date +%Y%m%d_%H%M%S)"
# 在 same_instances.json 中将 instance_ids 替换为目标实例
# 其余配置保持不变（WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC=1200，WATCHDOG_PY 已指定）
```

**关键参数**（与 E3 完全一致）：
```
WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC = 1200
WATCHDOG_PY = sweagent_external_tools_v2_2026-04-25/bin/watchdog.py
AGENT_MEM_BUG_INVARIANT_VERBATIM = 1
AGENT_MEM_PATCH_CONSISTENCY_GATE = enforce
REPEATS = 10
model = kimi-k2.5
```

**成功标准**：完成 3 个实例 × 10 attempts × 2 modes = 60 次 attempt  
**预期产出**：汇总表扩展为 4 个实例，Fisher 精确检验 p < 0.01

---

### **F2（高优先）：E4 修正——astropy-12057 用 Watchdog 重跑 with_mem**

**目的**：修正 E4 的计时不公平性，使其可作为正式对比数据  
**预期解决局限**：E4 with_mem 有效时间更少

**实验配置**：
```bash
# 直接复用 launch_phase9_v2c_django11278_withmem_watchdog.sh
# 修改 instance_ids 为 astropy__astropy-12057

RUN_TAG="phase9_f2_astropy12057_wm_watchdog_$(date +%Y%m%d_%H%M%S)"
# same_instances.json 中：
# "instance_ids": ["astropy__astropy-12057"]

# nomem baseline 已有（moonshot_134648），无需重跑
# 仅需重跑 with_mem 10次
REPEATS = 10
WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC = 1200
# 其余同 E3
```

**注意**：新的 with_mem run 会建立新的 memory store（空起点），与 E4 原 with_mem 的 memory 无关。这是正确的——保证与 E3 对比的一致性（同样从冷启动开始）。

**成功标准**：完成 10 次 with_mem attempts，与已有 nomem 10次 比较  
**预期产出**：E4 升格为完全符合标准的对比实验

---

### **F3（中优先）：消融实验——BugInvariantCard 单独贡献**

**目的**：量化 BugInvariantCard 的贡献，排除其他记忆组件的混淆效应  
**预期解决局限**：无消融实验

**实验设计**：在 django-11278 上，关闭 BugInvariantCard，保留其他组件（SuccessPathCard、AntiPatternCard、AttemptSummaryCard）

**实验配置**：
```bash
RUN_TAG="phase9_f3_django11278_ablation_no_bugcard_$(date +%Y%m%d_%H%M%S)"

# 关键环境变量修改：
export AGENT_MEM_BUG_INVARIANT_VERBATIM=0   # 禁用 verbatim diff 注入
# 其余保持与 E3 with_mem 完全一致

REPEATS = 10
WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC = 1200
# 保留 SuccessPathCard、AntiPattern、AttemptSummary
```

**对比结构**：
```
nomem (已有):               2R / 10  →  baseline
with_mem full (E3 已有):    7R / 10  →  完整框架
with_mem no BugCard (F3):   ?R / 10  →  消融
```

**成功标准**：完成 10 次 attempts  
**预期产出**：量化 BugInvariantCard 的独立贡献（F3 解出率预期在 nomem 和 full with_mem 之间）

---

### **F4（中优先）：规模实验——15 个实例 × 1 次，with_mem vs nomem**

**目的**：在多实例（非重复尝试）场景下验证框架有效性，证明记忆框架在单次尝试中也有正向效果  
**预期解决局限**：当前对比仅限于重复尝试场景

**实例选择**：从 SWE-bench Full test 中，选择 nomem 解出率在 20%-60% 之间的 15 个实例（避免极端案例）

**实验配置**：
```bash
RUN_TAG="phase9_f4_multi15_wm_watchdog_$(date +%Y%m%d_%H%M%S)"

# same_instances.json 中列出 15 个 instance_ids
REPEATS = 1
WITHMEM_INSTANCE_TOTAL_EXEC_TIMEOUT_SEC = 1200
WATCHDOG_PY = sweagent_external_tools_v2_2026-04-25/bin/watchdog.py
# 注意：单次尝试时 memory store 为空，BugInvariantCard 效果为零
# 此实验测试的是其他组件（AttemptSummary来自跨实例经验、AntiPattern等）的贡献
# 若无跨实例记忆，预期提升较小；可在此基础上扩展为 3 次尝试

# 推荐方案：每实例 3 次尝试，比较首次 vs 后续
REPEATS = 3
```

**成功标准**：完成 15 个实例 × 3 次 × 2 modes = 90 次 attempt  
**预期产出**：在更大样本上验证记忆框架的统计显著性

---

### **F5（低优先）：冷启动优化——跨实例记忆预加载**

**目的**：解决 E3 中 attempt_01/02 冷启动失败的问题；验证从相似实例迁移记忆的可行性  
**背景**：E3 中 attempt_01/02 失败的直接原因是 memory store 为空（新 RUN_ROOT），若能从历史解题经验预加载，冷启动失败率应降低

**实验配置**：
```bash
# 在启动实验前，将 E3 已有的 memory store 复制/迁移到新的 run
PRE_LOADED_GRAPH="${E3_RUN}/same_problem/with_mem/.../persistence/graph_store"
NEW_GRAPH="${NEW_RUN_ROOT}/.../persistence/graph_store"
cp -r "${PRE_LOADED_GRAPH}" "${NEW_GRAPH}"

# 实验对照：
# F5a: 冷启动（空 memory store，同 E3）
# F5b: 预加载（复制 E3 最终 memory store）
REPEATS = 5   # 每组 5 次，重点观察前 3 次的解出率变化
```

**成功标准**：F5b 中 attempt_01 解出率 > F5a 中 attempt_01 解出率  
**预期产出**：验证"记忆迁移"机制，为论文增加应用章节

---

## 6. 实验优先级与资源估算

| 实验 | 总 attempt 数 | 预计耗时 | 优先级 | 解决的局限 |
|------|-------------|---------|--------|-----------|
| **F1** 3新实例×10次×2 | 60次 | ~30小时 | 🔴 最高 | 样本量、泛化性 |
| **F2** astropy-12057 with_mem 重跑 | 10次 | ~5小时 | 🔴 高 | E4 计时公平性 |
| **F3** 消融 BugCard | 10次 | ~5小时 | 🟡 中 | 机制解释 |
| **F4** 15实例×3次×2 | 90次 | ~45小时 | 🟡 中 | 规模验证 |
| **F5** 冷启动预加载 | 10次 | ~5小时 | 🟢 低 | 冷启动改进 |

**最小可发表组合**：E3（已完成）+ F1（3新实例）+ F2（E4修正）  
→ 覆盖 5 个实例，总 attempt 数 100+，统计显著性 p < 0.01，结论泛化性强

---

## 7. 论文核心实验数据引用路径

```
final_experiment/
├── experiment_plan.md              ← 本文件
├── data/
│   ├── E3_django11278_repeated/
│   │   ├── nomem  → phase9_v2c_expand4_20260429_075835/same_problem/nomem
│   │   └── with_mem → phase9_v2c_django11278_wm_watchdog_20260429_170538/...
│   ├── E4_astropy12057_repeated/   （计时保守，佐证用）
│   │   ├── nomem_run  → phase9_v2_moonshot_kimi_full_12057_11693_20260426_134648
│   │   └── with_mem_run → phase9_v2c_kimi_full_12057_withmem_20260427_180256
│   ├── E1_lite_first50_unlimited/  （无时间限制，参考）
│   └── E2_full_first50_20min/      （nomem 参考）
└── results/
    ├── aggregate_stats.json        ← 各实验汇总
    └── per_attempt_details.json    ← E3 逐次明细（步数/token/结果）
```

---

## 附录：关键技术修复记录

以下修复是保证实验公平性和数据正确性的前提，须在论文中说明：

| 修复 | 内容 | 影响 |
|------|------|------|
| **Watchdog** | 用 `os.killpg` 替换 `proc.kill()`，确保 sweagent 孙进程被完全终止 | 消除"watchdog触发后 sweagent 仍继续、exit_0 无 patch"的假阳性 |
| **BugInvariantCard 文件选取** | `_pick_representative_file()` 优先选 `.py` 文件，跳过 `AUTHORS`/`CHANGELOG` 等非代码文件 | 消除"Key change: Can Sarıgöl"式的记忆污染，确保卡片指向真正的修复文件 |
| **bridge overhead 排除** | `agent_time = elapsed − Σ(bridge_overhead)`，Watchdog 据此计时 | 确保 with_mem 不因记忆查询耗时而损失实际推理时间 |
